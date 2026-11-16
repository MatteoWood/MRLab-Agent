r"""A test person on a known path, seen by the 8 cameras with real detection noise: how steady, how quick, how
far off the tracker is where the truth is known (README 4.12, D81).
    runtime\python\python.exe tools\test_person.py recordings\<walking run> [--calibration-a a.json]
        [--calibration-b b.json] [--ms 45] [--tracker other_tracking.py]

- Noise: from a recording of someone walking (after tools\pose_pass.py): per camera, that person's face
  points minus a smooth curve through 13 pictures (0.2 s): the pose model's jitter, picture by picture, with
  its real confidences and gaps (kept as test_person_noise.npz next to the recording).
- Path (the truth, middle of the eyes): standing, walking 1.2 to 2 m, a 10 cm lean, swaying 1.5 cm on the
  spot, a quick 30 cm side step.
- Pictures: the face points projected with calibration A (with the cameras' lens distortion) plus the noise;
  each camera's helper needs --ms per picture; the tracker uses calibration B, so the cameras disagree a
  little as in reality. Two independent calibrations: replay_calibration.py --half even / odd --save.
  Without them both are the calibration in use (hub.local.json): no disagreement.
Printed per part: standing (updates moving the sent head by more than 1 mm, wobble), moving (mean and
largest distance from the true head now, lag, when the wall starts to follow, overshoot where the person
stops, error across the direction of movement).
"""
import argparse
import pathlib
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import replay  # noqa: E402

FACE = (0, 1, 2, 3, 4)  # nose, left eye, right eye, left ear, right ear (COCO)
# face points from the middle of the eyes when facing the wall (+X); tracking Y is right, so left is -Y
OFFSETS = np.array([[2.0, 0.0, -4.0], [0.0, -3.2, 0.0], [0.0, 3.2, 0.0], [-9.0, -7.5, -1.5], [-9.0, 7.5, -1.5]])


def min_jerk(a, b, t0, t1):
    a, b = np.array(a, float), np.array(b, float)
    return lambda t: a + (b - a) * (lambda s: 10 * s ** 3 - 15 * s ** 4 + 6 * s ** 5)(np.clip((t - t0) / (t1 - t0), 0, 1))


def script():
    """[(start, end, name, kind, truth(t))]; kind: still, sway or move."""
    A, B, L = (230.0, -80.0, 160.0), (230.0, 70.0, 160.0), (240.0, 70.0, 157.0)
    C, D, E = (320.0, -10.0, 157.0), (320.0, 20.0, 157.0), (150.0, 120.0, 160.0)
    parts, t = [], 0.0

    def add(duration, name, kind, f):
        nonlocal t
        parts.append((t, t + duration, name, kind, f))
        t += duration
    add(4.0, "standing", "still", lambda t: np.array(A))
    add(2.0, "walk 1.5 m sideways", "move", min_jerk(A, B, t, t + 2.0))
    add(3.0, "standing", "still", lambda t: np.array(B))
    add(0.6, "lean 10 cm forward", "move", min_jerk(B, L, t, t + 0.6))
    add(3.0, "standing", "still", lambda t: np.array(L))
    add(1.6, "walk 1.2 m diagonally", "move", min_jerk(L, C, t, t + 1.6))
    add(3.0, "standing", "still", lambda t: np.array(C))
    s0 = t
    add(5.0, "swaying 1.5 cm", "sway", lambda t: np.array(C) + np.array([0, 1.5, 0]) * np.sin(2 * np.pi * 0.3 * (t - s0)))
    add(0.5, "side step 30 cm", "move", min_jerk(C, D, t, t + 0.5))
    add(3.0, "standing", "still", lambda t: np.array(D))
    add(2.4, "walk 2 m back", "move", min_jerk(D, E, t, t + 2.4))
    add(3.0, "standing", "still", lambda t: np.array(E))
    return parts


PARTS = script()
END = PARTS[-1][1]


def truth(t):
    return next((f(t) for start, end, _, _, f in PARTS if start <= t < end), PARTS[-1][4](END))


