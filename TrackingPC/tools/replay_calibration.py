r"""Calibration from a board recording (record_cameras.py board), as the hub computes it, and how good it is.
    runtime\python\python.exe tools\replay_calibration.py recordings\<run folder> [--save calibration.json]
        [--distance cm] [--half even|odd] [--calibration-module file]

Every 0.1 s each camera's board corners at that moment (calibration.board_at, as the hub; cached in
board_corners.json.gz next to the recording); the board on the floor from the run's "floor" phase (older
recordings: their last second). Every 4th moment with two or more cameras is held out of the solve and used to
check it:
- lines of sight: how far apart two cameras' lines of sight to the same board corner pass (mm, median); what
  the tracker's triangulation meets;
- transfer: the board placed from the other cameras, how far its corners land from where a camera saw them (px);
- board square size from the cameras (cm; the board's is 6.5);
plus the solve's report (score, per camera) and the tape checks. --save writes the cameras for
replay_tracking.py / live_test.py; --half even/odd solves from half of the moments (two independent
calibrations, for test_person.py).
"""
import argparse
import gzip
import importlib.util
import json
import multiprocessing
import pathlib
import sys
import time
import zipfile

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import replay  # noqa: E402

STEP = 0.1
ARCHIVES = {}


def corners_at(job):
    from hub import calibration
    path, moment = job
    if path not in ARCHIVES:
        archive = zipfile.ZipFile(path)
        info = json.loads(archive.read("info.json"))
        ARCHIVES[path] = (archive, np.array(info["camera_time"]), sorted(n for n in archive.namelist() if n.endswith(".jpg")))
    archive, times, names = ARCHIVES[path]
    i = int(np.searchsorted(times, moment))
    history = [(times[k], archive.read(names[k])) for k in (i - 1, i) if 0 <= k < len(names)]
    found = calibration.board_at(history, moment)
    return None if found is None else found.tolist()


def find_boards(recording):
    """{"walk": [{number: corners}], "floor": [...]} from the recording (cached next to it)."""
    cache = recording["folder"] / "board_corners.json.gz"
    if cache.exists():
        data = json.loads(gzip.open(cache, "rt").read())
    else:
        infos, numbers = recording["infos"], recording["numbers"]
        first = max(i["camera_time"][0] for i in infos.values()) + 0.05
        last = min(i["camera_time"][-1] for i in infos.values()) - 0.05
        floor_phase = next((p for p in (recording["run"] or {}).get("phases", []) if p[0] == "floor"), None)
        floor_from = max(first, floor_phase[3] - 5.0) if floor_phase else last - 1.0
        walk_end = floor_phase[2] if floor_phase else last - 1.0
        moments = {"walk": list(np.arange(first, walk_end, STEP)), "floor": list(np.arange(floor_from, last, STEP))}
        addresses = sorted(infos)
        jobs = [(str(recording["zips"][a]), m) for kind in ("walk", "floor") for m in moments[kind] for a in addresses]
        begin = time.perf_counter()
        with multiprocessing.Pool(max(1, multiprocessing.cpu_count() - 2)) as pool:
            found = iter(pool.map(corners_at, jobs, chunksize=8))
        print(f"board search: {len(jobs)} camera moments in {time.perf_counter() - begin:.0f} s")
        data = {}
        for kind in ("walk", "floor"):
            shots = []
            for _ in moments[kind]:
                shot = {str(numbers[a]): c for a in addresses if (c := next(found)) is not None}
                if shot:
                    shots.append(shot)
            data[kind] = shots
        with gzip.open(cache, "wt") as out:
            json.dump(data, out)
    return {kind: [{int(n): np.array(c) for n, c in shot.items()} for shot in shots] for kind, shots in data.items()}


def rays(calibration, result, devices, lenses, shot):
    out = {}
    for n, corners in shot.items():
        cam = result.get(devices[n])
        if cam is None:
            continue
        xy = calibration.normalize(corners, dict(lenses[n], matrix=cam["matrix"]))
        d = np.column_stack([xy, np.ones(len(xy))]) @ np.array(cam["rotation"]).T
        out[n] = (np.array(cam["position"]), d / np.linalg.norm(d, axis=1, keepdims=True))
    return out


