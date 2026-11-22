r"""Shadows of the room's own shape for the baked walls and ceiling (README 4.7, D119). The light bake
(bake_lab_light.py) treats the room as a flat box; the real panels stand 6 cm in front of a recessed strip at the
floor and at the ceiling, and meet in small V-shaped joints. Under live lights those parts lie in shadow. This
computes, from the room model's actual shape, how much of the light reaches each point of them, and writes it as
a third picture that M_LabBaked multiplies in (Content side: /Game/Assets/Materials/Baked/T_LabShadow).

    python Tools/bake_lab_shadow.py                 needs the editor open with DefaultMap (reads the room model);
                                                    writes Saved/LabBake/T_LabShadow.png (about a minute)
    python Tools/ue_py.py Tools/bake_lab_import.py  brings it into the editor with the other two pictures

Red: share of the direct light that reaches the point (the light sources of bake_lab_light.py, from where they
are). Green: share of the bounced light (light from all around, weighted as a matte surface takes it in).

How: each wall and the ceiling is a height field over its plane (the model's faces that look into the room,
rasterised on a 2.5 mm grid). For every point that has something higher around it, the horizon is found in 32
directions along the surface; light arriving from below the horizon is blocked. The slot between the ceiling tiles
and the top of the wall panels is not a height field (the tiles overhang it): its walls and ceiling get light only
through the gap between panel top and tile edge, worked out on its cross-section (it runs the length of each wall).
Each map reaches EXT beyond the room box, so that slot's ceiling is covered too. The directions the direct light
comes from are gathered per 8 cm cell from samples over every source. The walls' result is averaged to 5 mm
along them (2.5 mm up), the ceiling's stays at 2.5 mm.
"""
import json
import math
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bake_lab_light as bake  # noqa: E402  (room box, faces and light sources)

RES = 0.25           # cm, grid the shadows are computed on
TEXEL = {"back": (0.5, 0.25), "left": (0.5, 0.25), "right": (0.5, 0.25), "ceiling": (0.25, 0.25)}
# cm per pixel of the picture (along, up): the walls' joints and recesses run along them, the ceiling's both ways
AZIMUTHS = 32        # directions along the surface the horizon is searched in
STEPS = np.array([0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0, 14.0,
                  17.0, 20.0, 25.0, 30.0, 40.0, 50.0])   # cm, distances the horizon is sampled at
