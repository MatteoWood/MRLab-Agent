"""Stand-in for DepthAI (testing only, tools/live_test.py) that plays a recording (FAKE_RECORDING_DIR, one
zip per camera from record_cameras.py) as the cameras, at 60 fps, in a loop. Only what hub/cameras.py and
record_cameras.py use. The pictures stay in memory."""
import datetime
import glob
import json
import os
import time
import zipfile
from types import SimpleNamespace

import numpy as np

RECORDINGS = {}
for path in glob.glob(os.path.join(os.environ.get("FAKE_RECORDING_DIR", ""), "*.zip")):
    info = json.loads(zipfile.ZipFile(path).read("info.json"))
    RECORDINGS[info["address"]] = (path, info)


class _Value:
    def __init__(self, name):
        self.name = name


def _enum(*names):
    members = {n: _Value(n) for n in names}
    return type("Enum", (), {**members, "__members__": members})


XLinkDeviceState = _enum("X_LINK_BOOTLOADER", "X_LINK_BOOTED", "X_LINK_BOOTED_NON_EXCLUSIVE", "X_LINK_UNBOOTED")
XLinkProtocol = _enum("X_LINK_TCP_IP")
XLinkPlatform = _enum("X_LINK_MYRIAD_X")
XLinkError_t = _enum("X_LINK_SUCCESS")
CameraBoardSocket = _enum("CAM_A")
ImgFrame = SimpleNamespace(Type=_enum("NV12"))
VideoEncoderProperties = SimpleNamespace(Profile=_enum("MJPEG"))


class DeviceInfo:
    def __init__(self, name, deviceId="", state=None, protocol=None, platform=None, status=None):
        self.name = name
        self.deviceId = deviceId or RECORDINGS[name][1]["device_id"]
        self.state = state or XLinkDeviceState.X_LINK_BOOTLOADER
        self.protocol, self.platform = XLinkProtocol.X_LINK_TCP_IP, XLinkPlatform.X_LINK_MYRIAD_X


class Clock:
    @staticmethod
    def now():
        return datetime.timedelta(seconds=time.perf_counter())


class Device:
    @staticmethod
    def getAllConnectedDevices():
        return [DeviceInfo(address) for address in RECORDINGS]

    def __init__(self, info):
        self.path, self.info = RECORDINGS[info.name]

    def getProductName(self):
        return self.info["product"]

    def getConnectedCameraFeatures(self):
        return [SimpleNamespace(socket=CameraBoardSocket.CAM_A, width=4056, height=3040, sensorName=self.info["sensor"])]

    def readCalibration(self):
        return SimpleNamespace(getCameraIntrinsics=lambda socket, w, h: self.info["matrix"],
                               getDistortionCoefficients=lambda socket: self.info["distortion"],
                               getDistortionModel=lambda socket: _Value("Fisheye" if self.info["fisheye"] else "Perspective"))


class _Queue:
    def __init__(self, path, fps):
        z = zipfile.ZipFile(path)
        names = sorted(n for n in z.namelist() if n.endswith(".jpg"))
        self.pictures = [np.frombuffer(z.read(n), np.uint8) for n in names]
        self.interval, self.start, self.last = 1.0 / fps, None, -1

    def tryGet(self):
        now = time.perf_counter()
        if self.start is None:
            self.start = now
        index = int((now - self.start) / self.interval)
        if index == self.last:
            return None
        self.last = index
        jpeg = self.pictures[index % len(self.pictures)]
        taken = self.start + index * self.interval
        return SimpleNamespace(getTimestamp=lambda: datetime.timedelta(seconds=taken), getData=lambda: jpeg)


class _Camera:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    def build(self, socket):
        return self

    def requestOutput(self, size, type=None, fps=30):
        return SimpleNamespace(fps=fps)


class _Encoder:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    def build(self, output, frameRate=30, profile=None, quality=80):
        path = self.pipeline.device.path
        self.out = SimpleNamespace(createOutputQueue=lambda maxSize=1, blocking=False: _Queue(path, frameRate))
        return self


node = SimpleNamespace(Camera=_Camera, VideoEncoder=_Encoder)


class Pipeline:
    def __init__(self, device):
        self.device = device

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def create(self, kind):
        return kind(self)

    def start(self):
        pass

    def isRunning(self):
        return True
