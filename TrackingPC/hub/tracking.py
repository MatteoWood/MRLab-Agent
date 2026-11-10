"""Head tracker with all calibrated cameras (Step 8B).

The cameras only deliver pictures. In each camera's helper program (hub/cameras.py) the pose model
(YOLO11 nano pose, hub/pose.py, on this PC's graphics card) finds the people and their body points. Here,
for every person a camera sees, the head point in the picture (the middle of the eyes; if not both eyes
are visible, the middle of the visible face points: nose, eyes, ears) becomes a line of sight in the room,
from the camera's lens (factory calibration) and its position (the hub's calibration, hub/calibration.py).
Where the lines of sight of several cameras meet is the head: the point closest to all of them, each
weighted by 1 / distance squared (a far camera's line is less sure). Eye lines are used when at least
two cameras see both eyes, else all face lines. One camera alone gives no position (no depth is used):
the person keeps their last position for up to LOST_AFTER seconds.
People across cameras: a person found before is looked for along each camera's lines (within TRACK_GATE
of their last position); the remaining lines are paired where two cameras' lines nearly cross (within
GATE) at a head height, then joined by other cameras' lines passing as close. Each person keeps a number
while seen. The main person (clicked in the window, else the one nearest to the wall) is smoothed with a
One Euro filter and sent to the Unreal PC in Moverse's packet format (subject Actor0, 25 moverserig bones,
head at the point) at every update, so the Moverse Live Link plugin, NDC_Basic and the gaze work
unchanged. Pictures older than MAX_AGE are not combined. Moverse must not run at the same time (two
senders on one port).
"""
import collections
import itertools
import json
import math
import socket
import threading
import time

import numpy as np

from hub import calibration, pose

MIN_POINT_CONFIDENCE = 0.5
FACE = (pose.NOSE, pose.LEFT_EYE, pose.RIGHT_EYE, pose.LEFT_EAR, pose.RIGHT_EAR)
MAX_AGE = 0.05            # s: older pictures are not combined
GATE = 15.0               # cm: lines of one head pass at most this far from it
TRACK_GATE = 30.0         # cm: a known person's head moves less than this between updates
HEAD_HEIGHT = (40.0, 240.0)  # cm above the floor
MIN_INTERVAL = 1 / 120    # s between updates
LOST_AFTER = 0.5
FORGET_AFTER = 2.0        # seconds a person may be unseen and keep their number
KEEP_CHOSEN = 2.0         # seconds the clicked main person may be unseen before the nearest is followed again
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




# ---------- lines of sight ----------

def distance_to_line(point, line):
    """Distance of a point from a line of sight (infinite behind the camera)."""
    v = point - line["origin"]
    along = v @ line["direction"]
    return float(np.linalg.norm(v - along * line["direction"])) if along > 0 else math.inf


def crossing(a, b):
    """Middle of the closest approach of two lines of sight and how far apart they pass, or None."""
    w = a["origin"] - b["origin"]
    k = a["direction"] @ b["direction"]
    d, e = a["direction"] @ w, b["direction"] @ w
    den = 1.0 - k * k
    if den < 1e-6:
        return None
    s, t = (k * e - d) / den, (e - k * d) / den
    if s <= 0 or t <= 0:
        return None
    pa, pb = a["origin"] + s * a["direction"], b["origin"] + t * b["direction"]
    return (pa + pb) / 2, float(np.linalg.norm(pa - pb))


def closest_point(lines):
    """Point nearest to all lines of sight, each weighted by 1 / distance squared (two passes), or None."""
    point = None
    for _ in range(2):
        a, b = np.zeros((3, 3)), np.zeros(3)
        for line in lines:
            weight = 1.0 if point is None else 1.0 / max(1.0, float(np.linalg.norm(point - line["origin"]))) ** 2
            p = np.eye(3) - np.outer(line["direction"], line["direction"])
            a += weight * p
            b += weight * p @ line["origin"]
        if np.linalg.cond(a) > 1e8:
            return None
        point = np.linalg.solve(a, b)
    return point


