r"""Runs the hub's pose model over every picture of a recording (record_cameras.py) and saves only the numbers:
per camera and picture the people found (box, 17 body points with confidence) in people.json.gz next to the
recording. Needed by replay_tracking.py and test_person.py. Uses the graphics card like the hub.
    runtime\python\python.exe tools\pose_pass.py recordings\<run folder>
Takes about 3 minutes for 30 s of 8 cameras on the laptop (RTX 4090).
"""
import gzip
import json
import multiprocessing
import pathlib
import sys
import time
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def camera(path):
    sys.path.insert(0, str(ROOT))
    import cv2
    cv2.setNumThreads(1)
    from hub import cameras, pose
    model = pose.PoseModel(lambda text: None, device="graphics card (DirectML)", threads=2)
    archive = zipfile.ZipFile(path)
    info = json.loads(archive.read("info.json"))
    found = []
    for name in sorted(n for n in archive.namelist() if n.endswith(".jpg")):
        people = cameras.find_people(model, archive.read(name))
        found.append([[[float(v) for v in box], points.tolist(), float(score)] for box, points, score in people])
    return info["address"], found


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    folder = pathlib.Path(sys.argv[1])
    paths = sorted(str(p) for p in folder.glob("camera_*.zip"))
    if not paths:
        sys.exit(f"No camera recordings (camera_*.zip) in {folder}")
    begin = time.perf_counter()
    with multiprocessing.Pool(4) as pool:
        results = dict(pool.map(camera, paths))
    with gzip.open(folder / "people.json.gz", "wt") as out:
        json.dump(results, out)
    per = {a[-3:]: round(sum(len(p) for p in found) / max(len(found), 1), 2) for a, found in sorted(results.items())}
    print(f"pose pass {time.perf_counter() - begin:.0f} s, saved {folder / 'people.json.gz'}; people per picture: {per}")


if __name__ == "__main__":
    main()