def project(points, cam, distortion):
    """Pixels of points (N, 3) in a camera of a calibration; NaN behind it."""
    local = (points - np.array(cam["position"])) @ np.array(cam["rotation"])
    out = np.full((len(points), 2), np.nan)
    ahead = local[:, 2] > 10
    if ahead.any():
        pix, _ = cv2.projectPoints(local[ahead].reshape(-1, 1, 3), np.zeros(3), np.zeros(3), np.array(cam["matrix"], float),
                                   np.array(distortion, float))
        out[ahead] = pix.reshape(-1, 2)
    return out


def extract_noise(tracking, recording, people, poses):
    """{device id: (pictures, 5, 3) of (dx, dy, confidence)}, NaN where the walking person was not seen."""
    r = replay.feed(tracking, recording, people, poses, process=0)
    t_ref, raw = r["moment"], r["raw"]
    noise = {}
    for address, info in recording["infos"].items():
        times = np.array(info["camera_time"])
        head = np.array([np.interp(times, t_ref, raw[:, k]) for k in range(3)]).T
        pix = project(head, poses[info["device_id"]], info["distortion"])
        frames = []
        for i, found in enumerate(people[address]):
            best = None
            for _, points, _ in found:
                face = points[list(FACE)]
                good = face[:, 2] >= 0.5
                if good.any() and not np.isnan(pix[i, 0]):
                    gap = np.linalg.norm(face[good, :2].mean(0) - pix[i])
                    if gap < 80 and (best is None or gap < best[0]):
                        best = (gap, face)
            frames.append(best[1] if best and t_ref[0] <= times[i] <= t_ref[-1] else None)
        res = np.full((len(frames), 5, 3), np.nan)
        x = np.arange(-6, 7)
        for i, f in enumerate(frames):
            if f is None:
                continue
            res[i, :, 2], res[i, :, :2] = f[:, 2], 0.0
            if i < 6 or i >= len(frames) - 6:
                res[i, :, 2] = 0.0
                continue
            window = frames[i - 6:i + 7]
            for k in range(5):
                if f[k, 2] < 0.5:
                    continue
                if any(w is None or w[k, 2] < 0.5 for w in window):
                    res[i, k, 2] = 0.0  # no clean noise sample: dropped
                    continue
                y = np.array([w[k, :2] for w in window])
                res[i, k, :2] = y[6] - np.polyfit(x, y, 2)[-1]
        noise[info["device_id"]] = res
    return noise


def run(tracking, recording, poses_a, poses_b, noise, process, seed=1):
    rng = np.random.default_rng(seed)
    infos = {info["device_id"]: info for info in recording["infos"].values()}
    cameras, events = [], []
    for device, info in sorted(infos.items()):
        if device not in poses_b or device not in poses_a:
            continue
        cameras.append((device, replay.lens(info), info["address"]))
        times = rng.uniform(0, 1 / 60) + np.arange(0, END, 1 / 60)
        offset = int(rng.integers(0, len(noise[device])))
        free, i = times[0] + rng.uniform(0, process), 0
        w, h = info["size"]
        while i < len(times):
            while i + 1 < len(times) and times[i + 1] + replay.LATENCY <= free:
                i += 1
            free = max(free, times[i] + replay.LATENCY) + process
            sample = noise[device][(i + offset) % len(noise[device])]
            found = []
            if not np.isnan(sample[0, 2]):
                face = truth(times[i]) + OFFSETS
                pix = project(face, poses_a[device], info["distortion"])
                if not np.isnan(pix).any() and np.all((pix > 0) & (pix < [w, h])):
                    points = np.zeros((17, 3), np.float32)
                    points[list(FACE), :2] = pix + sample[:, :2]
                    points[list(FACE), 2] = sample[:, 2]
                    c = pix.mean(0)
                    found.append(((c[0] - 60, c[1] - 60, c[0] + 60, c[1] + 300), points, 0.9))
            events.append((free, times[i], device, found))
            i += 1
    events.sort(key=lambda e: e[0])
    tracker, stand_ins = replay.tracker_for(tracking, cameras, poses_b)
    out = {k: [] for k in ("arrival", "moment", "raw", "sent", "state", "main", "people")}
    last = -1.0
    for arrival, captured, device, found in events:
        tracker.on_people(stand_ins[device], captured, found)
        if arrival - last < tracking.MIN_INTERVAL:
            continue
        last = arrival
        if tracker.update(arrival):
            replay.record(out, tracker, arrival)
    result = {k: np.array(v) for k, v in out.items()}
    result["tracker"] = tracker
    return result


