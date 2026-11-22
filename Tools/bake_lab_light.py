r"""Bakes the room's light for walls and ceiling (README 4.7, D119): computes how much light every point of the back
wall, the two side walls and the ceiling gets, bounces included, and writes it as one picture that the room's
materials read (Content side: /Game/Assets/Materials/Baked/T_LabLight, material M_LabBaked). A second picture
(T_LabLightDir) holds where the direct light comes from and its share of the light, so the material can shade the
surface relief (normal and occlusion maps) the way live lights would. The shadows of the room's own shape come
from Tools/bake_lab_shadow.py.

    python Tools/bake_lab_light.py                  computes Saved/LabBake/T_LabLight.exr and T_LabLightDir.exr (about 11 min)
    python Tools/bake_lab_shadow.py                 the room's own shadows (editor open)
    python Tools/ue_py.py Tools/bake_lab_import.py  brings them into the open editor (re-imports the textures)

Needs numpy and OpenCV (the laptop's Python). Nothing here runs on the wall PC: the result is a texture.

What is baked: the light of the sources listed in SOURCES below, which mirror the level's actors
`Light_Strip_1` .. `Light_Strip_9` (here as one luminous area over the ceiling, on purpose: smooth walls without a
bright patch under each strip), `Light_Fill` (soft light from the wall opening; both also light the floor and
Frank live) and `Light_CeilingFill` (lights only the ceiling; switched off in the level, it exists only in the
bake), plus the glowing tubes of the room model. After changing one of those lights in the level, change it here
too and bake again; the floor and Frank follow the level at once, the walls only after the bake.

How: the room is a box (the planes below). Direct light of a rectangular source on a point is exact (Lambert's
polygon formula). Bounces: the box's faces are cut into patches of 12.5 cm that exchange light until it settles
(radiosity; the opening towards the LED wall swallows light, the floor reflects what its material reflects).
Checked against the level before the bake (Lumen): the bounced share came out the same (walls about a third,
ceiling about two thirds).

Units are the engine's: a rect light of F lumens and area A m2 shines like a one-sided diffuse emitter of
radiance 2 F / (pi A) (RectLightComponent.cpp, RectLightSceneProxy.cpp); the picture stores E / pi for the
irradiance E, so an unlit material shows  albedo x picture  exactly as a lit one would show under that light.
"""
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "Saved", "LabBake")

# ---- the room, world space, cm (from the model /Game/Assets/MRLab as placed in DefaultMap) ----
X0, X1 = -638.0, 50.2      # front of the back wall's panels; the opening (LED wall side)
Y0, Y1 = -269.8, 269.8     # fronts of the side walls' panels
Z0, Z1 = 0.0, 318.7        # floor; underside of the ceiling tiles
WHITE_WALL_FROM = -38.3    # from this x on the side walls are plaster
BARE_CEILING_FROM = -37.8  # from this x on the ceiling has no tiles
ALBEDO = {"panel": 0.52, "white_wall": 0.57, "ceiling_tile": 0.535, "ceiling_bare": 0.816, "floor": 0.145}  # measured (base colour captures)

# ---- the light sources (keep in step with the level, see above) ----
KELVIN = 4000.0
SOURCES = [
    # label, centre, direction it shines in, its two edge directions, size along them (cm), lumens, attenuation radius (cm)
    ("Light_Strip_1..9 as one area", (-336.0, 0.0, 318.5), (0, 0, -1), (0, 1, 0), (1, 0, 0), (520.0, 540.0), 720.0, 2000.0),
    ("Light_CeilingFill", (-336.0, 0.0, 300.0), (0, 0, 1), (0, 1, 0), (-1, 0, 0), (520.0, 640.0), 40.0, 800.0),
    ("Light_Fill", (30.0, 0.0, 210.0), (-0.9788, -0.0290, -0.2028), (0.0297, -0.9996, 0.0), (-0.2027, -0.0060, 0.9792), (250.0, 150.0), 120.0, 500.0),
]
TUBES = [(-96.0 - 60.0 * i, (1.0, 0.817840, 0.365014)) for i in range(9)] + [(-94.8 - 60.0 * i, (0.769617, 1.0, 0.943518)) for i in range(9)]
TUBE_RADIANCE = 30.0       # the tubes' emissive strength (M_LightsWarm, M_LightsCold)

