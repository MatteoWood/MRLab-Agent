"""OAK cameras: search, connect, stream.

Every camera runs in its own helper process (camera_process, started by CameraWorker). The helper opens
the camera, which sends its colour picture at the sensor's full width (SIZE_WIDTH) and FPS pictures a
second, compressed to JPEG on the camera. That is compression only: no model runs on the cameras.
8 uncompressed pictures of this size at 60 fps would need about 7 gigabit/s; as JPEG about 0.5.
The helper passes each picture with its capture time to the hub and, while tracking runs, also the people
the pose model (hub/pose.py) finds in it, on this PC's graphics card. One helper per camera means all
cameras open at the same time (about 10 s) and are processed in parallel. In one process, opening them at
the same time crashed DepthAI (heap corruption) and one after another took 80 s (lab, 2026-11-10).
A PoE camera that was just closed restarts first, so opening is retried for up to REOPEN_WAIT seconds.
The hub keeps the newest picture of each camera as JPEG and decodes it where needed: small for the tile,
full size for vision (frontal camera) and calibration (with a short history, to find pictures that
different cameras took at the same moment).
A webcam can stand in for a camera (laptop testing of vision; no tracking, it has no calibration).
"""
import collections
import math
import multiprocessing
import os
import threading
import time

import cv2
import numpy as np

SIZE_WIDTH = 1280      # OAK-D Pro W colour sensor: 1280 x 800; the height follows the sensor's aspect
FPS = 60
JPEG_QUALITY = 90
PREVIEW_INTERVAL = 0.2  # s between tile pictures
VISION_INTERVAL = 0.2   # s between full-size pictures for vision (frontal camera)
HISTORY = 40            # pictures kept per camera (two thirds of a second at 60 fps), for calibration
# A closed PoE camera restarts and cannot be opened again for some seconds (Luxonis forum: about 10 s).
REOPEN_WAIT = 20.0
WEBCAM = "webcam"  # device id of the test webcam


class Camera:
    """One camera as shown in the window; filled by its CameraWorker."""

    def __init__(self, device_id, address, state, info=None):
        self.device_id, self.address, self.state = device_id, address, state
        self.info = info      # how to reach it: search result fields (picklable), None for the webcam
        self.status = "found" if state != "in use" else "in use by another program"
        self.product = ""
        self.lens = None      # {"size": (w, h), "matrix": 3x3, "distortion": [...], "fisheye": bool}
        self.preview = None   # small BGR image
        self.fps = 0.0
        self.pose_ms = None   # pose model time per picture in the helper, while tracking
        self.latest = None    # (jpeg bytes, capture time)
        self.history = collections.deque(maxlen=HISTORY)  # (capture time, jpeg bytes)
        self.vision = None    # vision.FrameStore while this is the frontal camera
        self.on_people = None  # tracker: called with (camera, capture time, people) for every picture
        self.worker = None


def search(include_webcam=False):
    """(cameras this PC can reach, error text or ""); takes a few seconds."""
    cameras, error = [], ""
    try:
        import depthai as dai

        for info in dai.Device.getAllConnectedDevices():
            in_use = info.state in (dai.XLinkDeviceState.X_LINK_BOOTED, dai.XLinkDeviceState.X_LINK_BOOTED_NON_EXCLUSIVE)
            fields = (info.name, info.deviceId, info.state.name, info.protocol.name, info.platform.name)
            cameras.append(Camera(info.deviceId or info.name, info.name, "in use" if in_use else "available", fields))
    except Exception as failure:  # DepthAI missing or the network search failed: shown in the log
        error = str(failure)
    if include_webcam:
        cameras.append(Camera(WEBCAM, "this PC", "available"))
    return cameras, error


# ---------- helper process ----------

