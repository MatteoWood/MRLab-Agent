"""Head tracker with all calibrated cameras (Step 8B).

The cameras only deliver pictures. In each camera's helper program (hub/cameras.py) the pose model
(YOLO11 nano pose, hub/pose.py, on this PC's graphics card) finds the people and their body points. Here
every face point a camera sees (nose, eyes, ears) becomes a line of sight in the room, from the camera's
lens and its position (the hub's calibration, hub/calibration.py).
- People across cameras: a known person takes, from each camera, the person whose head line (through the
  middle of their visible face points) passes nearest to where they are expected (within MATCH). The rest
  are paired where two cameras' head lines nearly cross (within NEW_GATE) at a head height. A new person
  counts only after CONFIRM updates in a row (single wrong matches made extra "people" in the lab), and a
  new person within MERGE of a known one is that person.
- Head position: each face point is triangulated on its own (the point nearest to its lines, weighted by
  the point's confidence and 1 / distance squared; a line further than GATE is dropped), so all cameras
  aim at the same physical spot. The head is the middle of the two eyes. Without both eyes, the other
  triangulated points stand in, shifted by their distance from the eyes learned while both were seen, so
  the position does not jump when the visible points change. No depth is used: a person needs two cameras.
- Timing: pictures are combined only when taken within SAME_TIME of the newest one, and each line is moved
  along the person's velocity to that moment.
- The main person (clicked in the window, else the one nearest to the wall) is smoothed with a One Euro
  filter and sent to the Unreal PC in Moverse's packet format (subject Actor0, 25 moverserig bones, head
  at the point) at every update, so the Moverse Live Link plugin, NDC_Basic and the gaze work unchanged.
  Moverse must not run at the same time (two senders on one port).
"""
import collections
import itertools
import json
import math
import socket
import threading
import time

import cv2
import numpy as np

from hub import calibration, pose

MIN_POINT_CONFIDENCE = 0.5
FACE = (pose.NOSE, pose.LEFT_EYE, pose.RIGHT_EYE, pose.LEFT_EAR, pose.RIGHT_EAR)
SAME_TIME = 0.025         # s: pictures combined only when taken this close to the newest one
GATE = 12.0               # cm: the lines of one face point pass at most this far from it
MATCH = 35.0              # cm: a known person's head line passes at most this far from where they are expected
NEW_GATE = 20.0           # cm: two cameras' head lines of a new person pass at most this far apart
MERGE = 40.0              # cm: a new person this close to a known one is the same person
CONFIRM = 8               # updates in a row a new person must be found in before they count
HEAD_HEIGHT = (40.0, 240.0)  # cm above the floor
MIN_INTERVAL = 1 / 120    # s between updates
LOST_AFTER = 0.5          # s: the main person's position is kept this long when nobody locates them
FORGET_AFTER = 2.0        # s a person may be unseen and keep their number
KEEP_CHOSEN = 2.0         # s the clicked main person may be unseen before the nearest is followed again
OFFSET_SMOOTHING = 0.05   # share of a new measurement in a face point's learned distance from the eyes
AREA_MARGIN = 30.0        # cm: people further outside the area the cameras surround are ignored (reflections)
NEW_CAMERAS = 3           # cameras that must see a new person at the same moment before they count
FALLBACK_SHARE = 0.35     # without both eyes the measured head moves the position only this share of the way
MAX_SPEED = 300.0         # cm/s: a measurement further from the expected spot than this allows (plus
JUMP_SLACK = 15.0         # cm) is held back,
HOLD_BACK = 5             # at most this many times in a row
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
    """Point nearest to the lines, each weighted by its weight, then also by 1 / distance squared, or None."""
    point = None
    for _ in range(2):
        a, b = np.zeros((3, 3)), np.zeros(3)
        for line in lines:
            weight = line["weight"]
            if point is not None:
                weight /= max(1.0, float(np.linalg.norm(point - line["origin"])) / 100.0) ** 2
            p = np.eye(3) - np.outer(line["direction"], line["direction"])
            a += weight * p
            b += weight * p @ line["origin"]
        if np.linalg.cond(a) > 1e8:
            return None
        point = np.linalg.solve(a, b)
    return point


def robust_point(lines):
    """One face point from its lines of sight: drop the furthest line while it passes further than GATE
    (keeping two or more); None when the lines do not meet within GATE."""
    lines = list(lines)
    while len(lines) >= 2:
        point = closest_point(lines)
        if point is None:
            return None
        gaps = [distance_to_line(point, line) for line in lines]
        worst = int(np.argmax(gaps))
        if gaps[worst] <= GATE:
            return point
        if len(lines) == 2:
            return None
        lines.pop(worst)
    return None


