"""Shared parts of the test tools (GUIDE.md, "Testing on the laptop"): reading recordings (record_cameras.py),
the pose pass results and tracking logs, feeding the tracker as it would be fed live, and the measures.

All times are on the cameras' clock ("camera_time" of the recordings; the hub's time.perf_counter() in a
tracking log). Nothing here writes outside the recording's folder.
"""
import gzip
import importlib.util
import json
import pathlib
import sys
import zipfile
from types import SimpleNamespace

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent  # the TrackingPC folder
sys.path.insert(0, str(ROOT))
LATENCY = 0.015  # s from a picture to its helper (transfer)


def tracker_module(path=None):
    """hub.tracking, or another version of it from a file (to compare)."""
    if path is None:
        from hub import tracking
        return tracking
    spec = importlib.util.spec_from_file_location("tracking_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------- recordings ----------

def camera_order():
    """Camera addresses in the hub's order (runtime/defaults.json, "camera_order"); [] without it."""
    path = ROOT / "runtime" / "defaults.json"
    return json.loads(path.read_text()).get("camera_order", []) if path.exists() else []


def load_run(folder):
    """{"infos": {address: info.json without the pictures}, "zips": {address: path}, "run": run.json or None,
    "numbers": {address: camera number}}."""
    folder = pathlib.Path(folder)
    zips = {}
    infos = {}
    for path in sorted(folder.glob("camera_*.zip")):
        info = json.loads(zipfile.ZipFile(path).read("info.json"))
        infos[info["address"]] = info
        zips[info["address"]] = path
    if not infos:
        sys.exit(f"No camera recordings (camera_*.zip) in {folder}")
    order = camera_order()
    numbers = {a: order.index(a) + 1 if a in order else len(order) + i + 1 for i, a in enumerate(sorted(infos))}
    run = json.loads((folder / "run.json").read_text()) if (folder / "run.json").exists() else None
    return {"folder": folder, "infos": infos, "zips": zips, "run": run, "numbers": numbers}


def lens(info, matrix=None):
    out = {k: info[k] for k in ("size", "matrix", "distortion", "fisheye")}
    if matrix is not None:
        out["matrix"] = matrix
    return out


def load_people(folder):
    """The pose pass results (pose_pass.py): {address: [[(box, points (17, 3) float32, score), ...] per picture]}."""
    path = pathlib.Path(folder) / "people.json.gz"
    if not path.exists():
        sys.exit(f"No {path.name} in {folder}: run tools\\pose_pass.py on it first")
    data = json.loads(gzip.open(path, "rt").read())
    return {a: [[(tuple(b), np.array(p, np.float32), s) for b, p, s in found] for found in pictures]
            for a, pictures in data.items()}


def load_calibration(path=None):
    """Camera poses: from a file saved by replay_calibration.py ({"cameras": ...}), or the calibration in use
    in hub.local.json."""
    path = pathlib.Path(path) if path else ROOT / "hub.local.json"
    data = json.loads(path.read_text())
    cameras = data["cameras"] if "cameras" in data else (data.get("calibration") or {}).get("cameras")
    if not cameras:
        sys.exit(f"No calibration in {path}")
    return cameras


# ---------- feeding the tracker ----------

def tracker_for(tracking, cameras, poses, log=None):
    """A tracker without network or pose model: cameras [(device id, lens, address)]."""
    stand_ins = [SimpleNamespace(device_id=d, lens=lens_, address=a, worker=SimpleNamespace(pose=lambda device: None),
                                 on_people=None) for d, lens_, a in cameras]
    settings = {"unreal_address": "127.0.0.1", "moverse_port": 1}
    return tracking.Tracker(stand_ins, poses, settings, log=log or (lambda text: None)), {c.device_id: c for c in stand_ins}


def feed(tracking, recording, people, poses, process=0.045, log=None):
    """The recording's people (pose pass) into a tracker as live: each camera's helper takes its newest
    picture when free and needs `process` s per picture (0: every picture, LATENCY after it was taken).
    Returns per update of the main person numpy arrays: arrival, moment, raw (measured head), sent, state,
    main, people (confirmed people seen); and "tracker", "duration"."""
    cameras, events = [], []
    for k, (address, info) in enumerate(sorted(recording["infos"].items())):
        if info["device_id"] not in poses:
            continue
        cameras.append((info["device_id"], lens(info), address))
        times = info["camera_time"]
        if process <= 0:
            chosen = [(i, t + LATENCY) for i, t in enumerate(times)]
        else:
            chosen, free, i = [], times[0] + process * k / 8, 0
            while i < len(times):
                while i + 1 < len(times) and times[i + 1] + LATENCY <= free:
                    i += 1
                begin = max(free, times[i] + LATENCY)
                chosen.append((i, begin + process))
                free, i = begin + process, i + 1
        events += [(arrival, times[i], info["device_id"], people[address][i]) for i, arrival in chosen]
    events.sort(key=lambda e: e[0])
    tracker, stand_ins = tracker_for(tracking, cameras, poses, log)
    out = {k: [] for k in ("arrival", "moment", "raw", "sent", "state", "main", "people")}
    last = -1.0
    for arrival, captured, device, found in events:
        tracker.on_people(stand_ins[device], captured, found)
        if arrival - last < tracking.MIN_INTERVAL:
            continue
        last = arrival
        if tracker.update(arrival):
            record(out, tracker, arrival)
    result = {k: np.array(v) for k, v in out.items()}
    result["tracker"], result["duration"] = tracker, events[-1][0] - events[0][0]
    return result


def record(out, tracker, now):
    out["arrival"].append(now)
    out["moment"].append(tracker.filter.t)
    out["raw"].append(np.array(tracker.tracks[tracker.main]["position"], float))
    out["sent"].append(np.array(tracker.position, float))
    out["state"].append(tracker.motion)
    out["main"].append(tracker.main)
    out["people"].append(len(tracker.people))


def replay_log(tracking, path, log=None):
    """A hub tracking log through a tracker: the pictures' people and the combining steps in the order the hub
    had them. Returns feed()'s arrays plus "same": how many sent heads equal the logged ones (all of them
    with the tracker that wrote the log), "logged": how many there were, "header"."""
    lines = gzip.open(path, "rt", encoding="utf-8")
    header = json.loads(next(lines))
    cameras = [(d, c["lens"], c["address"]) for d, c in header["cameras"].items()]
    tracker, stand_ins = tracker_for(tracking, cameras, header["calibration"], log)
    out = {k: [] for k in ("arrival", "moment", "raw", "sent", "state", "main", "people")}
    same = logged = 0
    first, start = None, 1
    for line in lines:
        item = json.loads(line)
        if "p" in item:
            if first is None:  # a log switched on during tracking starts later: counted from there, the tracker
                tracker.version = tracker.used = item["v"] - 1  # starts fresh (its first seconds differ from the hub's)
                start = item["v"]
            found = [(tuple(b), np.array(p, np.float32), s) for b, p, s in item["people"]]
            tracker.on_people(stand_ins[item["d"]], item["c"], found)
            first = item["p"] if first is None else first
        elif "u" in item:
            if tracker.version != item["v"]:
                sys.exit(f"{path}: the log is out of order at picture {item['v']}")
            if tracker.update(item["u"]):
                record(out, tracker, item["u"])
        elif "s" in item:
            logged += 1
            same += bool(out["arrival"]) and out["arrival"][-1] == item["s"] and np.array_equal(out["sent"][-1], item["pos"])
    result = {k: np.array(v) for k, v in out.items()}
    result.update(tracker=tracker, same=same, logged=logged, header=header, start=start,
                  duration=(out["arrival"][-1] - first) if out["arrival"] and first else 0.0)
    return result


# ---------- measures ----------

def centred(t, x, width):
    """Centred moving average of x (by time t) over width s."""
    return np.array([x[np.abs(t - ti) <= width / 2].mean(0) for ti in t])


def standing(sent, mask):
    """(share of updates that move the sent head by more than 1 mm, wobble RMS mm) where mask."""
    seg = sent[mask]
    if len(seg) < 3:
        return float("nan"), float("nan")
    steps = np.linalg.norm(np.diff(seg, axis=0), axis=1)
    return float(np.mean(steps > 0.1)), float(np.sqrt(np.mean(np.sum((seg - seg.mean(0)) ** 2, 1)))) * 10


def moving(r, mask):
    """While walking (speed over 30 cm/s) within mask: shake of the sent path along / across the direction
    of movement (cm, RMS from its own 0.25 s average), ms behind the measured head (pictures to sending
    included), cm from the head at the moment sent (RMS). The measured heads' 0.25 s average stands in for
    the true head."""
    a, t, raw, sent = r["arrival"], r["moment"], r["raw"], r["sent"]
    ref = centred(t, raw, 0.25)
    speed = np.linalg.norm(np.gradient(centred(t, raw, 0.5), t, axis=0), axis=1)
    fast = mask & (speed > 30)
    if fast.sum() < 20:
        return None
    own = centred(a, sent, 0.25)
    direction = np.gradient(centred(a, sent, 0.5), a, axis=0)
    direction /= np.maximum(np.linalg.norm(direction, axis=1, keepdims=True), 1e-9)
    shake = sent - own
    along = np.sum(shake * direction, 1)
    across = shake - along[:, None] * direction
    lag = min((np.sqrt(np.mean(np.sum((sent[fast] - np.array([np.interp(a[fast] - d, t, ref[:, k]) for k in range(3)]).T) ** 2, 1))), d)
              for d in np.arange(-0.1, 0.3, 0.005))[1]
    inside = fast & (a <= t[-1])
    now = np.array([np.interp(a[inside], t, ref[:, k]) for k in range(3)]).T
    return {"along": float(np.sqrt(np.mean(along[fast] ** 2))), "across": float(np.sqrt(np.mean(np.sum(across[fast] ** 2, 1)))),
            "lag": lag * 1000, "off": float(np.sqrt(np.mean(np.sum((sent[inside] - now) ** 2, 1)))),
            "speed": float(np.median(speed[fast]))}
