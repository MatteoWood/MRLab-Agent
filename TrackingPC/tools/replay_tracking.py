r"""How the tracker behaves on a recording or a hub tracking log, on the laptop.
    runtime\python\python.exe tools\replay_tracking.py recordings\<run folder> [--calibration file] [--ms 45]
    runtime\python\python.exe tools\replay_tracking.py recordings\tracking_<date_time>.jsonl.gz
    (either: [--tracker other_tracking.py] to try another version of hub/tracking.py)

Run folder (record_cameras.py, after tools\pose_pass.py): the people found are fed to the tracker as live,
each camera's helper needing --ms per picture (default 45, about the laptop's). Calibration: --calibration
(saved by replay_calibration.py) or the one in use in hub.local.json.
Tracking log (hub, "Record tracking data"): replayed in the order the hub had it; with the same tracker
version every sent head comes out exactly as logged (shown), so a newer tracker can be judged on the same
session.

Printed: updates a second, people, the largest step; for a guided run per phase: standing (updates that move
the sent head by more than 1 mm, wobble), moving (shake of the sent path along and across the direction of
movement, how far it is behind the head, how far from the head when sent); on marks A and B, how far the
sent head is from the mark and the eye height (the eyes are a few cm in front of the feet).
"""
import argparse
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import replay  # noqa: E402

STANDING = {"stand": (2.0, 0.0), "sway": (1.0, 0.0), "to_b": (-5.0, 0.0), "two": (-5.0, 0.0)}  # from start, or last s


def report(r, run=None):
    a, sent = r["arrival"], r["sent"]
    if len(a) < 10:
        print("too few updates of a main person to measure")
        return
    steps = np.linalg.norm(np.diff(sent, axis=0), axis=1)
    print(f"{len(a)} updates in {r['duration']:.1f} s ({len(a) / max(r['duration'], 1e-9):.0f} a second), person numbers used "
          f"{r['tracker'].next_number - 1}, 2 or more people in {np.mean(r['people'] >= 2) * 100:.0f} % of updates, "
          f"standing in {np.mean(r['state'] == 'still') * 100:.0f} %, largest step {steps.max():.1f} cm")
    whole = replay.moving(r, np.ones(len(a), bool))
    if whole:
        print(f"walking (median {whole['speed']:.0f} cm/s): shake along {whole['along']:.2f} cm, across {whole['across']:.2f} cm; "
              f"{whole['lag']:.0f} ms behind the head; {whole['off']:.1f} cm from it when sent")
    if not run or not run.get("phases"):
        return
    from hub import calibration
    marks = run.get("marks") or {}
    for name, what, start, end in run["phases"]:
        mask = (a >= start) & (a < end)
        line = f"  {name:6s} ({what[:40]}): "
        if name in STANDING:
            begin, _ = STANDING[name]
            part = mask & (a >= (start + begin if begin >= 0 else end + begin))
            share, wobble = replay.standing(sent, part)
            line += f"standing: {share * 100:.0f} % of updates move the head more than 1 mm, wobble {wobble:.1f} mm"
            mark = "A" if name == "stand" else "B" if name == "to_b" else None
            if mark in marks and part.sum() > 5:
                front, right = marks[mark]
                truth = np.array([calibration.WALL_X - front, calibration.WALL_Y + right, run.get("eye_height") or np.nan])
                off = sent[part].mean(0) - truth
                line += (f"; at mark {mark}: X {off[0]:+.1f} (towards the wall), Y {off[1]:+.1f} (right) cm"
                         + (f", eye height {off[2]:+.1f} cm" if run.get("eye_height") else ""))
        else:
            m = replay.moving(r, mask)
            line += (f"shake along {m['along']:.2f}, across {m['across']:.2f} cm; {m['lag']:.0f} ms behind; {m['off']:.1f} cm off when sent"
                     if m else "too little walking to measure")
        print(line)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="a recording folder or a tracking log (.jsonl.gz)")
    parser.add_argument("--calibration")
    parser.add_argument("--ms", type=float, default=45.0, help="ms per picture each camera's helper needs")
    parser.add_argument("--tracker", help="another version of hub/tracking.py")
    args = parser.parse_args()
    tracking = replay.tracker_module(args.tracker)
    source = pathlib.Path(args.source)
    if source.is_file():
        r = replay.replay_log(tracking, source)
        print(f"tracking log of {r['header']['made']}: {r['same']} of {r['logged']} sent heads come out exactly as the hub "
              f"sent them" + ("" if r["same"] == r["logged"] or r["start"] > 1 else
                              " (expected with another tracker version than the one that wrote the log)"))
        if r["start"] > 1:
            print("  (the log was switched on during tracking: the replay starts without the hub's people, so its first "
                  "seconds differ; switch it on before Start tracking for exact replays)")
        report(r)
    else:
        recording = replay.load_run(source)
        r = replay.feed(tracking, recording, replay.load_people(source), replay.load_calibration(args.calibration), args.ms / 1000)
        print(f"{source.name}, {args.ms:.0f} ms per picture:")
        report(r, recording["run"])


if __name__ == "__main__":
    main()
