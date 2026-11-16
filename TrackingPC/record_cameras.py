r"""Records what the OAK cameras send, to test the tracking and the calibration later without the lab
(TrackingPC/tools, GUIDE.md). Run on the tracking PC, in this folder, with Moverse and the hub closed:
    runtime\python\python.exe record_cameras.py            guided test run (about 60 s, prompts and beeps)
    runtime\python\python.exe record_cameras.py two        the same, a second person joins at the end
    runtime\python\python.exe record_cameras.py board      calibration board: 60 s walking, 15 s on the floor
    runtime\python\python.exe record_cameras.py free 30    30 s of whatever happens
Result: recordings\<date>_<time>_<kind>\ with one file per camera and run.json. The recordings show
people: they stay on this PC (the recordings folder is never put into Git); delete them when done.

Guided run: tape two marks on the floor first. A: 150 cm in front of the middle of the LED wall (measured
from the bottom of the wall). B: also 150 cm in front, and 100 cm to the right (seen facing the wall).
The script asks for your eye height (floor to eyes, cm), then shows what to do and beeps at each change.

Each camera file is a ZIP without compression, written while recording (a run does not have to fit in
memory: about 11 MB a second per camera):
    00000.jpg, 00001.jpg, ...  the pictures in order, byte for byte as the camera sent them (JPEG, 1280
                               wide, 60 per second, quality 90: the same camera settings as hub/cameras.py)
    info.json                  address, device_id (the key of the hub's calibration), size and the lens
                               data the tracker uses (matrix, distortion, fisheye), and two lists with
                               one time per picture, in seconds, on clocks all cameras share:
                               "captured" as the hub computes it, "camera_time" the camera's own stamp
run.json: kind, phases [name, what to do, start, end] on the camera_time clock, eye height, marks, and for
a board run the measured distance of the board from the wall.
"""
import json
import multiprocessing
import os
import pathlib
import queue
import sys
import threading
import time
import zipfile

COUNTDOWN = 10  # seconds from "all cameras are streaming" to the start, to walk into the room
SIZE_WIDTH, FPS, JPEG_QUALITY = 1280, 60, 90  # as hub/cameras.py
REOPEN_WAIT = 20.0  # a camera that was just closed restarts first (as hub/cameras.py)
HERE = pathlib.Path(__file__).resolve().parent
MARKS = {"A": [150.0, 0.0], "B": [150.0, 100.0]}  # cm in front of the wall's middle, cm to the right of it
GUIDED = [  # (seconds, name, what to do)
    (10, "stand", "Stand on mark A, face the wall, and stand still"),
    (8, "sway", "Stay on mark A and sway gently (feet stay where they are)"),
    (8, "lean", "Lean slowly towards the wall and back, twice"),
    (10, "step", "Step 30 cm to the side, stand, step back, stand"),
    (12, "to_b", "Walk to mark B and stand still there, facing the wall"),
    (12, "walk", "Walk around freely, then stop anywhere"),
]
SECOND = (10, "two", "Second person: walk in. Then both stand still")
BOARD = [
    (60, "walk", "Hold the board high, facing two or three cameras at once, tilt it now and then, move around"),
    (15, "floor", "Lay the board flat on the floor (long side parallel to the wall, middle in front of the "
                  "wall's middle) and step away"),
]


def open_device(dai, info):
    """As hub/cameras.py: the camera with the details from the search, then retries by address only."""
    name, device_id, state, protocol, platform = info
    target = dai.DeviceInfo(name, device_id, dai.XLinkDeviceState.__members__[state],
                            dai.XLinkProtocol.__members__[protocol], dai.XLinkPlatform.__members__[platform],
                            dai.XLinkError_t.X_LINK_SUCCESS)
    deadline = time.monotonic() + REOPEN_WAIT
    while True:
        try:
            return dai.Device(target)
        except RuntimeError as error:
            if time.monotonic() > deadline:
                raise
            print(f"{name}: not ready ({error}), retrying", flush=True)
            target = dai.DeviceInfo(name)
            time.sleep(1.0)


def write(archive, pending):
    """Writes the pictures to the ZIP as they come (own thread, so taking pictures never waits for the disk)."""
    while True:
        item = pending.get()
        if item is None:
            return
        archive.writestr(*item)