COARSE, GATHER, TEXEL = 12.5, 6.0, 2.0   # cm: bounce patches, grid the bounced light is gathered on, the picture
ATLAS = (1024, 512)
LUMA = np.array([0.2126, 0.7152, 0.0722])
SIDE_MAX = 1.9             # light direction picture: longest part along the surface (where light only grazes it)
MAPS = {  # name: (plane axis, axis of u, axis of v) -> picture region, filled in by layout()
    "back": ("x", "y", "z"), "left": ("y", "x", "z"), "right": ("y", "x", "z"), "ceiling": ("z", "x", "y")}
RANGE = {"x": (X0, X1), "y": (Y0, Y1), "z": (Z0, Z1)}


def temperature_color(kelvin):
    """Linear RGB of a colour temperature, luminance 1 (as FLinearColor::MakeFromColorTemperature)."""
    t = min(max(kelvin, 1000.0), 15000.0)
    u = (0.860117757 + 1.54118254e-4 * t + 1.28641212e-7 * t * t) / (1.0 + 8.42420235e-4 * t + 7.08145163e-7 * t * t)
    v = (0.317398726 + 4.22806245e-5 * t + 4.20481691e-8 * t * t) / (1.0 - 2.89741816e-5 * t + 1.61456053e-7 * t * t)
    x, y = 3.0 * u / (2.0 * u - 8.0 * v + 4.0), 2.0 * v / (2.0 * u - 8.0 * v + 4.0)
    X, Y, Z = x / y, 1.0, (1.0 - x - y) / y
    return np.array([3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z, -0.9692660 * X + 1.8760108 * Y + 0.0415560 * Z,
                     0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z])


def rect_vector(points, corners):
    """Vector irradiance per unit radiance of rectangles (corners (M, 4, 3)) at points (N, 3): (N, M, 3), pointing
    towards the rectangle. Irradiance on a surface with normal n that has the rectangle in front: n . vector."""
    rel = corners[None] - points[:, None, None]
    rel = rel / np.maximum(np.linalg.norm(rel, axis=3, keepdims=True), 1e-9)
    total = np.zeros(rel.shape[:2] + (3,), rel.dtype)
    for i in range(4):
        a, b = rel[:, :, i], rel[:, :, (i + 1) % 4]
        cross = np.cross(a, b)
        angle = np.arccos(np.clip(np.sum(a * b, axis=2, keepdims=True), -1.0, 1.0))
        total += angle * cross / np.maximum(np.linalg.norm(cross, axis=2, keepdims=True), 1e-12)
    total *= 0.5
    centre = corners.mean(axis=1)
    return total * np.sign(np.sum(total * (centre[None] - points[:, None]), axis=2, keepdims=True))