class Tracker(threading.Thread):
    def __init__(self, cameras, poses, settings, log=print):
        """cameras: [Camera] streaming; poses: {device id: {"number", "rotation", "position", "matrix"}}
        (calibration)."""
        super().__init__(daemon=True)
        self.settings, self.log = settings, log
        self.running = True
        self.cameras = [c for c in cameras if c.device_id in poses and c.lens and c.worker]
        self.poses = {c.device_id: (int(poses[c.device_id]["number"]), np.array(poses[c.device_id]["rotation"]),
                                    np.array(poses[c.device_id]["position"])) for c in self.cameras}
        # the focal length and picture centre measured in the calibration (older calibrations: the camera's own)
        self.lenses = {c.device_id: dict(c.lens, matrix=poses[c.device_id].get("matrix", c.lens["matrix"])) for c in self.cameras}
        # The area the cameras surround (seen from above): people outside it are reflections or objects.
        corners = np.array([pose_["position"][:2] for pose_ in poses.values()], np.float32)
        self.area = cv2.convexHull(corners) if len(corners) >= 3 else None
        self.wake = threading.Condition()
        self.views = {}        # device id -> (capture time, [people seen]), newest picture per camera
        self.version = 0       # counts the pictures that came in
        self.used = -1         # version of the last update
        self.tracks = {}       # number -> person (also not confirmed ones, and unseen for up to FORGET_AFTER)
        self.next_number = 1
        self.main_seen = 0.0   # when the main person was last seen
        self.smooth = OneEuro(settings["filter_min_cutoff"], settings["filter_beta"])
        self.last_main, self.last_time, self.last_seen, self.times = None, 0.0, 0.0, []
        # Shown in the window (read by the window's thread):
        self.status = "starting"
        self.people = []       # [{"number", "position" (cm), "cameras" (numbers)}] confirmed, seen in the last LOST_AFTER s
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
        lens = self.lenses[camera.device_id]
        w, h = lens["size"]
        found, pixels = [], []
        for box, points, _ in people:
            good = [i for i in FACE if points[i, 2] >= MIN_POINT_CONFIDENCE]
            if good:
                head = points[good, :2].mean(0)
                found.append((box, points, good, head))
                pixels += [points[i, :2] for i in good] + [head]
        seen = []
        if found:
            directions = np.column_stack([calibration.normalize(pixels, lens), np.ones(len(pixels))]) @ rotation.T
            directions = iter(directions / np.linalg.norm(directions, axis=1, keepdims=True))
            for box, points, good, head in found:
                face = {i: {"origin": origin, "direction": next(directions), "weight": float(points[i, 2]), "captured": captured}
                        for i in good}
                seen.append({"camera": number, "captured": captured, "face": face,
                             "line": {"origin": origin, "direction": next(directions), "weight": 1.0, "captured": captured},
                             "box": (box[0] / w, box[1] / h, box[2] / w, box[3] / h), "head": (head[0] / w, head[1] / h),
                             "number": None})
        with self.wake:
            self.views[camera.device_id] = (captured, seen)
            self.version += 1
            self.wake.notify()

    # ---------- for the window ----------

    def seen_by(self, device_id):
        """[(box, head, person number or None)] in that camera's newest picture (fractions of the picture)."""
        with self.wake:
            captured, seen = self.views.get(device_id, (0.0, []))
        if time.perf_counter() - captured > 0.5:
            return []
        return [(person["box"], person["head"], person["number"]) for person in seen]

    def select(self, device_id, x, y):
        """Make the person under (x, y) in that camera's picture the main person; their number or None."""
        hits = [(box, number) for box, _, number in self.seen_by(device_id)
                if number is not None and box[0] <= x <= box[2] and box[1] <= y <= box[3]]
        if not hits:
            return None
        _, number = min(hits, key=lambda hit: (hit[0][2] - hit[0][0]) * (hit[0][3] - hit[0][1]))
        self.main, self.chosen, self.main_seen = number, True, time.perf_counter()
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
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        address = (self.settings["unreal_address"], int(self.settings["moverse_port"]))
        offset, subject = head_offset(), subject_packet()
        last_update = last_subject = 0.0
        while self.running:
            with self.wake:
                self.wake.wait(0.1)
            wait = MIN_INTERVAL - (time.perf_counter() - last_update)
            if wait > 0:
                time.sleep(wait)
            now = last_update = time.perf_counter()
            if not self.update(now):
                continue
            try:
                if now - last_subject > 1.0:  # sent every second, so Unreal can start at any time
                    sock.sendto(subject, address)
                    last_subject = now
                sock.sendto(frame_packet(self.position, offset), address)
                if self.sent == 0:
                    self.log(f"tracking: first packet sent to {address[0]}:{address[1]}")
                self.sent += 1
            except OSError as error:
                self.log(f"tracking: send failed: {error}")
                time.sleep(0.5)

    def update(self, now):
        """One combining step (now: the time on time.perf_counter()); True when the main person's smoothed
        head position (self.position) changed and should be sent."""
        with self.wake:
            if self.version == self.used:
                return False
            self.used = self.version
            views = list(self.views.values())
        newest = max(captured for captured, _ in views)
        seen = [person for captured, people in views if newest - captured <= SAME_TIME for person in people]
        updated = self.locate(seen, newest, now)
        main = self.choose_main(now)
        if main is None or main not in updated:
            if now - self.last_seen > LOST_AFTER:
                self.position = None
                self.smooth.t = None  # start fresh when someone comes back
            return False
        if newest <= self.last_time:
            return False
        if main != self.last_main:
            self.smooth.t = None  # another person: no gliding from the old one's position
            self.last_main = main
        self.last_seen, self.last_time = now, newest
        self.position = self.smooth(self.tracks[main]["position"], newest)
        self.times = [t for t in self.times if now - t < 1.0] + [now]
        self.rate = len(self.times)
        return True

    def locate(self, seen, t, now):
        """Numbers the people seen in the pictures and moves the known people; returns the numbers of the
        confirmed people located now (seen by two or more cameras). t: time of the newest picture."""
        expected = {n: track["position"] + track["velocity"] * min(max(t - track["time"], 0.0), 0.2)
                    for n, track in self.tracks.items()}
        pairs = sorted((distance_to_line(expected[n], person["line"]), n, i)
                       for n in self.tracks for i, person in enumerate(seen))
        taken, slots, members = set(), set(), collections.defaultdict(list)
        for gap, n, i in pairs:
            if gap > MATCH:
                break
            if i in taken or (n, seen[i]["camera"]) in slots:
                continue
            taken.add(i)
            slots.add((n, seen[i]["camera"]))
            members[n].append(i)
        updated = set()
        for n, chosen in members.items():
            found = self.head(self.tracks[n], [seen[i] for i in chosen], t)
            if found is not None and self.move(n, *found, t, now, {seen[i]["camera"] for i in chosen}):
                updated.add(n)
        # New people: two cameras' head lines that nearly cross at a head height, joined by others passing close;
        # not where a known person is (those are their own lines that did not match this time).
        rest = [i for i in range(len(seen)) if i not in taken]
        candidates = []
        for a, b in itertools.combinations(rest, 2):
            if seen[a]["camera"] != seen[b]["camera"]:
                met = crossing(seen[a]["line"], seen[b]["line"])
                if met and met[1] < NEW_GATE and HEAD_HEIGHT[0] <= met[0][2] <= HEAD_HEIGHT[1]:
                    candidates.append((met[1], a, b, met[0]))
        for _, a, b, guess in sorted(candidates, key=lambda c: c[0]):
            if a in taken or b in taken:
                continue
            if any(np.linalg.norm(guess - p) < MERGE for p in expected.values()) or not self.inside(guess):
                taken.update((a, b))
                continue
            chosen, cameras = [a, b], {seen[a]["camera"], seen[b]["camera"]}
            for i in sorted(rest, key=lambda i: distance_to_line(guess, seen[i]["line"])):
                if i not in taken and i not in chosen and seen[i]["camera"] not in cameras \
                        and distance_to_line(guess, seen[i]["line"]) < NEW_GATE:
                    chosen.append(i)
                    cameras.add(seen[i]["camera"])
            track = {"position": guess, "velocity": np.zeros(3), "time": 0.0, "seen": now, "cameras": [],
                     "offsets": {}, "path": collections.deque(), "hits": 0, "most": 0, "held": 0, "confirmed": False}
            found = self.head(track, [seen[i] for i in chosen], t)
            if found is None:
                continue
            n = self.next_number
            self.next_number += 1
            self.tracks[n] = track
            members[n] = chosen
            taken.update(chosen)
            self.move(n, *found, t, now, cameras)
            updated.add(n)
        for n, chosen in members.items():
            confirmed = n in self.tracks and self.tracks[n]["confirmed"]
            for i in chosen:
                seen[i]["number"] = n if confirmed else None
        # Forget people unseen too long (not confirmed ones quickly); two confirmed people on the same spot are one.
        self.tracks = {n: track for n, track in self.tracks.items()
                       if now - track["seen"] <= (FORGET_AFTER if track["confirmed"] else 0.3)}
        confirmed = sorted(n for n, track in self.tracks.items() if track["confirmed"])
        for a, b in itertools.combinations(confirmed, 2):
            if a in self.tracks and b in self.tracks and \
                    np.linalg.norm(self.tracks[a]["position"] - self.tracks[b]["position"]) < MERGE / 2:
                del self.tracks[a if b == self.main else b]
        self.people = [{"number": n, "position": track["position"], "cameras": track["cameras"]}
                       for n, track in self.tracks.items() if track["confirmed"] and now - track["seen"] <= LOST_AFTER]
        return {n for n in updated if n in self.tracks and self.tracks[n]["confirmed"]}

    @staticmethod
    def head(track, people, t):
        """(head position, whether from both eyes) of one person from the lines of sight of their face points,
        or None."""
        points = {}
        for k in FACE:
            lines = []
            for person in people:
                line = person["face"].get(k)
                if line is not None:  # moved along the person's velocity to the moment t
                    lines.append(dict(line, origin=line["origin"] + track["velocity"] * (t - line["captured"])))
            if len(lines) >= 2:
                point = robust_point(lines)
                if point is not None:
                    points[k] = point
        named = {"left eye": points.get(pose.LEFT_EYE), "right eye": points.get(pose.RIGHT_EYE),
                 "nose": points.get(pose.NOSE), "left ear": points.get(pose.LEFT_EAR), "right ear": points.get(pose.RIGHT_EAR)}
        offsets = track["offsets"]
        eyes = named["left eye"] is not None and named["right eye"] is not None
        if eyes:
            head = (named["left eye"] + named["right eye"]) / 2
            for name, point in named.items():  # how far each point is from the middle of the eyes, for later
                if point is not None:
                    offsets[name] = head - point if name not in offsets else \
                        (1 - OFFSET_SMOOTHING) * offsets[name] + OFFSET_SMOOTHING * (head - point)
        else:
            guesses = [point + offsets[name] for name, point in named.items() if point is not None and name in offsets]
            if guesses:
                head = np.mean(guesses, axis=0)
            elif points:
                head = np.mean(list(points.values()), axis=0)  # nothing learned yet
            else:
                return None
        return (head, eyes) if HEAD_HEIGHT[0] <= head[2] <= HEAD_HEIGHT[1] else None

    def inside(self, point):
        return self.area is None or \
            cv2.pointPolygonTest(self.area, (float(point[0]), float(point[1])), True) >= -AREA_MARGIN

    def move(self, n, head, eyes, t, now, cameras):
        """Moves person n to the measured head; False when the measurement was held back as a jump."""
        track = self.tracks[n]
        if track["time"]:
            dt = max(t - track["time"], 0.0)
            expected = track["position"] + track["velocity"] * min(dt, 0.2)
            if np.linalg.norm(head - expected) > JUMP_SLACK + MAX_SPEED * dt and track["held"] < HOLD_BACK:
                track["held"] += 1
                return False
            if not eyes:  # stand-in points only: less sure, so only part of the way
                head = expected + FALLBACK_SHARE * (head - expected)
        track["held"] = 0
        path = track["path"]  # positions of the last 0.15 s: velocity over that span (less noisy than per update)
        path.append((t, head))
        while path and t - path[0][0] > 0.15:
            path.popleft()
        if len(path) >= 2 and path[-1][0] - path[0][0] >= 0.05:
            velocity = (path[-1][1] - path[0][1]) / (path[-1][0] - path[0][0])
            speed = float(np.linalg.norm(velocity))
            track["velocity"] = velocity * min(1.0, 300.0 / speed) if speed > 0 else velocity
        track.update(position=head, time=t, seen=now, cameras=sorted(cameras))
        track["hits"] += 1
        track["most"] = max(track["most"], len(cameras))
        if track["hits"] >= CONFIRM and track["most"] >= NEW_CAMERAS:
            track["confirmed"] = True
        return True

    def choose_main(self, now):
        """The main person's number if visible; else wait for the clicked one (up to KEEP_CHOSEN), else the
        person nearest to the wall."""
        visible = {p["number"]: p for p in self.people}
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
