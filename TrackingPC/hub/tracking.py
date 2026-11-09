"""Fast head tracker (Step 8B, first version, not tested with an OAK camera yet).

The frontal camera's colour frames go through a face detector (OpenCV's built-in Haar cascade; no model
download needed). The distance to the face comes from the camera's stereo depth at the face, or, where
depth has no value, from the face width (a face is about FACE_WIDTH_MM wide). The point between the eyes
in camera space is moved into the tracking space NDC_Basic uses (cm; X towards the wall, Y to the right
seen facing the wall, Z height above the floor) with the camera pose from the settings, smoothed with a
One Euro filter, and sent to the Unreal PC in Moverse's packet format (subject Actor0, 25 moverserig
bones, head at the point), so the Moverse Live Link plugin, NDC_Basic and the gaze work unchanged.
When no face is seen for LOST_AFTER seconds nothing is sent, so the subject turns Unresponsive.
Moverse must not run at the same time (two senders on one port).
"""
import json
import math
import socket
import threading
import time

import cv2
import numpy as np

FACE_WIDTH_MM = 160.0
LOST_AFTER = 0.5
SUBJECT = "Actor0"

# Moverse rig (from /Game/Actor0/asset): name, parent index, location relative to the parent.
# Rig axes: X to the person's left, Y down, Z forward. Bone rotations are identity in this pose.
BONES = [
    ("moverserig_Pivot", -1, (0.0, 0.0, 0.0)),
    ("moverserig_Pelvis", 0, (-0.2328, -95.3471, 2.9980)),
    ("moverserig_LeftHip", 1, (5.9682, 8.3540, -1.6647)),
    ("moverserig_LeftKnee", 2, (4.1132, 37.6328, 0.8016)),
    ("moverserig_LeftAnkle", 3, (-1.5142, 41.6523, -3.8239)),
    ("moverserig_LeftFoot", 4, (3.8980, 5.9398, 12.1897)),
    ("moverserig_RightHip", 1, (-6.1412, 9.1789, -1.2318)),
    ("moverserig_RightKnee", 6, (-4.1145, 37.4555, -0.4463)),
    ("moverserig_RightAnkle", 7, (1.9105, 40.9963, -3.5354)),
    ("moverserig_RightFoot", 8, (-3.4666, 6.0737, 13.0106)),
    ("moverserig_Spine1", 1, (0.4320, -12.7213, -4.0101)),
    ("moverserig_Spine2", 10, (0.5017, -14.2736, 2.7621)),
    ("moverserig_Spine3", 11, (-0.2279, -5.8120, 0.3739)),
    ("moverserig_Neck", 12, (-1.3269, -21.4987, -3.6790)),
    ("moverserig_Head", 13, (1.0031, -8.8843, 5.0896)),
    ("moverserig_LeftCollar", 12, (7.2478, -11.5423, -2.0013)),
    ("moverserig_LeftShoulder", 15, (12.4563, -4.4473, -2.0196)),
    ("moverserig_LeftElbow", 16, (25.0649, 1.4353, -2.3049)),
    ("moverserig_LeftWrist", 17, (26.1919, -1.2614, -0.6985)),
    ("moverserig_LeftHand", 18, (8.6448, 1.0644, -1.5423)),
    ("moverserig_RightCollar", 12, (-8.3918, -11.3703, -2.5034)),
    ("moverserig_RightShoulder", 20, (-11.4825, -4.5847, -0.9397)),
    ("moverserig_RightElbow", 21, (-25.5946, 1.2095, -3.1986)),
    ("moverserig_RightWrist", 22, (-26.4602, -0.5962, -0.5802)),
    ("moverserig_RightHand", 23, (-8.8685, 0.8668, -0.9961)),
]
HEAD = 14
# The plugin turns the root rotation by +90 degrees about X; sending the inverse keeps the body upright.
ROOT_ROTATION = [-math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5)]
IDENTITY = [0.0, 0.0, 0.0, 1.0]
ONE = [1.0, 1.0, 1.0]


def head_offset():
    """Head location relative to the root bone, in rig axes."""
    x = y = z = 0.0
    i = HEAD
    while i > 0:
        dx, dy, dz = BONES[i][2]
        x, y, z = x + dx, y + dy, z + dz
        i = BONES[i][1]
    return x, y, z


def subject_packet():
    bones = [{"Name": name, "Parent": parent} for name, parent, _ in BONES]
    return json.dumps({SUBJECT: [{"Type": "CharacterSubject"}] + bones}, separators=(",", ":")).encode()


def frame_packet(head, offset):
    # NDC_Basic maps the head's rig location (x, y, z) to tracking (z, -x, -y); this is the inverse.
    hx, hy, hz = head
    root = [round(-hy - offset[0], 4), round(-hz - offset[1], 4), round(hx - offset[2], 4)]
    bones = [{"Location": root, "Rotation": ROOT_ROTATION, "Scale": ONE}]
    bones += [{"Location": list(loc), "Rotation": IDENTITY, "Scale": ONE} for _, _, loc in BONES[1:]]
    return json.dumps({SUBJECT: [{"Type": "CharacterAnimation"}] + bones}, separators=(",", ":")).encode()