class Source:
    def __init__(self, centre, forward, right, up, size, radiance, radius=None):
        self.centre, self.forward = np.array(centre, float), np.array(forward, float)
        r, u = np.array(right, float) * size[0] / 2, np.array(up, float) * size[1] / 2
        self.corners = np.array([self.centre - r - u, self.centre + r - u, self.centre + r + u, self.centre - r + u])
        self.radiance, self.radius = np.array(radiance, float), radius

    def reach(self, part):
        """How much of the light gets to the points: only in front of the source, faded out towards the attenuation
        radius as the engine does."""
        k = (np.sum((part - self.centre) * self.forward, axis=1) > 0.0).astype(float)
        if self.radius:
            k *= np.clip(1.0 - (np.sum((part - self.centre) ** 2, axis=1) / self.radius ** 2) ** 2, 0.0, 1.0) ** 2
        return k

    def irradiance(self, points, normal):
        flat = points.reshape(-1, 3)
        out = np.zeros(flat.shape)
        for start in range(0, len(flat), 20000):
            part = flat[start:start + 20000]
            e = np.maximum(np.sum(rect_vector(part, self.corners[None])[:, 0] * np.asarray(normal, float), axis=1), 0.0) * self.reach(part)
            out[start:start + 20000] = e[:, None] * self.radiance
        return out.reshape(points.shape)

    def vector(self, points):
        """Vector irradiance (luminance), pointing towards the source: a surface of normal n facing it gets n . vector."""
        flat = points.reshape(-1, 3)
        out = np.zeros(flat.shape)
        for start in range(0, len(flat), 20000):
            part = flat[start:start + 20000]
            out[start:start + 20000] = rect_vector(part, self.corners[None])[:, 0] * (self.reach(part) * float(LUMA @ self.radiance))[:, None]
        return out.reshape(points.shape)


def sources():
    tint = temperature_color(KELVIN)
    out = [Source(c, f, r, u, size, 2.0 * lumens / (math.pi * size[0] * size[1] / 1e4) * tint, radius) for _, c, f, r, u, size, lumens, radius in SOURCES]
    out += [Source((x, 0.0, 319.2), (0, 0, -1), (0, 1, 0), (1, 0, 0), (520.0, 1.0), TUBE_RADIANCE * np.array(color)) for x, color in TUBES]
    return out


# surface: origin, axis u, axis v, normal into the room, length u, length v
FACES = {
    "floor":   (np.array([X0, Y0, Z0]), np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0]), X1 - X0, Y1 - Y0),
    "ceiling": (np.array([X0, Y0, Z1]), np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, -1.0]), X1 - X0, Y1 - Y0),
    "back":    (np.array([X0, Y0, Z0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0]), np.array([1.0, 0, 0]), Y1 - Y0, Z1 - Z0),
    "front":   (np.array([X1, Y0, Z0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0]), np.array([-1.0, 0, 0]), Y1 - Y0, Z1 - Z0),
    "left":    (np.array([X0, Y1, Z0]), np.array([1.0, 0, 0]), np.array([0, 0, 1.0]), np.array([0, -1.0, 0]), X1 - X0, Z1 - Z0),
    "right":   (np.array([X0, Y0, Z0]), np.array([1.0, 0, 0]), np.array([0, 0, 1.0]), np.array([0, 1.0, 0]), X1 - X0, Z1 - Z0),
}


def albedo_of(face, points):
    x = points[..., 0]
    if face in ("left", "right"):
        return np.where(x > WHITE_WALL_FROM, ALBEDO["white_wall"], ALBEDO["panel"])
    if face == "ceiling":
        return np.where(x > BARE_CEILING_FROM, ALBEDO["ceiling_bare"], ALBEDO["ceiling_tile"])
    return np.full(x.shape, {"back": ALBEDO["panel"], "floor": ALBEDO["floor"]}.get(face, 0.0))   # the opening reflects nothing


def grid(face, step):
    origin, au, av, normal, lu, lv = FACES[face]
    nu, nv = max(1, int(round(lu / step))), max(1, int(round(lv / step)))
    du, dv = lu / nu, lv / nv
    points = origin + ((np.arange(nu) + 0.5) * du)[:, None, None] * au + ((np.arange(nv) + 0.5) * dv)[None, :, None] * av
    return points, du, dv


