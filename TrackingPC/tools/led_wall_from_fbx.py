"""Makes hub/led_wall.json (the LED wall for the hub's 3D view) from the lab's LEDWall.fbx.

Run once, when the wall model changes:
    python tools/led_wall_from_fbx.py "<path>/LEDWall.fbx"

The FBX holds 240 separate panel quads (20 x 12) in metres: x is the curve depth (-0.3..0), y the width
(+-2.47), z the height (0..3). They are placed in tracking space (cm; X towards the wall, Y to the right
seen facing the wall, Z up) exactly as NDC_Basic places the same mesh (README 4.3): component LEDWALL at
(279, 16, 0), yaw 180. So the middle of the curve is at X 309 and its edges at 279, as measured.
Output: "panels" (every panel edge once) and "outline" (edges of the whole wall), as segments
[x1, y1, z1, x2, y2, z2] in cm. Reads only the binary FBX format (version 7400 and later), no libraries.
"""
import json
import pathlib
import struct
import sys
import zlib
from collections import Counter

import numpy as np

PLACE = np.array([279.0, 16.0, 0.0])  # NDC_Basic: LEDWALL at nDisplayXform (279, 16, 150) + (0, 0, -150)


def read_fbx(path):
    data = pathlib.Path(path).read_bytes()
    if not data.startswith(b"Kaydara FBX Binary"):
        raise SystemExit("not a binary FBX file")
    wide = struct.unpack_from("<I", data, 23)[0] >= 7500

    def prop(pos):
        kind = chr(data[pos])
        pos += 1
        simple = {"Y": "<h", "C": "<?", "I": "<i", "F": "<f", "D": "<d", "L": "<q"}
        if kind in simple:
            return struct.unpack_from(simple[kind], data, pos)[0], pos + struct.calcsize(simple[kind])
        if kind in "fdlib":
            length, encoding, size = struct.unpack_from("<III", data, pos)
            raw = data[pos + 12:pos + 12 + size]
            raw = zlib.decompress(raw) if encoding == 1 else raw
            dtype = {"f": "<f4", "d": "<f8", "l": "<i8", "i": "<i4", "b": "u1"}[kind]
            return np.frombuffer(raw, dtype)[:length], pos + 12 + size
        if kind in "SR":
            size = struct.unpack_from("<I", data, pos)[0]
            return data[pos + 4:pos + 4 + size], pos + 4 + size
        raise ValueError(f"unknown FBX property type {kind!r}")

    def node(pos):
        if wide:
            end, count, _, name_len = struct.unpack_from("<QQQB", data, pos)
            pos += 25
        else:
            end, count, _, name_len = struct.unpack_from("<IIIB", data, pos)
            pos += 13
        if end == 0:
            return None, pos
        name = data[pos:pos + name_len].decode()
        pos += name_len
        props = []
        for _ in range(count):
            value, pos = prop(pos)
            props.append(value)
        children = []
        while pos < end:
            child, pos = node(pos)
            if child is None:
                break
            children.append(child)
        return (name, props, children), end

    nodes, pos = [], 27
    while pos < len(data) - 200:
        found, pos = node(pos)
        if found is None:
            break
        nodes.append(found)
    return nodes


def find(nodes, name):
    for n in nodes:
        if n[0] == name:
            yield n
        yield from find(n[2], name)


def main():
    geometry = next(find(read_fbx(sys.argv[1]), "Geometry"))
    vertices = next(find(geometry[2], "Vertices"))[1][0].reshape(-1, 3)
    index = next(find(geometry[2], "PolygonVertexIndex"))[1][0]
    # Polygons end with a negative index (bitwise not of the last vertex).
    polygons, current = [], []
    for i in index:
        current.append(int(i) if i >= 0 else int(~i))
        if i < 0:
            polygons.append(current)
            current = []
    tracking = PLACE + np.column_stack([-vertices[:, 0], -vertices[:, 1], vertices[:, 2]]) * 100.0  # yaw 180, m to cm
    points = [tuple(np.round(p, 1)) for p in tracking]
    edges = Counter()
    for polygon in polygons:
        for a, b in zip(polygon, polygon[1:] + polygon[:1]):
            edges[tuple(sorted((points[a], points[b])))] += 1
    panels = [list(a) + list(b) for a, b in edges]
    # A panel edge on the wall's border belongs to one panel only; inside, two panels share it.
    outline = [list(a) + list(b) for (a, b), n in edges.items() if n == 1]
    middle = tracking[np.abs(tracking[:, 1] - PLACE[1]) < 5]
    print(f"{len(polygons)} panels, {len(panels)} edges, {len(outline)} on the outline; "
          f"X {tracking[:, 0].min():.0f}..{tracking[:, 0].max():.0f} (middle at {middle[:, 0].max():.0f}), "
          f"Y {tracking[:, 1].min():.0f}..{tracking[:, 1].max():.0f}, Z {tracking[:, 2].min():.0f}..{tracking[:, 2].max():.0f}")
    out = pathlib.Path(__file__).resolve().parent.parent / "hub" / "led_wall.json"
    out.write_text(json.dumps({"source": "LEDWall.fbx, placed as NDC_Basic places it (README 4.3)",
                               "panels": panels, "outline": outline}, separators=(",", ":")))
    print(f"written {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
