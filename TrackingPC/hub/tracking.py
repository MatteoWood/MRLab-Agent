"""Fast head tracker (Step 8B, first version, not tested with an OAK camera yet).

The frontal camera only delivers pictures: colour, and stereo depth aligned to the colour picture.
Everything else runs here on the tracking PC: the pose model (YOLO11 nano pose, hub/pose.py, on the
graphics card or the processor, whichever is faster) finds the people and their body points; the head
point is the middle of the eyes (else the nose, else the ears); its distance is the median depth around
that point, or, without depth (webcam test), estimated from the eye distance (about EYE_DISTANCE_MM).
The point in camera space is moved into the tracking space NDC_Basic uses (cm; X towards the wall, Y to
the right seen facing the wall, Z height above the floor) with the camera pose from the settings,
smoothed with a One Euro filter, and sent to the Unreal PC in Moverse's packet format (subject Actor0,
25 moverserig bones, head at the point), so the Moverse Live Link plugin, NDC_Basic and the gaze work
unchanged. When nobody is seen for LOST_AFTER seconds nothing is sent, so the subject turns Unresponsive.
Moverse must not run at the same time (two senders on one port).

Several people: every visible person gets a number that follows them from frame to frame (nearest head
point). Only the main person's head is sent. The main person is the one clicked in the hub's window;
without a click (or when the clicked person has been gone for KEEP_CHOSEN seconds) it is the person
nearest to the camera, kept while visible.
"""
import json
import math
import socket
import threading
import time

import numpy as np

from hub import pose