def solve(lights, log):
    """Radiosity on the coarse patches: per patch its place, corners, face, albedo and total irradiance."""
    names = list(FACES)
    centres, normals, corners, rho, owner, direct = [], [], [], [], [], []
    for k, name in enumerate(names):
        origin, au, av, normal, lu, lv = FACES[name]
        p, du, dv = grid(name, COARSE)
        flat = p.reshape(-1, 3)
        hu, hv = 0.5 * du * au, 0.5 * dv * av
        centres.append(flat)
        normals.append(np.tile(normal, (len(flat), 1)))
        corners.append(np.stack([flat - hu - hv, flat + hu - hv, flat + hu + hv, flat - hu + hv], axis=1))
        rho.append(albedo_of(name, flat))
        owner.append(np.full(len(flat), k))
        direct.append(sum(s.irradiance(flat, normal) for s in lights) if name != "front" else np.zeros(flat.shape))
    centres, normals, corners = np.concatenate(centres), np.concatenate(normals), np.concatenate(corners)
    rho, owner, direct = np.concatenate(rho), np.concatenate(owner), np.concatenate(direct)
    n = len(centres)
    form = np.zeros((n, n), np.float32)
    c32, p32, n32 = corners.astype(np.float32), centres.astype(np.float32), normals.astype(np.float32)
    for start in range(0, n, 256):
        f = np.maximum(np.sum(rect_vector(p32[start:start + 256], c32) * n32[start:start + 256, None], axis=2), 0.0) / math.pi
        f[owner[start:start + 256, None] == owner[None]] = 0.0
        form[start:start + 256] = f
    e = direct.copy()
    for bounce in range(80):
        new = direct + form @ (rho[:, None] * e)
        change = float(np.abs(new - e).max() / max(e.max(), 1e-9))
        e = new
        if change < 1e-5:
            break
    log(f"{n} patches, {bounce + 1} bounces")
    return {"names": names, "corners": corners, "owner": owner, "radiance": rho[:, None] * e / math.pi, "direct": direct, "total": e}


def bounced(solution, points, normal, face):
    """Irradiance at points from the light the other faces' patches send out."""
    use = solution["owner"] != solution["names"].index(face)
    c32, rad = solution["corners"][use].astype(np.float32), solution["radiance"][use].astype(np.float32)
    flat = points.reshape(-1, 3).astype(np.float32)
    out = np.zeros(flat.shape, np.float32)
    for start in range(0, len(flat), 192):
        out[start:start + 192] = np.maximum(np.sum(rect_vector(flat[start:start + 192], c32) * np.asarray(normal, np.float32), axis=2), 0.0) @ rad
    return out.reshape(points.shape).astype(np.float64)


def upsample(coarse, shape):
    """Bilinear resize of (nu, nv, 3) to shape (nu2, nv2), sample centres aligned, edges held."""
    def axis(n_from, n_to):
        pos = (np.arange(n_to) + 0.5) * n_from / n_to - 0.5
        lo = np.clip(np.floor(pos).astype(int), 0, n_from - 1)
        hi = np.clip(lo + 1, 0, n_from - 1)
        return lo, hi, np.clip(pos - lo, 0.0, 1.0)
    lo, hi, t = axis(coarse.shape[0], shape[0])
    rows = coarse[lo] * (1 - t)[:, None, None] + coarse[hi] * t[:, None, None]
    lo, hi, t = axis(coarse.shape[1], shape[1])
    return rows[:, lo] * (1 - t)[None, :, None] + rows[:, hi] * t[None, :, None]


def layout():
    """Where each map sits in the picture: {name: (x, y, width, height)} in pixels, 2 pixels of margin around each."""
    size = {name: (int(round((RANGE[u][1] - RANGE[u][0]) / TEXEL)), int(round((RANGE[v][1] - RANGE[v][0]) / TEXEL))) for name, (_, u, v) in MAPS.items()}
    place, x, y, row = {}, 4, 4, 0
    for name in ("back", "left", "right", "ceiling"):
        w, h = size[name]
        if x + w + 4 > ATLAS[0]:
            x, y, row = 4, y + row + 8, 0
        place[name] = (x, y, w, h)
        x, row = x + w + 8, max(row, h)
    assert y + row + 4 <= ATLAS[1], "the picture is too small"
    return place