def evaluate(r):
    a, sent = r["arrival"], r["sent"]
    true_now = np.array([truth(t) for t in a])
    still = np.zeros(len(a), bool)
    for start, end, _, kind, _ in PARTS:
        still |= (kind == "still") & (a >= start + 1.0) & (a < end)
    bias = np.median((sent - true_now)[still], axis=0)  # the calibrations' difference, not the tracker's
    print(f"{len(a)} updates ({len(a) / (a[-1] - a[0]):.0f} a second), person numbers used {r['tracker'].next_number - 1}; "
          f"calibration A against B {np.linalg.norm(bias):.1f} cm apart (taken out below)")
    sent = sent - bias
    for start, end, name, kind, f in PARTS:
        if kind == "move":
            m = (a >= start) & (a < end + 0.3)
            err = np.linalg.norm(sent[m] - true_now[m], axis=1)
            lag = min((np.sqrt(np.mean(np.sum((sent[m] - np.array([truth(t - d) for t in a[m]])) ** 2, 1))), d)
                      for d in np.arange(0, 0.3, 0.005))[1]
            target, origin = f(end), f(start)
            direction = (target - origin) / np.linalg.norm(target - origin)
            after = (a >= end) & (a < end + 1.5)
            over = max(0.0, float(np.max((sent[after] - target) @ direction))) if after.any() else float("nan")
            t_true = a[np.argmax((np.linalg.norm(true_now - f(start), axis=1) > 1.0) & (a >= start))]
            t_sent = a[np.argmax((np.linalg.norm(sent - f(start), axis=1) > 1.0) & (a >= start))]
            across = (sent[m] - true_now[m]) - np.outer((sent[m] - true_now[m]) @ direction, direction)
            print(f"  {name:22s} moving: {err.mean():4.1f} cm from the true head (largest {err.max():4.1f}), lag {lag * 1000:3.0f} ms, "
                  f"follows {max(0.0, t_sent - t_true) * 1000:3.0f} ms after it starts, overshoot {over:.1f} cm, "
                  f"across {np.sqrt(np.mean(np.sum(across ** 2, 1))):.2f} cm")
        else:
            m = (a >= start + 0.6) & (a < end)
            share, wobble = replay.standing(sent, m)
            print(f"  {name:22s} {'standing' if kind == 'still' else 'swaying '}: {share * 100:3.0f} % of updates move the sent head "
                  f"more than 1 mm, wobble {wobble:4.1f} mm, {np.linalg.norm(sent[m] - true_now[m], axis=1).mean():.1f} cm from the truth")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("walking", help="recording folder of someone walking, after pose_pass.py")
    parser.add_argument("--calibration-a")
    parser.add_argument("--calibration-b")
    parser.add_argument("--ms", type=float, default=45.0)
    parser.add_argument("--tracker")
    args = parser.parse_args()
    tracking = replay.tracker_module(args.tracker)
    recording = replay.load_run(args.walking)
    poses_a = replay.load_calibration(args.calibration_a)
    poses_b = replay.load_calibration(args.calibration_b) if args.calibration_b else poses_a
    cache = recording["folder"] / "test_person_noise.npz"
    if cache.exists():
        noise = dict(np.load(cache))
    else:
        noise = extract_noise(replay.tracker_module(), recording, replay.load_people(args.walking), poses_a)
        np.savez(cache, **noise)
    print(f"test person, {args.ms:.0f} ms per picture:")
    evaluate(run(tracking, recording, poses_a, poses_b, noise, args.ms / 1000))


if __name__ == "__main__":
    main()
