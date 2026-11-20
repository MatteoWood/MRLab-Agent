r"""Frame rate of the nDisplay node from its log: how many frames a second the wall got, in steps of 10 s.

    python Tools/node_fps.py                    reads Saved/Logs/Node_0.log (while the node runs, or afterwards)
    python Tools/node_fps.py <log file> [step in seconds]

On the LED wall PC use the engine's Python:
    "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" Tools\node_fps.py
NDC_Basic prints the tracked head (or INVALID) once per frame, so every frame leaves a line with its time and
its number (the log counts frames 0 to 999 and starts over). A frame above 100 ms is listed as a hitch.
"""
import pathlib
import re
import sys
from datetime import datetime

path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent / "Saved" / "Logs" / "Node_0.log"
step = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
stamp = re.compile(r"^\[(\d{4}\.\d\d\.\d\d-\d\d\.\d\d\.\d\d):(\d{3})\]\[\s*(\d+)\]")
times = []  # the time of each frame's line
last = None
try:
    lines = open(path, encoding="utf-8", errors="replace")
except OSError as error:
    sys.exit(f"Cannot read {path}: {error}")
for line in lines:
    m = stamp.match(line)
    if m and "LogBlueprintUserMessages" in line and ("X=" in line or "INVALID" in line) and m.group(3) != last:
        last = m.group(3)
        times.append(datetime.strptime(m.group(1), "%Y.%m.%d-%H.%M.%S").timestamp() + int(m.group(2)) / 1000.0)
if len(times) < 3:
    sys.exit(f"{path}: no frames found (NDC_Basic prints one line per frame once the node runs)")
start = times[0]
print(f"{path.name}: {len(times)} frames in {times[-1] - start:.0f} s")
first, hitches = 0, []
for i in range(1, len(times)):
    if times[i] - times[i - 1] > 0.1:
        hitches.append((times[i] - start, times[i] - times[i - 1]))
    if times[i] - times[first] >= step or i == len(times) - 1:
        print(f"  {times[first] - start:6.0f} s to {times[i] - start:6.0f} s: {(i - first) / max(times[i] - times[first], 1e-6):6.1f} frames a second")
        first = i
if hitches:
    print(f"  {len(hitches)} frames longer than 100 ms; the longest: " + ", ".join(f"{d * 1000:.0f} ms at {t:.0f} s" for t, d in sorted(hitches, key=lambda h: -h[1])[:5]))