def main():
    try:
        os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
        import cv2
    except ImportError:
        sys.exit("OpenCV (cv2) is needed to write the picture: pip install opencv-python")
    begin = time.perf_counter()
    lights = sources()
    solution = solve(lights, print)
    place = layout()
    atlas = np.zeros((ATLAS[1], ATLAS[0], 3))
    atlas_dir = np.full((ATLAS[1], ATLAS[0], 4), 0.5)
    atlas_dir[..., 3] = 0.0

    def put(picture, tile, x, y, w, h):
        picture[y:y + h, x:x + w] = tile
        picture[y - 2:y, x:x + w], picture[y + h:y + h + 2, x:x + w] = tile[:1], tile[-1:]
        picture[y - 2:y + h + 2, x - 2:x] = picture[y - 2:y + h + 2, x:x + 1]
        picture[y - 2:y + h + 2, x + w:x + w + 2] = picture[y - 2:y + h + 2, x + w - 1:x + w]

    report = {}
    for name, (x, y, w, h) in place.items():
        origin, au, av, normal, lu, lv = FACES[name]
        fine, _, _ = grid(name, TEXEL)
        assert fine.shape[:2] == (w, h), (name, fine.shape, w, h)
        direct = sum(s.irradiance(fine, normal) for s in lights)
        coarse, _, _ = grid(name, GATHER)
        total = direct + upsample(bounced(solution, coarse, normal, name), (w, h))
        put(atlas, np.transpose(total / math.pi, (1, 0, 2)), x, y, w, h)        # rows = v, columns = u
        # where the direct light comes from, scaled so that d . normal = 1: a bumped normal n gets direct x (n . d)
        vec = sum(s.vector(fine) for s in lights)
        lit = np.sum(vec * normal, axis=2)
        d = np.where(lit[..., None] > 1e-6, vec / np.maximum(lit, 1e-6)[..., None], normal)
        side = d - np.sum(d * normal, axis=2, keepdims=True) * normal
        d = normal + side * np.minimum(1.0, SIDE_MAX / np.maximum(np.linalg.norm(side, axis=2, keepdims=True), 1e-9))
        share = np.clip((direct @ LUMA) / np.maximum(total @ LUMA, 1e-9), 0.0, 1.0)   # direct part of the light
        put(atlas_dir, np.transpose(np.concatenate([d * 0.25 + 0.5, share[..., None]], axis=2), (1, 0, 2)), x, y, w, h)
        report[name] = {"direct": float(direct[..., 0].mean()), "total": float(total[..., 0].mean()), "max": float(total[..., 0].max())}
        print(f"  {name:8s} {w} x {h}: irradiance (red) direct {report[name]['direct']:6.2f}, with bounces {report[name]['total']:6.2f} "
              f"({100 * (1 - report[name]['direct'] / report[name]['total']):.0f} % bounced), brightest {report[name]['max']:6.2f}")
    os.makedirs(OUT, exist_ok=True)
    cv2.imwrite(os.path.join(OUT, "T_LabLight.exr"), atlas[:, :, ::-1].astype(np.float32))
    cv2.imwrite(os.path.join(OUT, "T_LabLightDir.exr"), atlas_dir[:, :, [2, 1, 0, 3]].astype(np.float32))
    names = solution["names"]
    floor = solution["owner"] == names.index("floor")
    info = {"atlas": list(ATLAS), "texel_cm": TEXEL, "regions": place, "room": {"x": [X0, X1], "y": [Y0, Y1], "z": [Z0, Z1]},
            "surfaces": report, "floor": {"direct": float(solution["direct"][floor, 0].mean()), "total": float(solution["total"][floor, 0].mean())},
            "sources": [[s[0], s[6]] for s in SOURCES], "kelvin": KELVIN}
    json.dump(info, open(os.path.join(OUT, "T_LabLight.json"), "w"), indent=1)
    print(f"floor (not baked, for comparison): direct {info['floor']['direct']:.2f}, with bounces {info['floor']['total']:.2f}")
    print(f"wrote {os.path.join(OUT, 'T_LabLight.exr')} in {time.perf_counter() - begin:.0f} s")


if __name__ == "__main__":
    main()