EYE_DISTANCE_MM = 63.0
MIN_POINT_CONFIDENCE = 0.5
LOST_AFTER = 0.5
MATCH_DISTANCE = 0.1  # a head moves less than this (fraction of the image) between two frames
FORGET_AFTER = 2.0    # seconds a person may be unseen and keep their number
KEEP_CHOSEN = 2.0     # seconds the clicked main person may be unseen before the nearest is followed again
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
    """Newest colour frame of the frontal camera, its depth and the colour camera's intrinsics."""

    def __init__(self):
        self.lock = threading.Lock()
        self.color = None  # (BGR image, capture time)
        self.depth = None  # uint16 depth in mm aligned to the colour image (any size, same aspect), or None
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
        self.model = None
        self.tracks = {}       # number -> person (also people unseen for up to FORGET_AFTER seconds)
        self.next_number = 1
        self.main_seen = 0.0   # when the main person was last seen
        # Shown in the window (read by the window's thread):
        self.status = "loading the pose model"
        self.people = []       # people seen in the newest frame: number, point (camera mm), box and head
                               # (fractions of the colour image), source of the distance
        self.main = None       # number of the main person, whose head is sent
        self.chosen = False    # main person chosen by a click (else: automatic, the nearest)
        self.position = None   # filtered head position of the main person in tracking space (cm)
        self.distance_from = ""  # how the main person's distance was found
        self.rate = 0.0        # tracked frames per second
        self.sent = 0

    def select(self, x, y):
        """Make the person under (x, y) (fractions of the colour image) the main person; their number or None."""
        hits = [p for p in self.people if p["box"][0] <= x <= p["box"][2] and p["box"][1] <= y <= p["box"][3]]
        if not hits:
            return None
        person = min(hits, key=lambda p: (p["box"][2] - p["box"][0]) * (p["box"][3] - p["box"][1]))
        self.main, self.chosen, self.main_seen = person["number"], True, time.monotonic()
        return person["number"]

    def automatic(self):
        """Follow the nearest person again (keeps the current main person while visible)."""
        self.chosen = False

    def main_box(self):
        """(number, box as fractions) of the main person while visible, else None (for the vision model)."""
        for person in self.people:
            if person["number"] == self.main:
                return person["number"], person["box"]
        return None

    def run(self):
        try:
            self.model = pose.PoseModel(self.log)
        except Exception as error:  # model file or runtime missing: shown in the window and the log
            self.status = f"pose model not available: {error}"
            self.log(self.status)
            return
        self.status = f"pose model on the {self.model.device}, {self.model.ms:.0f} ms per frame"
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s = self.settings
        address = (s["unreal_address"], int(s["moverse_port"]))
        rotation = camera_rotation(s["camera_yaw"], s["camera_pitch"], s["camera_roll"])
        translation = np.array([s["camera_x"], s["camera_y"], s["camera_z"]], float)
        smooth = OneEuro(s["filter_min_cutoff"], s["filter_beta"])
        offset, subject = head_offset(), subject_packet()
        last_seq, last_seen, last_subject, last_main, times = 0, 0.0, 0.0, None, []
        while self.running:
            with self.frames.lock:
                seq, color, depth, intrinsics = self.frames.seq, self.frames.color, self.frames.depth, self.frames.intrinsics
            if seq == last_seq or color is None or intrinsics is None:
                time.sleep(0.002)
                continue
            last_seq = seq  # the newest frame only: frames that came while the model ran are skipped
            image, captured = color
            now = time.monotonic()
            self.number_people(self.detect(image, depth, intrinsics), now)
            main = self.choose_main(now)
            if main is None:
                if now - last_seen > LOST_AFTER:
                    self.position = None
                    smooth.t = None  # start fresh when someone comes back
                continue
            if main["number"] != last_main:
                smooth.t = None  # another person: no gliding from the old one's position
                last_main = main["number"]
            last_seen = now
            self.distance_from = main["source"]
            head = smooth(translation + rotation @ (main["point"] / 10.0), captured)  # mm to cm
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

    def detect(self, image, depth, intrinsics):
        """Head point of every person in the image: camera space in mm (x right, y down, z forward), with
        the person box and the head point as fractions of the image and where the distance came from."""
        h, w = image.shape[:2]
        fx, fy, cx, cy = intrinsics
        heads = []
        for person in self.model(image):
            points = person["points"]

            def good(i):
                return points[i, 2] >= MIN_POINT_CONFIDENCE

            for group in ((pose.LEFT_EYE, pose.RIGHT_EYE), (pose.NOSE,), (pose.LEFT_EAR, pose.RIGHT_EAR)):
                if all(good(i) for i in group):
                    u, v = points[list(group), :2].mean(0)
                    break
            else:
                continue  # head not seen
            z, source = None, ""
            if depth is not None:
                sx, sy = depth.shape[1] / w, depth.shape[0] / h
                du, dv, r = int(u * sx), int(v * sy), max(2, int(6 * sx))
                patch = depth[max(0, dv - r):dv + r + 1, max(0, du - r):du + r + 1]
                valid = patch[patch > 0]
                if valid.size >= 5:
                    z, source = float(np.median(valid)), "camera depth"
            if z is None and good(pose.LEFT_EYE) and good(pose.RIGHT_EYE):
                eyes = np.linalg.norm(points[pose.LEFT_EYE, :2] - points[pose.RIGHT_EYE, :2])
                if eyes > 2:
                    z, source = fx * EYE_DISTANCE_MM / eyes, "eye distance"
            if z is None:
                continue
            box = person["box"]
            heads.append({
                "point": np.array([(u - cx) * z / fx, (v - cy) * z / fy, z]),
                "box": (box[0] / w, box[1] / h, box[2] / w, box[3] / h),
                "head": (u / w, v / h),
                "source": source,
            })
        return heads

    def number_people(self, heads, now):
        """Give each head the number of the nearest person seen before (within MATCH_DISTANCE), else a new one."""
        pairs = sorted(
            (math.dist(head["head"], track["head"]), i, number)
            for i, head in enumerate(heads) for number, track in self.tracks.items())
        used_heads, used_numbers = set(), set()
        for distance, i, number in pairs:
            if distance > MATCH_DISTANCE:
                break
            if i in used_heads or number in used_numbers:
                continue
            heads[i]["number"] = number
            used_heads.add(i)
            used_numbers.add(number)
        for head in heads:
            if "number" not in head:
                head["number"] = self.next_number
                self.next_number += 1
            head["seen"] = now
            self.tracks[head["number"]] = head
        self.tracks = {n: t for n, t in self.tracks.items() if now - t["seen"] <= FORGET_AFTER}
        self.people = heads

    def choose_main(self, now):
        """The main person if visible; else wait for the clicked one (up to KEEP_CHOSEN), else the nearest."""
        visible = {person["number"]: person for person in self.people}
        if self.main in visible:
            self.main_seen = now
            return visible[self.main]
        if self.chosen:
            if now - self.main_seen <= KEEP_CHOSEN:
                return None  # the clicked person is hidden for a moment: send nothing rather than someone else
            self.log(f"tracking: P{self.main} gone for {KEEP_CHOSEN:.0f} s, following the nearest person")
            self.chosen = False
        if not visible:
            return None
        nearest = min(visible.values(), key=lambda person: person["point"][2])
        self.main, self.main_seen = nearest["number"], now
        return nearest