CELL = 8.0           # cm, cells the direct light's directions are gathered on
ELEVATIONS = 45      # bins of the angle above the surface (0..90 deg)
SAMPLE = 8.0         # cm, spacing of the sample points on the light sources
SLAB = 15.0          # cm, model faces this close to a plane belong to its height field
EXT = 8.0            # cm, each map reaches this far beyond the room box
ATLAS = (4096, 4096)
MARGIN, GAP = 8, 16  # pixels repeated around each map, space between maps (keeps the mipmaps apart)
MESH = os.path.join(bake.OUT, "shell_mesh.npz")
# the slot above the wall panels (from the room model): panels 6 cm in front of the wall behind them, panel tops at
# PANEL_TOP, ceiling tiles' faces at the room box's top, the slot's own ceiling at SLOT_TOP
PANEL_TOP, SLOT_TOP, RECESS = 314.5, 319.7, 6.0
SLOTS = {  # wall: point on the wall behind the panels, direction into the room, along the wall, along range (cm), tile edge
    "left": ((0.0, bake.Y1 + RECESS, 0.0), (0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (bake.X0 - RECESS, bake.WHITE_WALL_FROM), 268.1),
    "right": ((0.0, bake.Y0 - RECESS, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (bake.X0 - RECESS, bake.WHITE_WALL_FROM), -268.1),
    "back": ((bake.X0 - RECESS, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (bake.Y0 - RECESS, bake.Y1 + RECESS), -634.0),
}

EXPORT = r'''
import unreal, numpy as np
actor = next(a for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors() if a.get_actor_label() == "MRLab")
comp = actor.static_mesh_component
mesh = comp.static_mesh
xf = comp.get_world_transform()
P, N, T, base = [], [], [], 0
for i in range(mesh.get_num_sections(0)):
    v, tri, nrm, uv, tan = unreal.ProceduralMeshLibrary.get_section_from_static_mesh(mesh, 0, i)
    for p in v:
        q = unreal.MathLibrary.transform_location(xf, p)
        P.append((q.x, q.y, q.z))
    for n in nrm:
        q = unreal.MathLibrary.transform_direction(xf, n)
        N.append((q.x, q.y, q.z))
    T.extend(base + int(k) for k in tri)
    base += len(v)
np.savez(r"%s", points=np.array(P), normals=np.array(N), triangles=np.array(T).reshape(-1, 3))
print("exported", mesh.get_path_name(), len(P), "points", len(T) // 3, "triangles")
'''


def export_mesh():
    """The room model (the MRLab actor's mesh, as placed) in world space, from the open editor."""
    os.makedirs(bake.OUT, exist_ok=True)
    subprocess.run([sys.executable, os.path.join(HERE, "ue_py.py"), "-c", EXPORT % MESH], check=True)
    data = np.load(MESH)
    return data["points"], data["normals"], data["triangles"]


def frame(name):
    """A map's plane, reaching EXT beyond the room box: origin, axes u and v, normal, size in grid points."""
    origin, au, av, normal, lu, lv = bake.FACES[name]
    return origin - EXT * (au + av), au, av, normal, int(round((lu + 2 * EXT) / RES)), int(round((lv + 2 * EXT) / RES))


def height_field(name, points, normals, triangles):
    """Height above the plane (cm, into the room) of the model's front-most face, per grid point (rows = v)."""
    origin, au, av, normal, w, h = frame(name)
    rel = points - origin
    uvh = np.stack([rel @ au / RES - 0.5, rel @ av / RES - 0.5, rel @ normal], axis=1)
    tri = uvh[triangles]
    facing = normals[triangles].mean(axis=1) @ normal > 0.3
    near = np.all(np.abs(tri[:, :, 2]) < SLAB, axis=1)
    inside = (tri[:, :, 0].max(1) > -1) & (tri[:, :, 0].min(1) < w) & (tri[:, :, 1].max(1) > -1) & (tri[:, :, 1].min(1) < h)
    field = np.full((h, w), -1e9)
    for a, b, c in tri[facing & near & inside]:
        area = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
        if abs(area) < 1e-9:
            continue
        x0, x1 = max(int(np.floor(min(a[0], b[0], c[0]))), 0), min(int(np.ceil(max(a[0], b[0], c[0]))), w - 1)
        y0, y1 = max(int(np.floor(min(a[1], b[1], c[1]))), 0), min(int(np.ceil(max(a[1], b[1], c[1]))), h - 1)
        if x1 < x0 or y1 < y0:
            continue
        X, Y = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        w0 = ((b[0] - X) * (c[1] - Y) - (c[0] - X) * (b[1] - Y)) / area
        w1 = ((c[0] - X) * (a[1] - Y) - (a[0] - X) * (c[1] - Y)) / area
        w2 = 1.0 - w0 - w1
        m = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        if m.any():
            z = w0 * a[2] + w1 * b[2] + w2 * c[2]
            sub = field[y0:y1 + 1, x0:x1 + 1]
            sub[m] = np.maximum(sub[m], z[m])
    return field


def horizons(field, rows, cols):
    """Tangent of the horizon's angle above the surface at the given grid points, per azimuth: (AZIMUTHS, n)."""
    h, w = field.shape
    base = field[rows, cols]
    out = np.zeros((AZIMUTHS, len(rows)), np.float32)
    for k in range(AZIMUTHS):
        phi = -math.pi + (k + 0.5) * 2.0 * math.pi / AZIMUTHS
        best = np.zeros(len(rows), np.float32)
        for t in STEPS:
            r = rows + int(round(t * math.sin(phi) / RES))
            c = cols + int(round(t * math.cos(phi) / RES))
            ok = (r >= 0) & (r < h) & (c >= 0) & (c < w)
            rise = np.where(ok, field[np.clip(r, 0, h - 1), np.clip(c, 0, w - 1)] - base, -1e9)
            np.maximum(best, rise / t, out=best)
        out[k] = best
    return out


def source_samples(lights):
    """Points spread over every light source: positions, luminous weight, direction the source faces, which source."""
    samples, weights, forwards, owners = [], [], [], []
    for j, s in enumerate(lights):
        c0, c1, c3 = s.corners[0], s.corners[1], s.corners[3]
        na, nb = max(1, int(math.ceil(np.linalg.norm(c1 - c0) / SAMPLE))), max(1, int(math.ceil(np.linalg.norm(c3 - c0) / SAMPLE)))
        a, b = np.meshgrid((np.arange(na) + 0.5) / na, (np.arange(nb) + 0.5) / nb)
        q = c0 + a.reshape(-1, 1) * (c1 - c0) + b.reshape(-1, 1) * (c3 - c0)
        area = np.linalg.norm(c1 - c0) * np.linalg.norm(c3 - c0) / (na * nb)
        samples.append(q)
        weights.append(np.full(len(q), area * float(bake.LUMA @ s.radiance)))
        forwards.append(np.tile(s.forward, (len(q), 1)))
        owners.append(np.full(len(q), j))
    return np.concatenate(samples), np.concatenate(weights), np.concatenate(forwards), np.concatenate(owners)


def arriving(points, normal, lights, samples):
    """Direct light (luminance) from each source sample at points with the given normal, unblocked, and the unit
    directions it comes from: (n, samples), (n, samples, 3)."""
    q, wq, fq, oq = samples
    reach = np.stack([s.reach(points) for s in lights], axis=1)
    d = q[None] - points[:, None]
    r2 = np.sum(d * d, axis=2)
    d /= np.sqrt(r2)[..., None]
    cos_src = -np.sum(d * fq[None], axis=2)
    return wq[None] * np.maximum(cos_src, 0.0) * np.maximum(d @ normal, 0.0) / r2 * reach[:, oq], d


def direction_tables(name, lights, samples):
    """Per cell of the plane: direct light (luminance) arriving per azimuth and elevation bin, unblocked:
    (cells v, cells u, AZIMUTHS, ELEVATIONS)."""
    origin, au, av, normal, w, h = frame(name)
    nu, nv = int(math.ceil(w * RES / CELL)), int(math.ceil(h * RES / CELL))
    centres = origin + ((np.arange(nu) + 0.5) * CELL)[None, :, None] * au + ((np.arange(nv) + 0.5) * CELL)[:, None, None] * av
    centres = centres.reshape(-1, 3)
    table = np.zeros((len(centres), AZIMUTHS * ELEVATIONS))
    for start in range(0, len(centres), 64):
        p = centres[start:start + 64]
        wgt, d = arriving(p, normal, lights, samples)
        cn, cu, cv = d @ normal, d @ au, d @ av
        az = np.floor((np.arctan2(cv, cu) + math.pi) / (2 * math.pi) * AZIMUTHS).astype(int) % AZIMUTHS
        el = np.minimum((np.arctan2(np.maximum(cn, 0.0), np.hypot(cu, cv)) / (0.5 * math.pi) * ELEVATIONS).astype(int), ELEVATIONS - 1)
        idx = (np.arange(len(p))[:, None] * (AZIMUTHS * ELEVATIONS) + az * ELEVATIONS + el).ravel()
        table[start:start + 64] = np.bincount(idx, weights=wgt.ravel(), minlength=len(p) * AZIMUTHS * ELEVATIONS).reshape(len(p), -1)
    return table.reshape(nv, nu, AZIMUTHS, ELEVATIONS), centres.reshape(nv, nu, 3)


def shadow_map(name, field, holes, lights, samples, log):
    """(rows, cols, 2): visible share of the direct light, of the bounced light."""
    h, w = field.shape
    out = np.ones((h, w, 2), np.float32)
    import cv2
    # only points with something higher around them can be shadowed: anything higher close by, or at least 1 cm
    # higher further away (a rivet 20 cm off lifts the horizon by under 2 degrees)
    def around(radius_cm):
        px = int(radius_cm / RES)
        return cv2.dilate(field.astype(np.float32), np.ones((2 * px + 1, 2 * px + 1), np.uint8))
    rows, cols = np.nonzero((around(5.0) > field + 0.02) | (around(STEPS[-1]) > field + 1.0))
    tan_h = np.maximum(horizons(field, rows, cols), 0.0)          # (AZIMUTHS, n); below the plane does not count
    elev = np.arctan(tan_h)
    out[rows, cols, 1] = np.mean(np.cos(elev) ** 2, axis=0)      # matte surface, light from all around
    table, _ = direction_tables(name, lights, samples)
    nv, nu = table.shape[:2]
    above = np.concatenate([np.cumsum(table[..., ::-1], axis=3)[..., ::-1], np.zeros((nv, nu, AZIMUTHS, 1))], axis=3)
    cv_ = np.minimum((rows * RES / CELL).astype(int), nv - 1)
    cu_ = np.minimum((cols * RES / CELL).astype(int), nu - 1)
    pos = elev / (0.5 * math.pi) * ELEVATIONS
    k0 = np.minimum(pos.astype(int), ELEVATIONS - 1)
    frac = pos - k0
    seen = np.zeros(len(rows))
    for a in range(AZIMUTHS):
        seen += above[cv_, cu_, a, k0[a]] - frac[a] * table[cv_, cu_, a, k0[a]]
    total = above[cv_, cu_, :, 0].sum(axis=1)
    out[rows, cols, 0] = np.where(total > 1e-9, seen / np.maximum(total, 1e-9), 1.0)
    out[holes] = 1.0                              # no model there (beyond its edges): nothing to shade
    slots(name, field, out, lights, samples)
    log(f"  {name:8s} {w} x {h} points, {len(rows)} can be shadowed: direct light {100 * out[..., 0].mean():.1f} %, "
        f"bounced {100 * out[..., 1].mean():.1f} % on average, darkest {100 * out[..., 0].min():.0f} % / {100 * out[..., 1].min():.0f} %")
    return out


def through_gap(ps, pz, ws, wz, gap_far):
    """Whether directions (cross-section parts ws into the room, wz up) from slot points (ps cm from the wall behind
    the panels, pz high) leave the slot through the gap between the panel top's front edge and the tile edge
    (gap_far cm from that wall)."""
    a_s, a_z, b_s, b_z = RECESS - ps, PANEL_TOP - pz, gap_far - ps, bake.Z1 - pz
    return (ws > 0.0) & (a_s * wz - a_z * ws >= 0.0) & (ws * b_z - wz * b_s >= 0.0)


def slot_light(points, normal, s_pos, z_pos, s_dir, gap_far, lights, samples, sphere):
    """Visible share of the direct light at slot points (n,), and of light from all around (n,)."""
    direct = np.ones(len(points))
    for start in range(0, len(points), 64):
        wgt, d = arriving(points[start:start + 64], normal, lights, samples)
        ok = through_gap(s_pos[start:start + 64, None], z_pos[start:start + 64, None], d @ s_dir, d[..., 2], gap_far)
        total = wgt.sum(axis=1)
        direct[start:start + 64] = np.where(total > 1e-9, (wgt * ok).sum(axis=1) / np.maximum(total, 1e-9), 1.0)
    cos = np.maximum(sphere @ normal, 0.0)
    ok = through_gap(s_pos[:, None], z_pos[:, None], (sphere @ s_dir)[None], sphere[None, :, 2], gap_far)
    return direct, (ok * cos[None]).sum(axis=1) / cos.sum()


def slots(name, field, out, lights, samples):
    """Writes the slot above the wall panels into a map: on a wall, the wall behind the panels above their tops; on
    the ceiling, the strip of the slot's own ceiling beyond the tile edges."""
    origin, au, av, normal, w, h = frame(name)
    n = 4096                                      # directions all around (Fibonacci sphere)
    k = np.arange(n) + 0.5
    phi, cz = np.pi * (1 + 5 ** 0.5) * k, 1 - 2 * k / n
    sphere = np.stack([np.sqrt(1 - cz ** 2) * np.cos(phi), np.sqrt(1 - cz ** 2) * np.sin(phi), cz], axis=1)
    up = np.array([0.0, 0.0, 1.0])
    u = (np.arange(w) + 0.5) * RES
    v = (np.arange(h) + 0.5) * RES
    for side, (base, s_dir, along, (a0, a1), tile_edge) in SLOTS.items():
        base, s_dir, along = np.array(base), np.array(s_dir), np.array(along)
        gap_far = abs(tile_edge - base @ np.abs(s_dir))           # tile edge, cm into the room from the wall behind
        cells = np.arange(a0 + 0.5 * CELL, a1, CELL)
        if name == side:                                          # the wall behind the panels, above them
            zs = np.arange(PANEL_TOP + 0.5 * RES, SLOT_TOP, RES)
            pts = (base[None, None] + cells[:, None, None] * along + zs[None, :, None] * up).reshape(-1, 3)
            direct, _ = slot_light(pts, s_dir, np.zeros(len(pts)), np.tile(zs, len(cells)), s_dir, gap_far, lights, samples, sphere)
            _, around_ = slot_light(base[None] + zs[:, None] * up, s_dir, np.zeros(len(zs)), zs, s_dir, gap_far, lights, samples, sphere)
            direct = direct.reshape(len(cells), len(zs))
            pos_along = origin @ along + u
            for r in np.nonzero(origin[2] + v > PANEL_TOP)[0]:
                cols = np.nonzero((field[r] < -0.5 * RECESS) & (pos_along >= a0) & (pos_along <= a1))[0]
                zi = min(int((origin[2] + v[r] - PANEL_TOP) / RES), len(zs) - 1)
                ci = np.clip(((pos_along[cols] - a0) / CELL).astype(int), 0, len(cells) - 1)
                out[r, cols, 0] = direct[ci, zi]
                out[r, cols, 1] = around_[zi]
        elif name == "ceiling":                                   # the slot's ceiling beyond the tile edge
            ss = np.arange(0.5 * RES, gap_far, RES)
            down = -up
            pts = (base[None, None] + cells[:, None, None] * along + ss[None, :, None] * s_dir + SLOT_TOP * up).reshape(-1, 3)
            direct, _ = slot_light(pts, down, np.tile(ss, len(cells)), np.full(len(pts), SLOT_TOP), s_dir, gap_far, lights, samples, sphere)
            _, around_ = slot_light(base[None] + ss[:, None] * s_dir + SLOT_TOP * up, down, ss, np.full(len(ss), SLOT_TOP),
                                    s_dir, gap_far, lights, samples, sphere)
            direct = direct.reshape(len(cells), len(ss))
            grid = origin[None, None] + u[None, :, None] * au + v[:, None, None] * av      # (h, w, 3)
            s_of = (grid - base) @ s_dir
            a_of = grid @ along
            r, c = np.nonzero((s_of >= 0) & (s_of < gap_far) & (a_of >= a0) & (a_of <= a1))
            si = np.clip((s_of[r, c] / RES).astype(int), 0, len(ss) - 1)
            ci = np.clip(((a_of[r, c] - a0) / CELL).astype(int), 0, len(cells) - 1)
            out[r, c, 0] = np.minimum(out[r, c, 0], direct[ci, si])
            out[r, c, 1] = np.minimum(out[r, c, 1], around_[si])


def layout():
    """{name: (x, y, width, height)} of each map in the picture, in pixels."""
    size = {name: (int(round((bake.FACES[name][4] + 2 * EXT) / TEXEL[name][0])), int(round((bake.FACES[name][5] + 2 * EXT) / TEXEL[name][1])))
            for name in TEXEL}
    place, x, y, row = {}, GAP, GAP, 0
    for name in ("back", "left", "right", "ceiling"):
        w, h = size[name]
        if x + w + GAP > ATLAS[0]:
            x, y, row = GAP, y + row + GAP, 0
        place[name] = (x, y, w, h)
        x, row = x + w + GAP, max(row, h)
    assert y + row + GAP <= ATLAS[1], "the picture is too small"
    return place


def main():
    import cv2
    begin = time.perf_counter()
    points, normals, triangles = export_mesh()
    lights = bake.sources()
    samples = source_samples(lights)
    place = layout()
    atlas = np.ones((ATLAS[1], ATLAS[0], 2), np.float32)
    report = {}
    for name, (x, y, w, h) in place.items():
        field = height_field(name, points, normals, triangles)
        holes = field < -1e8
        field[holes] = field[~holes].min()                      # holes in the model: as deep as its deepest part
        fine = shadow_map(name, field, holes, lights, samples, print)
        tile = cv2.resize(fine, (w, h), interpolation=cv2.INTER_AREA)
        padded = cv2.copyMakeBorder(tile, MARGIN, MARGIN, MARGIN, MARGIN, cv2.BORDER_REPLICATE)
        atlas[y - MARGIN:y + h + MARGIN, x - MARGIN:x + w + MARGIN] = padded
        report[name] = {"direct": float(tile[..., 0].mean()), "bounced": float(tile[..., 1].mean())}
    picture = np.zeros((ATLAS[1], ATLAS[0], 3), np.uint8)
    picture[..., 2] = np.round(np.clip(atlas[..., 0], 0, 1) * 255)    # OpenCV writes BGR: red = direct
    picture[..., 1] = np.round(np.clip(atlas[..., 1], 0, 1) * 255)
    cv2.imwrite(os.path.join(bake.OUT, "T_LabShadow.png"), picture)
    json.dump({"atlas": list(ATLAS), "texel_cm": TEXEL, "ext_cm": EXT, "regions": place, "maps": report},
              open(os.path.join(bake.OUT, "T_LabShadow.json"), "w"), indent=1)
    print(f"wrote {os.path.join(bake.OUT, 'T_LabShadow.png')} in {time.perf_counter() - begin:.0f} s")


if __name__ == "__main__":
    main()