def gap(o1, d1, o2, d2):
    w = o1 - o2
    k = np.sum(d1 * d2, 1)
    d, e = d1 @ w, d2 @ w
    s, t = (k * e - d) / (1 - k * k), (e - k * d) / (1 - k * k)
    return np.linalg.norm((o1 + s[:, None] * d1) - (o2 + t[:, None] * d2), axis=1)


def triangulate(lines):
    a, b = 0.0, 0.0
    for o, d in lines:
        p = np.eye(3)[None] - d[:, :, None] * d[:, None, :]
        a, b = a + p, b + p @ o
    return np.linalg.solve(a, b[..., None])[..., 0]


def check(calibration, result, devices, lenses, test):
    gaps, sizes, transfer = [], [], []
    for shot in test:
        r = rays(calibration, result, devices, lenses, shot)
        numbers = sorted(r)
        for i, a in enumerate(numbers):
            for b in numbers[i + 1:]:
                gaps.append(np.median(gap(*r[a], *r[b])))
        if len(numbers) >= 2:
            p = triangulate([r[n] for n in numbers]).reshape(calibration.BOARD[1], calibration.BOARD[0], 3)
            sizes.append(np.mean([np.linalg.norm(np.diff(p, axis=1), axis=2).mean(), np.linalg.norm(np.diff(p, axis=0), axis=2).mean()]))
        if len(numbers) >= 3:
            for n in numbers:
                p = triangulate([r[k] for k in numbers if k != n])
                cam = result[devices[n]]
                local = (p - np.array(cam["position"])) @ np.array(cam["rotation"])
                seen = calibration.normalize(shot[n], dict(lenses[n], matrix=cam["matrix"]))
                transfer.append(np.sqrt(np.mean(np.sum((local[:, :2] / local[:, 2:3] - seen) ** 2, 1))) * cam["matrix"][0][0])
    return np.array(gaps), np.array(sizes), np.array(transfer)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder")
    parser.add_argument("--save")
    parser.add_argument("--distance", type=float, help="cm from the bottom of the wall to the board's pattern on the floor")
    parser.add_argument("--half", choices=("even", "odd"))
    parser.add_argument("--calibration-module", help="another version of hub/calibration.py, to compare")
    args = parser.parse_args()
    if args.calibration_module:
        spec = importlib.util.spec_from_file_location("calibration_under_test", args.calibration_module)
        calibration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(calibration)
    else:
        from hub import calibration
    recording = replay.load_run(args.folder)
    numbers = recording["numbers"]
    devices = {numbers[a]: info["device_id"] for a, info in recording["infos"].items()}
    lenses = {numbers[a]: replay.lens(info) for a, info in recording["infos"].items()}
    boards = find_boards(recording)
    walk = [s for s in boards["walk"] if len(s) >= 2]
    test = walk[3::4]
    train = [s for i, s in enumerate(walk) if i % 4 != 3]
    if args.half:
        train = train[0::2] if args.half == "even" else train[1::2]
    distance = args.distance or (recording["run"] or {}).get("floor_distance") or 50.0
    begin = time.perf_counter()
    result = calibration.solve(train, boards["floor"], {n: (devices[n], lenses[n]) for n in devices}, distance)
    print(f"solve {time.perf_counter() - begin:.0f} s from {len(train)} moments (floor board: {len(boards['floor'])} moments, "
          f"{distance:.0f} cm from the wall)")
    print("\n".join(result["report"]))
    gaps, sizes, transfer = check(calibration, result["cameras"], devices, lenses, test)
    if len(gaps):
        print(f"Held out ({len(test)} moments): lines of sight to the same corner {np.median(gaps) * 10:.1f} mm apart "
              f"(90 %: {np.percentile(gaps, 90) * 10:.1f}); transfer {np.median(transfer) if len(transfer) else float('nan'):.2f} px; "
              f"board square {np.median(sizes):.3f} cm (true 6.5)")
    if args.save:
        pathlib.Path(args.save).write_text(json.dumps({"cameras": result["cameras"], "score": result["score"]}))
        print(f"saved {args.save}")


if __name__ == "__main__":
    main()