def record(info, folder, ready, start, stop):
    """One camera, in its own process as in the hub (opening all cameras in one process crashed DepthAI).
    Writes the pictures that arrive between start and stop to its file, then the times."""
    import depthai as dai

    address, device_id = info[0], info[1]
    device = open_device(dai, info)
    path = folder / f"camera_{address}.zip"
    archive, pending, writer = None, queue.Queue(), None
    with dai.Pipeline(device) as pipeline:  # the same pipeline as camera_process in hub/cameras.py
        socket = dai.CameraBoardSocket.CAM_A
        sensor = next(f for f in device.getConnectedCameraFeatures() if f.socket == socket)
        size = (SIZE_WIDTH, round(SIZE_WIDTH * sensor.height / sensor.width / 16) * 16)
        color = pipeline.create(dai.node.Camera).build(socket)
        output = color.requestOutput(size, dai.ImgFrame.Type.NV12, fps=FPS)
        encoder = pipeline.create(dai.node.VideoEncoder).build(
            output, frameRate=FPS, profile=dai.VideoEncoderProperties.Profile.MJPEG, quality=JPEG_QUALITY)
        # The hub keeps 2 pictures (it only wants the newest); here none may be lost.
        frames = encoder.out.createOutputQueue(maxSize=30, blocking=False)
        calibration = device.readCalibration()
        details = {
            "address": address, "device_id": device_id, "product": device.getProductName(),
            "sensor": sensor.sensorName, "size": size, "fps": FPS, "jpeg_quality": JPEG_QUALITY,
            "matrix": calibration.getCameraIntrinsics(socket, *size),
            "distortion": calibration.getDistortionCoefficients(socket),
            "fisheye": calibration.getDistortionModel(socket).name == "Fisheye",
        }
        pipeline.start()
        captured, camera_time = [], []
        while not stop.is_set() and pipeline.isRunning():
            frame = frames.tryGet()
            if frame is None:
                time.sleep(0.001)
                continue
            if not ready.is_set():
                ready.set()
                print(f"{address}: streaming", flush=True)
            if start.is_set():
                if archive is None:
                    archive = zipfile.ZipFile(path, "w")  # stored, not compressed
                    writer = threading.Thread(target=write, args=(archive, pending))
                    writer.start()
                stamp = frame.getTimestamp()  # on the PC's fine clock (dai.Clock), set by the camera
                captured.append(time.perf_counter() - (dai.Clock.now() - stamp).total_seconds())  # as the hub
                camera_time.append(stamp.total_seconds())
                pending.put((f"{len(camera_time) - 1:05d}.jpg", frame.getData().tobytes()))
    if archive is None:
        return
    pending.put(None)
    writer.join()
    archive.writestr("info.json", json.dumps(details | {"captured": captured, "camera_time": camera_time}))
    archive.close()
    span = camera_time[-1] - camera_time[0] if len(camera_time) > 1 else 0.0
    print(f"{address}: {len(camera_time)} pictures ({len(camera_time) / max(span, 1e-9):.1f} per second), "
          f"{path.stat().st_size / 1e6:.0f} MB", flush=True)


def ask(question):
    try:
        return input(question).strip()
    except EOFError:
        return ""


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else "guided"
    if kind not in ("guided", "two", "board", "free"):
        sys.exit(__doc__)
    if kind == "free":
        seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
        phases = [(seconds, "free", "Do what you want to test")]
    else:
        phases = BOARD if kind == "board" else GUIDED + ([SECOND] if kind == "two" else [])
    # Home, AppData and temp inside .\runtime (as env.bat), so nothing is written outside this folder.
    home, temp = HERE / "runtime" / "home", HERE / "runtime" / "temp"
    for name, path in {"USERPROFILE": home, "HOME": home, "APPDATA": home / "AppData" / "Roaming",
                       "LOCALAPPDATA": home / "AppData" / "Local", "TEMP": temp, "TMP": temp}.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)
    import depthai as dai

    run = {"kind": kind, "marks": MARKS if kind in ("guided", "two") else None}
    if kind in ("guided", "two"):
        print("Tape mark A 150 cm in front of the middle of the LED wall, mark B 150 cm in front and 100 cm to "
              "the right (seen facing the wall).")
        answer = ask("Your eye height in cm (floor to eyes; Enter to skip): ")
        run["eye_height"] = float(answer) if answer.replace(".", "", 1).isdigit() else None

    print("Searching for the cameras...", flush=True)
    cameras = sorted((info.name, info.deviceId, info.state.name, info.protocol.name, info.platform.name)
                     for info in dai.Device.getAllConnectedDevices())
    in_use = [c[0] for c in cameras if c[2] in ("X_LINK_BOOTED", "X_LINK_BOOTED_NON_EXCLUSIVE")]
    print(f"{len(cameras)} cameras: {', '.join(c[0] for c in cameras)}", flush=True)
    if in_use:
        sys.exit(f"In use by another program: {', '.join(in_use)}. Close Moverse and the hub, then try again.")
    if not cameras:
        sys.exit("No camera found. Close Moverse and the hub (they hold the cameras), then try again.")

    recordings = HERE / "recordings"
    recordings.mkdir(exist_ok=True)
    (recordings / ".gitignore").write_text("*\n")  # the recordings are large, local and show people: never into Git
    folder = recordings / f"{time.strftime('%Y-%m-%d_%H-%M-%S')}_{kind}"
    folder.mkdir()
    start, stop = multiprocessing.Event(), multiprocessing.Event()
    workers = []
    for info in cameras:
        ready = multiprocessing.Event()
        process = multiprocessing.Process(target=record, args=(info, folder, ready, start, stop), daemon=True)
        process.start()
        workers.append((process, ready))
    print("Opening the cameras...", flush=True)
    while not all(ready.is_set() for _, ready in workers):
        if not all(process.is_alive() for process, _ in workers):
            sys.exit("A camera did not start (see the error above). Nothing was recorded.")
        time.sleep(0.1)

    print(f"First: {phases[0][2]}", flush=True)
    for left in range(COUNTDOWN, 0, -1):
        print(f"Recording starts in {left} s", flush=True)
        time.sleep(1)
    start.set()
    run["phases"] = []
    for number, (seconds, name, what) in enumerate(phases, 1):
        begin = dai.Clock.now().total_seconds()  # the clock of the cameras' stamps (camera_time)
        print(f"\a\n>>> {number}/{len(phases)}  {what}  ({seconds:.0f} s)", flush=True)
        time.sleep(seconds)
        run["phases"].append([name, what, begin, dai.Clock.now().total_seconds()])
    stop.set()
    print("\a\nDone. Saving the files...", flush=True)
    for process, _ in workers:
        process.join()
    if kind == "board":
        answer = ask("Distance from the bottom of the wall to the near edge of the board's black and white pattern, "
                     "cm (as on the Calibration page): ")
        run["floor_distance"] = float(answer) if answer.replace(".", "", 1).isdigit() else None
    (folder / "run.json").write_text(json.dumps(run, indent=1))
    print(f"Saved in {folder.relative_to(HERE)}")


if __name__ == "__main__":
    main()