class Tracker(threading.Thread):
    def __init__(self, cameras, poses, settings, log=print):
        """cameras: [Camera] streaming; poses: {device id: {"number", "rotation", "position"}} (calibration)."""
        super().__init__(daemon=True)
        self.settings, self.log = settings, log
        self.running = True
        self.cameras = [c for c in cameras if c.device_id in poses and c.lens and c.worker]
        self.poses = {c.device_id: (int(poses[c.device_id]["number"]), np.array(poses[c.device_id]["rotation"]),
                                    np.array(poses[c.device_id]["position"])) for c in self.cameras}
        self.wake = threading.Condition()
        self.views = {}        # device id -> (capture time, [lines of sight]), newest picture per camera
        self.tracks = {}       # number -> {"position", "seen", "cameras"} (also unseen for up to FORGET_AFTER)
        self.next_number = 1
        self.main_seen = 0.0   # when the main person was last seen
        # Shown in the window (read by the window's thread):
        self.status = "starting"
        self.people = []       # [{"number", "position" (cm), "cameras" (numbers)}] seen in the last LOST_AFTER s
        self.main = None       # number of the main person, whose head is sent
        self.chosen = False    # main person chosen by a click (else: automatic, nearest to the wall)
        self.position = None   # filtered head position of the main person (cm)
        self.rate = 0.0        # updates of the main person per second
        self.sent = 0
        for camera in self.cameras:
            camera.on_people = self.on_people

    def stop(self):
        self.running = False
        for camera in self.cameras:
            camera.on_people = None
            camera.worker.pose(None)

    # ---------- called from the camera threads ----------

    def on_people(self, camera, captured, people):
        number, rotation, origin = self.poses[camera.device_id]
        w, h = camera.lens["size"]
        heads = []
        for box, points, _ in people:
            good = points[:, 2] >= MIN_POINT_CONFIDENCE
            if good[pose.LEFT_EYE] and good[pose.RIGHT_EYE]:
                chosen, kind = [pose.LEFT_EYE, pose.RIGHT_EYE], "eyes"
            else:
                chosen, kind = [i for i in FACE if good[i]], "face"
                if not chosen:
                    continue
            heads.append((points[chosen, :2].mean(0), kind, box))
        lines = []
        if heads:
            normalized = calibration.normalize([head for head, _, _ in heads], camera.lens)
            for (head, kind, box), (x, y) in zip(heads, normalized):
                direction = rotation @ np.array([x, y, 1.0])
                lines.append({"camera": number, "origin": origin, "direction": direction / np.linalg.norm(direction),
                              "kind": kind, "box": (box[0] / w, box[1] / h, box[2] / w, box[3] / h),
                              "head": (head[0] / w, head[1] / h), "number": None})
        with self.wake:
            self.views[camera.device_id] = (captured, lines)
            self.wake.notify()

    # ---------- for the window ----------

    def seen_by(self, device_id):
        """[(box, head, person number or None)] in that camera's newest picture (fractions of the picture)."""
        with self.wake:
            captured, lines = self.views.get(device_id, (0.0, []))
        if time.monotonic() - captured > 0.5:
            return []
        return [(line["box"], line["head"], line["number"]) for line in lines]

    def select(self, device_id, x, y):
        """Make the person under (x, y) in that camera's picture the main person; their number or None."""
        hits = [(box, number) for box, _, number in self.seen_by(device_id)
                if number is not None and box[0] <= x <= box[2] and box[1] <= y <= box[3]]
        if not hits:
            return None
        _, number = min(hits, key=lambda hit: (hit[0][2] - hit[0][0]) * (hit[0][3] - hit[0][1]))
        self.main, self.chosen, self.main_seen = number, True, time.monotonic()
        return number

    def automatic(self):
        """Follow the person nearest to the wall again (keeps the current main person while visible)."""
        self.chosen = False

    def main_box(self, device_id):
        """(number, box as fractions) of the main person in that camera's picture, else None (for vision)."""
        for box, _, number in self.seen_by(device_id):
            if number is not None and number == self.main:
                return number, box
        return None

    # ---------- combining ----------

    def run(self):
        self.status = "timing the pose model"
        try:
            model = pose.PoseModel(self.log)
        except Exception as error:  # model file or runtime missing: shown in the window and the log
            self.status = f"pose model not available: {error}"
            self.log(self.status)
            return
        if not self.running:
            return
        for camera in self.cameras:
            camera.worker.pose(model.device)
        self.status = f"pose model on the {model.device} ({model.ms:.0f} ms per picture), {len(self.cameras)} cameras"
        del model
        s = self.settings
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        address = (s["unreal_address"], int(s["moverse_port"]))
        smooth = OneEuro(s["filter_min_cutoff"], s["filter_beta"])
        offset, subject = head_offset(), subject_packet()
        last_update = last_seen = last_subject = last_time = 0.0
        last_main, times = None, []
        while self.running:
            with self.wake:
                self.wake.wait(0.1)
            wait = MIN_INTERVAL - (time.monotonic() - last_update)
            if wait > 0:
                time.sleep(wait)
            now = last_update = time.monotonic()
            with self.wake:
                views = {k: v for k, v in self.views.items() if now - v[0] <= MAX_AGE}
            if not views:
                continue
            newest = max(captured for captured, _ in views.values())
            located = self.locate([line for _, lines in views.values() for line in lines], now)
            main = self.choose_main(now)
            if main is None or main not in located:
                if now - last_seen > LOST_AFTER:
                    self.position = None
                    smooth.t = None  # start fresh when someone comes back
                continue
            if newest <= last_time:
                continue  # nothing new since the last update
            if main != last_main:
                smooth.t = None  # another person: no gliding from the old one's position
                last_main = main
            last_seen, last_time = now, newest
            head = smooth(located[main], newest)
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

    def locate(self, lines, now):
        """Gives each line of sight the number of its person; {number: head position} of the people seen by
        two or more cameras now."""
        taken, members = set(), collections.defaultdict(list)
        # People seen before: from each camera, the line passing nearest to their last position.
        pairs = sorted((distance_to_line(track["position"], line), number, i)
                       for number, track in self.tracks.items() for i, line in enumerate(lines))
        slots = set()
        for gap, number, i in pairs:
            if gap > TRACK_GATE:
                break
            if i in taken or (number, lines[i]["camera"]) in slots:
                continue
            taken.add(i)
            slots.add((number, lines[i]["camera"]))
            members[number].append(i)
        located = {}
        for number, chosen in members.items():
            point = self.triangulate([lines[i] for i in chosen])
            for i in chosen:
                lines[i]["number"] = number
            if point is not None:
                located[number] = point
        # New people: two cameras' lines that nearly cross at a head height, joined by others passing close.
        rest = [i for i in range(len(lines)) if i not in taken]
        candidates = []
        for a, b in itertools.combinations(rest, 2):
            if lines[a]["camera"] == lines[b]["camera"]:
                continue
            met = crossing(lines[a], lines[b])
            if met and met[1] < GATE and HEAD_HEIGHT[0] <= met[0][2] <= HEAD_HEIGHT[1]:
                candidates.append((met[1], a, b, met[0]))
        for _, a, b, guess in sorted(candidates, key=lambda c: c[0]):
            if a in taken or b in taken:
                continue
            chosen, cameras = [a, b], {lines[a]["camera"], lines[b]["camera"]}
            for i in sorted(rest, key=lambda i: distance_to_line(guess, lines[i])):
                if i not in taken and i not in chosen and lines[i]["camera"] not in cameras and distance_to_line(guess, lines[i]) < GATE:
                    chosen.append(i)
                    cameras.add(lines[i]["camera"])
            point = self.triangulate([lines[i] for i in chosen])
            if point is None:
                continue
            number = self.next_number
            self.next_number += 1
            self.tracks[number] = {"position": point, "seen": now, "cameras": []}
            located[number] = point
            taken.update(chosen)
            members[number] = chosen
            for i in chosen:
                lines[i]["number"] = number
        for number, point in located.items():
            self.tracks[number].update(position=point, seen=now,
                                       cameras=sorted(lines[i]["camera"] for i in members[number]))
        self.tracks = {n: t for n, t in self.tracks.items() if now - t["seen"] <= FORGET_AFTER}
        self.people = [{"number": n, "position": t["position"], "cameras": t["cameras"]}
                       for n, t in self.tracks.items() if now - t["seen"] <= LOST_AFTER]
        return located

    @staticmethod
    def triangulate(lines):
        """Head position from the lines of sight of one person, or None (fewer than two usable lines)."""
        eyes = [line for line in lines if line["kind"] == "eyes"]
        lines = eyes if len(eyes) >= 2 else lines
        if len(lines) < 2:
            return None
        point = closest_point(lines)
        if point is None:
            return None
        near = [line for line in lines if distance_to_line(point, line) < GATE]
        if len(near) < 2:
            return None
        if len(near) < len(lines):  # a line that does not belong (wrong match): without it
            point = closest_point(near)
        if point is None or not HEAD_HEIGHT[0] <= point[2] <= HEAD_HEIGHT[1]:
            return None
        return point

    def choose_main(self, now):
        """The main person's number if visible; else wait for the clicked one (up to KEEP_CHOSEN), else the
        person nearest to the wall."""
        visible = {n: t for n, t in self.tracks.items() if now - t["seen"] <= LOST_AFTER}
        if self.main in visible:
            self.main_seen = now
            return self.main
        if self.chosen:
            if now - self.main_seen <= KEEP_CHOSEN:
                return None  # the clicked person is hidden for a moment: send nothing rather than someone else
            self.log(f"tracking: P{self.main} gone for {KEEP_CHOSEN:.0f} s, following the person nearest to the wall")
            self.chosen = False
        if not visible:
            return None
        self.main = max(visible, key=lambda n: visible[n]["position"][0])
        self.main_seen = now
        return self.main
