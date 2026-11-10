r"""Records what the OAK cameras send for 30 seconds, to test the tracking later without the lab.

Run on the tracking PC, in this folder, with Moverse and the hub closed (they hold the cameras):
    runtime\python\python.exe record_cameras.py
Walk around between the two beeps. Result: recordings\camera_<camera address>.zip, one file per camera
(a new run replaces them).

The pictures are the ones the hub feeds to the tracking (same camera settings as hub/cameras.py): JPEG,
1280 wide, 60 per second, quality 90, saved byte for byte as the camera sent them. Each file is a ZIP
without compression:
    00000.jpg, 00001.jpg, ...  the pictures in order
    info.json                  address, device_id (the key of the hub's calibration), size and the lens
                               data the tracker uses (matrix, distortion, fisheye), and two lists with
                               one time per picture, in seconds, on clocks all cameras share:
                               "captured" as the hub computes it (the time the tracking gets),
                               "camera_time" the camera's own stamp (finer, see record)
"""
import json
import multiprocessing
import os
import pathlib
import sys
import time
import zipfile

SECONDS = 30
COUNTDOWN = 10  # seconds from "all cameras are streaming" to the start, to walk into the room
SIZE_WIDTH, FPS, JPEG_QUALITY = 1280, 60, 90  # as hub/cameras.py
REOPEN_WAIT = 20.0  # a camera that was just closed restarts first (as hub/cameras.py)
HERE = pathlib.Path(__file__).resolve().parent


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


def record(info, folder, ready, start, stop):
    """One camera, in its own process as in the hub (opening all cameras in one process crashed DepthAI).
    Keeps the pictures that arrive between start and stop in memory, then writes the file."""
    import depthai as dai

    address, device_id = info[0], info[1]
    device = open_device(dai, info)
    with dai.Pipeline(device) as pipeline:  # the same pipeline as camera_process in hub/cameras.py
        socket = dai.CameraBoardSocket.CAM_A
        sensor = next(f for f in device.getConnectedCameraFeatures() if f.socket == socket)
        size = (SIZE_WIDTH, round(SIZE_WIDTH * sensor.height / sensor.width / 16) * 16)
        color = pipeline.create(dai.node.Camera).build(socket)
        output = color.requestOutput(size, dai.ImgFrame.Type.NV12, fps=FPS)
        encoder = pipeline.create(dai.node.VideoEncoder).build(
            output, frameRate=FPS, profile=dai.VideoEncoderProperties.Profile.MJPEG, quality=JPEG_QUALITY)
        # The hub keeps 2 pictures (it only wants the newest); here none may be lost.
        queue = encoder.out.createOutputQueue(maxSize=30, blocking=False)
        calibration = device.readCalibration()
        details = {
            "address": address, "device_id": device_id, "product": device.getProductName(),
            "sensor": sensor.sensorName, "size": size, "fps": FPS, "jpeg_quality": JPEG_QUALITY,
            "matrix": calibration.getCameraIntrinsics(socket, *size),
            "distortion": calibration.getDistortionCoefficients(socket),
            "fisheye": calibration.getDistortionModel(socket).name == "Fisheye",
        }
        pipeline.start()
        captured, camera_time, pictures = [], [], []
        while not stop.is_set() and pipeline.isRunning():
            frame = queue.tryGet()
            if frame is None:
                time.sleep(0.001)
                continue
            if not ready.is_set():
                ready.set()
                print(f"{address}: streaming", flush=True)
            if start.is_set():
                stamp = frame.getTimestamp()  # on the PC's fine clock (dai.Clock), set by the camera
                # The hub's capture time. time.monotonic() moves in steps of 15.6 ms on Windows with
                # this Python, so this time does too; camera_time is the same moment without the steps.
                captured.append(time.monotonic() - (dai.Clock.now() - stamp).total_seconds())
                camera_time.append(stamp.total_seconds())
                pictures.append(frame.getData().tobytes())
    if not pictures:
        return
    path = folder / f"camera_{address}.zip"
    with zipfile.ZipFile(path, "w") as archive:  # stored, not compressed
        archive.writestr("info.json", json.dumps(details | {"captured": captured, "camera_time": camera_time}))
        for index, jpeg in enumerate(pictures):
            archive.writestr(f"{index:05d}.jpg", jpeg)
    print(f"{address}: {len(pictures)} pictures ({len(pictures) / SECONDS:.1f} per second), "
          f"{path.stat().st_size / 1e6:.0f} MB, {path.name}", flush=True)


def main():
    # Home, AppData and temp inside .\runtime (as env.bat), so nothing is written outside this folder.
    home, temp = HERE / "runtime" / "home", HERE / "runtime" / "temp"
    for name, path in {"USERPROFILE": home, "HOME": home, "APPDATA": home / "AppData" / "Roaming",
                       "LOCALAPPDATA": home / "AppData" / "Local", "TEMP": temp, "TMP": temp}.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)
    import depthai as dai

    print("Searching for the cameras...", flush=True)
    cameras = sorted((info.name, info.deviceId, info.state.name, info.protocol.name, info.platform.name)
                     for info in dai.Device.getAllConnectedDevices())
    in_use = [c[0] for c in cameras if c[2] in ("X_LINK_BOOTED", "X_LINK_BOOTED_NON_EXCLUSIVE")]
    print(f"{len(cameras)} cameras: {', '.join(c[0] for c in cameras)}", flush=True)
    if in_use:
        sys.exit(f"In use by another program: {', '.join(in_use)}. Close Moverse and the hub, then try again.")
    if not cameras:
        sys.exit("No camera found. Close Moverse and the hub (they hold the cameras), then try again.")

    folder = HERE / "recordings"
    folder.mkdir(exist_ok=True)
    (folder / ".gitignore").write_text("*\n")  # the recordings are large and local: never into Git
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

    for left in range(COUNTDOWN, 0, -1):
        print(f"Recording starts in {left} s", flush=True)
        time.sleep(1)
    start.set()
    print(f"\aRECORDING for {SECONDS} seconds: walk around", flush=True)
    time.sleep(SECONDS)
    stop.set()
    print("\aDone. Saving the files...", flush=True)
    for process, _ in workers:
        process.join()
    print(f"Saved in {folder}")


if __name__ == "__main__":
    main()