def camera_process(info, conn, stop):
    """Runs in its own process: open the camera, send its pictures to conn until stop is set.

    To the hub: ("status", text), ("log", text), ("info", lens and product), ("picture", capture time,
    jpeg, people or None, pose ms), ("error", text). From the hub: ("pose", device name or None) starts or
    stops the pose model ("graphics card (DirectML)" or "processor", as hub/pose.py names them)."""
    cv2.setNumThreads(1)  # 8 helpers with one OpenCV thread per processor core each would fight over the cores
    try:
        import depthai as dai

        start = time.monotonic()
        device = open_device(dai, info, conn, stop)
        if device is None:
            return
        opened = time.monotonic()
        with dai.Pipeline(device) as pipeline:
            socket = dai.CameraBoardSocket.CAM_A
            sensor = next(f for f in device.getConnectedCameraFeatures() if f.socket == socket)
            size = (SIZE_WIDTH, round(SIZE_WIDTH * sensor.height / sensor.width / 16) * 16)
            color = pipeline.create(dai.node.Camera).build(socket)
            output = color.requestOutput(size, dai.ImgFrame.Type.NV12, fps=FPS)
            encoder = pipeline.create(dai.node.VideoEncoder).build(
                output, frameRate=FPS, profile=dai.VideoEncoderProperties.Profile.MJPEG, quality=JPEG_QUALITY)
            queue = encoder.out.createOutputQueue(maxSize=2, blocking=False)
            calibration = device.readCalibration()
            conn.send(("info", {
                "product": device.getProductName(), "sensor": sensor.sensorName, "size": size,
                "matrix": calibration.getCameraIntrinsics(socket, *size),
                "distortion": calibration.getDistortionCoefficients(socket),
                "fisheye": calibration.getDistortionModel(socket).name == "Fisheye",
            }))
            pipeline.start()
            started = time.monotonic()
            model, first = None, True
            while not stop.is_set() and pipeline.isRunning():
                while conn.poll():
                    _, device_name = conn.recv()  # ("pose", device name or None)
                    model = load_pose(device_name, conn) if device_name else None
                frame = queue.tryGet()
                if frame is None:
                    time.sleep(0.001)
                    continue
                while (newer := queue.tryGet()) is not None:  # the newest picture: no delay piling up when the
                    frame = newer                             # pose model is slower than the camera
                captured = time.monotonic() - (dai.Clock.now() - frame.getTimestamp()).total_seconds()
                jpeg = frame.getData().tobytes()
                if first:
                    conn.send(("log", f"opened in {opened - start:.1f} s, pipeline started in {started - opened:.1f} s, "
                                      f"first picture after {time.monotonic() - start:.1f} s ({size[0]}x{size[1]}, "
                                      f"{device.getProductName()}, {sensor.sensorName})"))
                    first = False
                people, pose_ms = None, None
                if model is not None:
                    begin = time.perf_counter()
                    people = find_people(model, jpeg)
                    pose_ms = (time.perf_counter() - begin) * 1000
                conn.send(("picture", captured, jpeg, people, pose_ms))
    except (EOFError, BrokenPipeError):
        return  # the hub closed
    except Exception as error:  # unreachable, in use, unplugged, or a setting the camera refused
        try:
            conn.send(("error", str(error)))
        except OSError:
            pass


def open_device(dai, info, conn, stop):
    """The camera with the details from the search; a camera that was just closed restarts first, so
    retry (by address only, as its state may have changed) for up to REOPEN_WAIT seconds."""
    name, device_id, state, protocol, platform = info
    try:
        target = dai.DeviceInfo(name, device_id, dai.XLinkDeviceState.__members__[state],
                                dai.XLinkProtocol.__members__[protocol], dai.XLinkPlatform.__members__[platform],
                                dai.XLinkError_t.X_LINK_SUCCESS)
    except (KeyError, AttributeError, TypeError):
        target = dai.DeviceInfo(name)
    deadline = time.monotonic() + REOPEN_WAIT
    while not stop.is_set():
        try:
            return dai.Device(target)
        except RuntimeError as error:
            if time.monotonic() > deadline:
                raise
            conn.send(("status", "camera restarting, retrying"))
            conn.send(("log", f"not ready ({error}), retrying"))
            target = dai.DeviceInfo(name)
            time.sleep(1.0)
    return None