def camera_rotation(yaw, pitch, roll):
    """Camera axes (x right, y down, z forward in the image) to tracking axes, angles in degrees.

    With all angles 0 the camera looks straight away from the wall (-X), level. pitch > 0 tilts it down,
    yaw > 0 turns it towards +Y, roll > 0 turns the image clockwise as seen from behind the camera.
    """
    y, p, r = (math.radians(a) for a in (yaw, pitch, roll))
    base = np.array([[0, 0, -1], [-1, 0, 0], [0, -1, 0]], float)  # columns: camera x, y, z in tracking axes
    tilt = np.array([[1, 0, 0], [0, math.cos(p), math.sin(p)], [0, -math.sin(p), math.cos(p)]])
    turn = np.array([[math.cos(-y), -math.sin(-y), 0], [math.sin(-y), math.cos(-y), 0], [0, 0, 1]])
    spin = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    return turn @ base @ tilt @ spin


class OneEuro:
    """One Euro filter (Casiez et al. 2012) on a 3D point: smooth when still, little lag when moving."""

    def __init__(self, min_cutoff, beta, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = self.dx = self.t = None

    @staticmethod
    def alpha(dt, cutoff):
        return 1.0 / (1.0 + 1.0 / (2.0 * math.pi * cutoff * dt))

    def __call__(self, x, t):
        if self.t is None or t <= self.t:
            self.x, self.dx, self.t = x, np.zeros(3), t
            return x
        dt = t - self.t
        dx = (x - self.x) / dt
        a_d = self.alpha(dt, self.d_cutoff)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        cutoff = self.min_cutoff + self.beta * np.linalg.norm(self.dx)
        a = self.alpha(dt, cutoff)
        self.x, self.t = a * x + (1 - a) * self.x, t
        return self.x


class FrontalFrames:
    """Newest colour frame and depth frame of the frontal camera, with the colour camera's intrinsics."""

    def __init__(self):
        self.lock = threading.Lock()
        self.color = None  # (BGR image, capture time)
        self.depth = None  # (uint16 depth in mm aligned to the colour image, any size with the same aspect)
        self.intrinsics = None  # (fx, fy, cx, cy) at the colour image size
        self.seq = 0

    def publish(self, color, captured, depth=None):
        with self.lock:
            self.color, self.depth, self.seq = (color, captured), depth, self.seq + 1


class Tracker(threading.Thread):
    def __init__(self, frames, settings, log=print):
        super().__init__(daemon=True)
        self.frames, self.settings, self.log = frames, settings, log
        self.running = True
        self.detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        # Shown in the window:
        self.face = None       # (x, y, w, h) in the colour image, or None
        self.position = None   # filtered head position in tracking space (cm)
        self.distance_from = ""  # "depth" or "face size"
        self.rate = 0.0        # tracked frames per second
        self.sent = 0

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s = self.settings
        address = (s["unreal_address"], int(s["moverse_port"]))
        rotation = camera_rotation(s["camera_yaw"], s["camera_pitch"], s["camera_roll"])
        translation = np.array([s["camera_x"], s["camera_y"], s["camera_z"]], float)
        smooth = OneEuro(s["filter_min_cutoff"], s["filter_beta"])
        offset, subject = head_offset(), subject_packet()
        last_seq, last_seen, last_subject, times = 0, 0.0, 0.0, []
        while self.running:
            with self.frames.lock:
                seq, color, depth, intrinsics = self.frames.seq, self.frames.color, self.frames.depth, self.frames.intrinsics
            if seq == last_seq or color is None or intrinsics is None:
                time.sleep(0.005)
                continue
            last_seq = seq
            image, captured = color
            point = self.locate(image, depth, intrinsics)
            now = time.monotonic()
            if point is None:
                if now - last_seen > LOST_AFTER:
                    self.position, self.face = None, None
                    smooth.t = None  # start fresh when the face comes back
                continue
            last_seen = now
            head = smooth(translation + rotation @ (point / 10.0), captured)  # mm to cm
            self.position = head
            times = [t for t in times if now - t < 1.0] + [now]
            self.rate = len(times)
            try:
                if now - last_subject > 1.0:  # sent every second, so Unreal can start at any time
                    sock.sendto(subject, address)
                    last_subject = now
                sock.sendto(frame_packet(head, offset), address)
                self.sent += 1
            except OSError as error:
                self.log(f"tracking: send failed: {error}")
                time.sleep(0.5)

    def locate(self, image, depth, intrinsics):
        """Point between the eyes of the largest face, in camera space (mm), or None."""
        grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = self.detector.detectMultiScale(grey, scaleFactor=1.1, minNeighbors=5, minSize=(20, 20))
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        self.face = (int(x), int(y), int(w), int(h))
        fx, fy, cx, cy = intrinsics
        u, v = x + w / 2.0, y + 0.4 * h  # the eyes sit a bit above the middle of the face box
        z = None
        if depth is not None:
            sx, sy = depth.shape[1] / image.shape[1], depth.shape[0] / image.shape[0]
            patch = depth[int((y + 0.25 * h) * sy):int((y + 0.75 * h) * sy), int((x + 0.25 * w) * sx):int((x + 0.75 * w) * sx)]
            valid = patch[patch > 0]
            if valid.size > 10:
                z = float(np.median(valid))
                self.distance_from = "depth"
        if z is None:
            z = fx * FACE_WIDTH_MM / w
            self.distance_from = "face size"
        return np.array([(u - cx) * z / fx, (v - cy) * z / fy, z])
