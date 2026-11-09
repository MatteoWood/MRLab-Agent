"""OAK cameras: search, connect, stream.

Each connected camera runs in its own thread with a temporary pipeline in the camera's memory (as every
DepthAI program does); nothing is flashed or saved on the camera. Every camera sends a small colour
preview (PREVIEW at PREVIEW_FPS). The frontal camera also sends colour at FRONTAL_SIZE (for vision and
the window) and runs the pose model (YOLOv8 nano pose, 17 body points, from Luxonis' model zoo, in
runtime/oak_models) on its own chip at TRACK_FPS, together with its stereo depth: for every person it
sends the points with their distance (SpatialDetectionNetwork), and heads() turns them into one 3D
head point per person. A webcam can stand in for the frontal camera (laptop testing, no pose model).
"""
import math
import pathlib
import threading
import time

import cv2
import numpy as np

PREVIEW = (320, 200)
PREVIEW_FPS = 5
FRONTAL_SIZE = (1280, 720)  # 16:9 like the pose model's input, so both crop the same part of the image
FRONTAL_FPS = 15
TRACK_FPS = 30              # pose model and depth; Luxonis measured 33 inferences/s for this model on RVC2
DEPTH_SIZE = (640, 400)
WEBCAM = "webcam"  # device id of the test webcam
POSE_MODELS = pathlib.Path(__file__).resolve().parent.parent / "runtime" / "oak_models"
# COCO body points of the pose model: 0 nose, 1 left eye, 2 right eye, 3 left ear, 4 right ear, ...
NOSE, LEFT_EYE, RIGHT_EYE, LEFT_EAR, RIGHT_EAR = range(5)
MIN_POINT_CONFIDENCE = 0.5


def pose_model():
    """The pose model archive for the OAK chip (RVC2) in runtime/oak_models, or None."""
    found = sorted(POSE_MODELS.glob("*/yolov8n-pose.rvc2.tar.xz"))
    return found[0] if found else None


def heads(message):
    """One head point per person from the pose model's message: camera space in mm (x right, y down,
    z forward), plus the person box and the head point as fractions of the image (for drawing).

    The head is the middle of the eyes, else the nose, else the middle of the ears. Its distance is the
    median depth the camera measured at those points (else at the person box); x and y come from the
    point's pixel position and the frame's intrinsics, so they do not depend on the sign convention of
    DepthAI's spatial coordinates (not documented for v3)."""
    transformation = message.getTransformation()
    width, height = transformation.getSize()
    k = np.array(transformation.getIntrinsicMatrix(), float)
    fx, fy, cx, cy = k[0][0], k[1][1], k[0][2], k[1][2]
    found = []
    for detection in message.detections:
        points = detection.getKeypoints()

        def good(i):
            return i < len(points) and points[i].confidence >= MIN_POINT_CONFIDENCE

        for group in ((LEFT_EYE, RIGHT_EYE), (NOSE,), (LEFT_EAR, RIGHT_EAR)):
            if all(good(i) for i in group):
                chosen = [points[i] for i in group]
                break
        else:
            continue  # no head point seen for this person
        u = sum(p.imageCoordinates.x for p in chosen) / len(chosen)
        v = sum(p.imageCoordinates.y for p in chosen) / len(chosen)
        if u <= 1.5 and v <= 1.5:  # fractions of the image, not pixels
            u, v = u * width, v * height
        depths = [p.spatialCoordinates.z for p in chosen if p.spatialCoordinates.z > 0]
        z = float(np.median(depths)) if depths else float(detection.spatialCoordinates.z)
        if z <= 0:
            continue  # no depth at this person
        found.append({
            "point": np.array([(u - cx) * z / fx, (v - cy) * z / fy, z]),
            "box": (detection.xmin, detection.ymin, detection.xmax, detection.ymax),
            "head": (u / width, v / height),
            "confidence": detection.confidence,
        })
    return found


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
            people_queue = None
            if frontal:
                model = pose_model()
                if model is not None:
                    # The network links the depth to its own input frame itself (as in Luxonis' spatial example).
                    depth = pipeline.create(dai.node.StereoDepth).build(autoCreateCameras=True, size=DEPTH_SIZE, fps=TRACK_FPS)
                    network = pipeline.create(dai.node.SpatialDetectionNetwork).build(color, depth, dai.NNArchive(str(model)), fps=TRACK_FPS)
                    network.setDepthLowerThreshold(300)   # mm
                    network.setDepthUpperThreshold(8000)
                    people_queue = network.out.createOutputQueue(maxSize=1, blocking=False)
                else:
                    self.log("pose model missing in runtime/oak_models: tracking uses the face detector on this PC")
                color_queue = color.requestOutput(FRONTAL_SIZE, dai.ImgFrame.Type.NV12, fps=FRONTAL_FPS).createOutputQueue(maxSize=1, blocking=False)
                m = device.readCalibration().getCameraIntrinsics(dai.CameraBoardSocket.CAM_A, *FRONTAL_SIZE)
                self.frontal.intrinsics = (m[0][0], m[1][1], m[0][2], m[1][2])
            else:
                color_queue = color.requestOutput(PREVIEW, dai.ImgFrame.Type.NV12, fps=PREVIEW_FPS).createOutputQueue(maxSize=1, blocking=False)
            pipeline.start()
            times = []
            while self.running and pipeline.isRunning():
                busy = False
                if people_queue is not None:
                    message = people_queue.tryGet()
                    if message is not None:
                        age = (dai.Clock.now() - message.getTimestamp()).total_seconds()
                        self.frontal.publish_people(heads(message), time.monotonic() - age)
                        busy = True
                frame = color_queue.tryGet()
                if frame is not None:
                    age = (dai.Clock.now() - frame.getTimestamp()).total_seconds()
                    self.deliver(frame.getCvFrame(), time.monotonic() - age, None, times)
                    busy = True
                if not busy:
                    time.sleep(0.003)

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