def load_pose(device_name, conn):
    from hub import pose

    try:
        return pose.PoseModel(lambda text: conn.send(("log", text)), device=device_name, threads=max(1, (os.cpu_count() or 8) // 8))
    except Exception as error:  # model file or runtime missing: no people from this camera
        conn.send(("log", f"pose model not available: {error}"))
        return None


def find_people(model, jpeg):
    """People in the picture: [(box, points (17, 3), score)] in full-size pixels. The model works at 640
    across, so the picture is decoded at half size (the JPEG decoder does that directly, which is faster)."""
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_REDUCED_COLOR_2)
    found = []
    for person in model(image):
        points = person["points"].astype(np.float32)
        points[:, :2] *= 2
        found.append((tuple(2 * v for v in person["box"]), points, person["score"]))
    return found


# ---------- in the hub ----------

class CameraWorker(threading.Thread):
    """Starts a camera's helper process and receives its pictures (one thread per camera)."""

    def __init__(self, camera, log=print):
        super().__init__(daemon=True)
        self.camera, self.log = camera, log
        self.running = True
        self.conn, child = multiprocessing.Pipe()
        self.stop_event = multiprocessing.Event()
        self.process = multiprocessing.Process(target=camera_process, args=(camera.info, child, self.stop_event), daemon=True)

    def pose(self, device_name):
        """Start (device name) or stop (None) the pose model in the helper."""
        try:
            self.conn.send(("pose", device_name))
        except OSError:
            pass

    def run(self):
        cam = self.camera
        cam.status = "starting"
        self.process.start()
        times, last_preview, last_vision = [], 0.0, 0.0
        try:
            while self.running:
                if not self.conn.poll(0.25):
                    if not self.process.is_alive():
                        if not cam.status.startswith("error"):
                            cam.status = "error: the camera's helper program stopped"
                        break
                    continue
                message = self.conn.recv()
                kind = message[0]
                if kind == "picture":
                    _, captured, jpeg, people, pose_ms = message
                    now = time.monotonic()
                    cam.latest = (jpeg, captured)
                    cam.history.append((captured, jpeg))
                    cam.pose_ms = pose_ms
                    times[:] = [t for t in times if now - t < 1.0] + [now]
                    cam.fps = len(times)
                    cam.status = "streaming"
                    if now - last_preview >= PREVIEW_INTERVAL:
                        cam.preview = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_REDUCED_COLOR_4)
                        last_preview = now
                    store = cam.vision
                    if store is not None and now - last_vision >= VISION_INTERVAL:
                        store.publish(cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR), captured)
                        last_vision = now
                    if people is not None and cam.on_people is not None:
                        cam.on_people(cam, captured, people)
                elif kind == "info":
                    info = message[1]
                    cam.product = f"{info['product']} ({info['sensor']})"
                    cam.lens = {k: info[k] for k in ("size", "matrix", "distortion", "fisheye")}
                elif kind == "status":
                    cam.status = message[1]
                elif kind == "log":
                    self.log(f"camera {cam.device_id}: {message[1]}")
                elif kind == "error":
                    cam.status = f"error: {message[1]}"
                    self.log(f"camera {cam.device_id}: {message[1]}")
        except (EOFError, OSError) as error:
            cam.status = f"error: {error}"
        finally:
            self.stop_event.set()
            deadline = time.monotonic() + 5.0
            while self.process.is_alive() and time.monotonic() < deadline:
                try:  # keep reading, or the helper waits forever to hand over its last picture
                    if self.conn.poll(0.05):
                        self.conn.recv()
                except (EOFError, OSError):
                    break
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.terminate()
            cam.fps = 0.0
            if not cam.status.startswith("error"):
                cam.status = "disconnected"


class WebcamWorker(threading.Thread):
    """A webcam as a camera, for testing vision on the laptop (no tracking: it has no calibration)."""

    def __init__(self, camera, log=print):
        super().__init__(daemon=True)
        self.camera, self.log = camera, log
        self.running = True

    def pose(self, device_name):
        pass

    def run(self):
        cam = self.camera
        capture = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cam.product = "webcam (test)"
        times = []
        try:
            while self.running:
                ok, image = capture.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                now = time.monotonic()
                h, w = image.shape[:2]
                if cam.lens is None:
                    f = (w / 2) / math.tan(math.radians(35.0))  # assumed 70 degrees across
                    cam.lens = {"size": (w, h), "matrix": [[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], "distortion": [], "fisheye": False}
                jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])[1].tobytes()
                cam.latest = (jpeg, now)
                cam.history.append((now, jpeg))
                cam.preview = cv2.resize(image, (320, 320 * h // w))
                if cam.vision is not None:
                    cam.vision.publish(image, now)
                times[:] = [t for t in times if now - t < 1.0] + [now]
                cam.fps = len(times)
                cam.status = "streaming"
        finally:
            capture.release()
            cam.fps = 0.0
            cam.status = "disconnected"
