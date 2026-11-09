"""OAK cameras: search, connect, stream.

Each connected camera runs in its own thread with a temporary pipeline in the camera's memory (as every
DepthAI program does); nothing is flashed or saved on the camera. Every camera sends a small colour
preview (PREVIEW at PREVIEW_FPS); the frontal camera also sends colour at FRONTAL_SIZE and stereo depth
aligned to it, for tracking and vision. A webcam can stand in for the frontal camera (laptop testing).
"""
import math
import threading
import time

import cv2

PREVIEW = (320, 200)
PREVIEW_FPS = 5
FRONTAL_SIZE = (1280, 800)
FRONTAL_FPS = 15
DEPTH_SIZE = (640, 400)
WEBCAM = "webcam"  # device id of the test webcam


class Camera:
    """One camera as shown in the window."""

    def __init__(self, device_id, address, state):
        self.device_id, self.address, self.state = device_id, address, state
        self.status = "found" if state != "in use" else "in use by another program"
        self.preview = None  # small BGR image
        self.fps = 0.0
        self.product = ""
        self.worker = None


def search(include_webcam=False):
    """(cameras this PC can reach, error text or ""); takes a few seconds."""
    cameras, error = [], ""
    try:
        import depthai as dai

        for info in dai.Device.getAllConnectedDevices():
            in_use = info.state in (dai.XLinkDeviceState.X_LINK_BOOTED, dai.XLinkDeviceState.X_LINK_BOOTED_NON_EXCLUSIVE)
            cameras.append(Camera(info.deviceId or info.name, info.name, "in use" if in_use else "available"))
    except Exception as failure:  # DepthAI missing or the network search failed: shown in the log
        error = str(failure)
    if include_webcam:
        cameras.append(Camera(WEBCAM, "this PC", "available"))
    return cameras, error


class CameraWorker(threading.Thread):
    def __init__(self, camera, frontal_frames=None, vision_store=None, log=print):
        super().__init__(daemon=True)
        self.camera, self.frontal, self.vision, self.log = camera, frontal_frames, vision_store, log
        self.running = True

    def run(self):
        cam = self.camera
        cam.status = "connecting"
        try:
            if cam.device_id == WEBCAM:
                self.run_webcam()
            else:
                self.run_oak()
        except Exception as error:  # unreachable, in use or unplugged: show it on the tile
            cam.status = f"error: {error}"
            self.log(f"camera {cam.device_id}: {error}")
            return
        cam.status = "disconnected"
        cam.fps = 0.0

    def deliver(self, image, captured, depth=None, times=None):
        cam = self.camera
        cam.preview = cv2.resize(image, PREVIEW)
        if self.frontal is not None:
            self.frontal.publish(image, captured, depth)
        if self.vision is not None:
            self.vision.publish(image, captured)
        now = time.monotonic()
        times[:] = [t for t in times if now - t < 1.0] + [now]
        cam.fps = len(times)
        cam.status = "streaming"

    def run_oak(self):
        import depthai as dai

        cam, frontal = self.camera, self.frontal is not None
        with dai.Pipeline(dai.Device(dai.DeviceInfo(cam.address))) as pipeline:
            device = pipeline.getDefaultDevice()
            cam.product = device.getProductName()
            color = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
            if frontal:
                color_queue = color.requestOutput(FRONTAL_SIZE, dai.ImgFrame.Type.NV12, fps=FRONTAL_FPS).createOutputQueue(maxSize=1, blocking=False)
                stereo = pipeline.create(dai.node.StereoDepth).build(autoCreateCameras=True, size=DEPTH_SIZE, fps=FRONTAL_FPS)
                stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)
                stereo.setOutputSize(*DEPTH_SIZE)
                depth_queue = stereo.depth.createOutputQueue(maxSize=1, blocking=False)
                m = device.readCalibration().getCameraIntrinsics(dai.CameraBoardSocket.CAM_A, *FRONTAL_SIZE)
                self.frontal.intrinsics = (m[0][0], m[1][1], m[0][2], m[1][2])
            else:
                color_queue = color.requestOutput(PREVIEW, dai.ImgFrame.Type.NV12, fps=PREVIEW_FPS).createOutputQueue(maxSize=1, blocking=False)
                depth_queue = None
            pipeline.start()
            times, depth = [], None
            while self.running and pipeline.isRunning():
                if depth_queue is not None:
                    message = depth_queue.tryGet()
                    if message is not None:
                        depth = message.getFrame()
                frame = color_queue.tryGet()
                if frame is None:
                    time.sleep(0.005)
                    continue
                age = (dai.Clock.now() - frame.getTimestamp()).total_seconds()
                self.deliver(frame.getCvFrame(), time.monotonic() - age, depth, times)

    def run_webcam(self):
        capture = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.camera.product = "webcam (test)"
        times = []
        try:
            while self.running:
                ok, image = capture.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                if self.frontal is not None and self.frontal.intrinsics is None:
                    w, h = image.shape[1], image.shape[0]
                    f = (w / 2) / math.tan(math.radians(35.0))  # assumed 70 degrees across; a webcam has no calibration
                    self.frontal.intrinsics = (f, f, w / 2, h / 2)
                self.deliver(image, time.monotonic(), None, times)
        finally:
            capture.release()
