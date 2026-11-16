"""Head tracker with all calibrated cameras (Step 8B).

The cameras only deliver pictures. In each camera's helper program (hub/cameras.py) the pose model
(YOLO11 nano pose, hub/pose.py, on this PC's graphics card) finds the people and their body points. Here
every face point a camera sees (nose, eyes, ears) becomes a line of sight in the room, from the camera's
lens and its position (the hub's calibration, hub/calibration.py).
- People across cameras: a known person takes, from each camera, the person whose head line (through the
  middle of their visible face points) passes nearest to where they are expected (within MATCH). The rest
  are paired where two cameras' head lines nearly cross (within NEW_GATE) at a head height. A new person
  counts only after CONFIRM updates, seen by NEW_CAMERAS different cameras, inside the area the cameras
  surround and not on the LED wall (single wrong matches, a reflection and Frank on the wall made extra
  "people" in the lab), and a new person within MERGE of a known one is that person.
- Head position: each face point is triangulated on its own (the point nearest to its lines, weighted by
  the point's confidence and 1 / distance squared; a line further than GATE is dropped), so all cameras
  aim at the same physical spot. The head is the middle of the two eyes. Without both eyes, the other
  triangulated points stand in, shifted by their distance from the eyes learned while both were seen, so
  the position does not jump when the visible points change. No depth is used: a person needs two cameras.
- Timing: pictures are combined when taken within the slowest camera's interval between analysed pictures
  (SAME_TIME limits) of the newest one, at the middle of their capture times; each line is moved along the
  person's velocity (a line through their positions of the last VELOCITY_SPAN s, zero when standing) to it.
- The main person (clicked in the window, else the one nearest to the wall) goes through Motion (steady
  while standing, quick and smoothed across the direction of movement while moving) and is sent to the
  Unreal PC in Moverse's packet format (subject Actor0, 25 moverserig bones, head at the point) at every
  update, so the Moverse Live Link plugin, NDC_Basic and the gaze work unchanged. Moverse must not run at
  the same time (two senders on one port).
- Tracking log (Recorder, Tracking page "Record tracking data"): what the tracker gets (each analysed
  picture's people: boxes and body points, numbers only, no pictures) and does (each combining step, each
  head sent), so a lab session can be replayed through this or a newer tracker (tools/replay_tracking.py).
- Calibration watch: by how much, on average over the last WATCH_SPAN s, each camera's lines of sight point
  beside the face points triangulated from all cameras (an angle). The pose model's noise scatters them to
  all sides and averages out; a camera that was bumped or turned after the calibration points beside them
  steadily, to one side.
"""
import collections
import gzip
import itertools
import json
import math
import pathlib
import socket
import threading
import time
import traceback

import cv2
import numpy as np

from hub import calibration, pose

MIN_POINT_CONFIDENCE = 0.5
FACE = (pose.NOSE, pose.LEFT_EYE, pose.RIGHT_EYE, pose.LEFT_EAR, pose.RIGHT_EAR)
SAME_TIME = (0.03, 0.15)  # s: pictures are combined when taken this close to the newest one: the slowest
                          # camera's interval between analysed pictures, within these limits. Live, each helper
                          # analyses its newest picture as fast as it can (about 22 a second each on the laptop),
                          # and the helpers need not be equally fast
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
NEW_CAMERAS = 3           # different cameras that must have seen a new person before they count
FALLBACK_SHARE = 0.35     # without both eyes the measured head moves the position only this share of the way
MAX_SPEED = 300.0         # cm/s: a measurement further from the expected spot than this allows (plus
JUMP_SLACK = 15.0         # cm) is held back,
HOLD_BACK = 5             # at most this many times in a row
WALL_CLEARANCE = 25.0     # cm: a new person must be this far in front of the LED wall (Frank on the wall is no visitor)
VELOCITY_SPAN = 0.25      # s: a person's velocity (to line up pictures taken at different moments) is the
VELOCITY_DEAD = 8.0       # line through their positions of this span; slower than this counts as standing
# What is sent (Motion):
STILL_WINDOW = 0.35       # s: standing still when the line through the measurements of this span
STILL_SPEED = 8.0         # cm/s is slower than this
EXIT_MIN = 1.5            # cm: moving again when the head is at least this far from where it stands and further
EXIT_SIGMAS = 2.5         # than this many times the measurement noise explains (EXIT_MAX at most),
EXIT_MAX = 4.0
EXIT_SPEED = 12.0         # cm/s and moving at least this fast (line through the last EXIT_WINDOW s); else it is
EXIT_WINDOW = 0.25        # swaying or noise. Twice as far: moving anyway
ANCHOR_TIME = 1.0         # s after stopping in which the hub learns where the head stands; then it stays there
MAX_SPREAD = 2.5          # cm: the measurement noise is counted at most this
SETTLE_TIME = 0.2         # s: while standing, the sent head glides to where it stands
MOVE_WINDOW = 0.2         # s of measurements the moving head's line is drawn through
BRAKE_SAMPLES = 4         # slowing down: the line through this many last measurements (of 0.2 s at most),
BRAKE_WINDOW = 0.25       # and how hard it slows from a curve through this span (s)
SLOW_SPEED = 15.0         # cm/s: below, the direction of movement is not sure (fully sure at twice this)
ALONG_TIME = 0.02         # s: follows along the direction of movement within this
ACROSS_TIME = 0.15        # s: and across it within this
SLOW_TIME = 0.08          # s: and at low speed in any direction within this
MAX_AHEAD = 0.1           # s: the head is moved on by this share of the age of the pictures (at most
AHEAD_SHARE = 0.7         # MAX_AHEAD)
HEADING_TIME = 0.3        # s: the direction of movement from the velocity smoothed over this
WATCH_SPAN = 30.0         # s of lines of sight the calibration watch looks at
WATCH_DEGREES = 0.5       # degrees: a camera whose lines point beside the face points by more than this on
                          # average has likely moved (owner's walk, judged on 20 s or more: as calibrated at most
                          # 0.14; one camera turned by 1 degree after calibrating: 0.7 to 0.9, only that one)
SUBJECT = "Actor0"


def wall_edge():
    """(Y, X) of the LED wall's bottom edge in tracking space, sorted by Y (hub/led_wall.json)."""
    outline = json.loads(pathlib.Path(__file__).with_name("led_wall.json").read_text())["outline"]
    points = sorted({(round(y, 1), round(x, 1)) for line in outline for x, y, z in (line[:3], line[3:]) if abs(z) < 1})
    return np.array([y for y, _ in points]), np.array([x for _, x in points])


WALL_EDGE_Y, WALL_EDGE_X = wall_edge()

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




def line_fit(samples, t):
    """(position at t, velocity) of the straight line through [(time, position)] (least squares)."""
    s = np.array([x for x, _ in samples]) - t
    p = np.array([y for _, y in samples])
    if len(s) < 3 or s.max() - s.min() < 0.03:
        return p.mean(0), np.zeros(3)
    a = np.column_stack([np.ones_like(s), s])
    (start, velocity), *_ = np.linalg.lstsq(a, p, rcond=None)
    return start, velocity


class Motion:
    """What is sent: steady while the person stands, quick and smooth while they move (2026-11-16; before,
    a One Euro filter let about 1 cm of the measurements' noise through, and the wall's view flickered).

    Two states:
    - "still": the sent head stays where it is. In the first ANCHOR_TIME after stopping the hub learns where
      the head stands (the mean of the measurements; the sent head glides there, in steps of 0.2 mm or
      more), and all along how noisy the measurements are. The person moves again when the median of the
      last 5 measurements is further from that place than the noise explains (EXIT_SIGMAS, EXIT_MIN to
      EXIT_MAX) and the head moves at EXIT_SPEED or more, twice in a row; or twice that far once. Swaying
      on the spot and the noise are not movement.
    - "moving": a straight line through the measurements of the last MOVE_WINDOW s gives where the head is
      and its velocity, without the lag of an average. It is moved on by AHEAD_SHARE of the pictures' age
      (about 0.1 s when sent), so the wall does not trail behind (all of it: the rhythm of the steps and
      every turn were overdone). When the head slows down, the line through the last few measurements is
      used and the head is moved on only as far as it will still go, so it does not overshoot where the
      person stops. The direction of movement comes from the velocity smoothed over HEADING_TIME (the
      velocity of each moment swings with the steps). Along it the head follows at once; across it
      (sideways sway, the bobbing of the steps) within ACROSS_TIME. At low speed the direction is unsure:
      both within SLOW_TIME, not moved on. It is "still" again once the line through the last
      STILL_WINDOW s is slower than STILL_SPEED.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.history = collections.deque()  # (picture time, measured head)
        self.state, self.out, self.t = "moving", None, None
        self.anchor, self.count, self.spread, self.away, self.since = None, 0, 0.0, 0, 0.0
        self.heading = None  # smoothed velocity while moving

    def __call__(self, raw, t, now):
        """The head to send for the measured head `raw` of the pictures taken at t (time.perf_counter()),
        sent at now."""
        raw = np.asarray(raw, float)
        history = self.history
        history.append((t, raw))
        while t - history[0][0] > STILL_WINDOW + 0.1:
            history.popleft()
        if self.out is None:
            self.out, self.t = raw.copy(), t
            return self.out.copy()
        dt, self.t = max(t - self.t, 1e-3), t
        if self.state == "still":
            recent = [p for s, p in list(history)[-5:] if t - s <= 0.25]
            off = float(np.linalg.norm(np.median(recent, axis=0) - self.anchor))
            limit = min(EXIT_MAX, max(EXIT_MIN, EXIT_SIGMAS * 1.25 * self.spread / math.sqrt(len(recent))))
            if limit < off <= 2 * limit and \
                    np.linalg.norm(line_fit([(s, p) for s, p in history if t - s <= EXIT_WINDOW], t)[1]) < EXIT_SPEED:
                off = limit  # off, but not moving away: swaying on the spot, or noise
            self.away = self.away + 1 if off > limit else 0
            if self.away < 2 and off <= 2 * limit:
                gap = float(np.linalg.norm(raw - self.anchor))
                if gap < max(2 * self.spread, EXIT_MIN):  # learn the place and the noise (not from outliers)
                    if t - self.since < ANCHOR_TIME:
                        self.count += 1
                        self.anchor = self.anchor + (raw - self.anchor) / self.count
                    self.spread = min(MAX_SPREAD, math.sqrt(0.97 * self.spread ** 2 + 0.03 * gap ** 2))
                step = (self.anchor - self.out) * (1 - math.exp(-dt / SETTLE_TIME))
                if np.linalg.norm(step) >= 0.02:
                    self.out = self.out + step
                return self.out.copy()
            self.state, self.heading = "moving", None
        settled = [(s, p) for s, p in history if t - s <= STILL_WINDOW]
        if settled[-1][0] - settled[0][0] >= STILL_WINDOW * 0.8 and np.linalg.norm(line_fit(settled, t)[1]) < STILL_SPEED:
            points = np.array([p for _, p in settled])
            self.state, self.anchor, self.count, self.away, self.since = "still", points.mean(0), len(points), 0, t
            self.spread = min(MAX_SPREAD, max(0.3, float(np.sqrt(np.mean(np.sum((points - self.anchor) ** 2, 1))))))
            return self.out.copy()
        position, velocity = line_fit([(s, p) for s, p in history if t - s <= MOVE_WINDOW], t)
        self.heading = velocity if self.heading is None else \
            self.heading + (1 - math.exp(-dt / HEADING_TIME)) * (velocity - self.heading)
        speed = float(np.linalg.norm(velocity))
        ahead = AHEAD_SHARE * min(max(now - t, 0.0), MAX_AHEAD)
        shift = velocity * ahead
        if speed > 0:
            last = [(s, p) for s, p in list(history)[-BRAKE_SAMPLES:] if t - s <= 0.2]
            if len(last) >= 3:
                position_last, velocity_last = line_fit(last, t)
                if velocity_last @ velocity / speed < speed:  # slowing down: the line through the last ones
                    position, velocity = position_last, velocity_last
                    speed = max(float(np.linalg.norm(velocity)), 1e-9)
            shift = velocity * ahead
            curve = [(s, p) for s, p in history if t - s <= BRAKE_WINDOW]
            if len(curve) >= 5:
                s = np.array([x for x, _ in curve]) - t
                c = np.linalg.lstsq(np.column_stack([np.ones_like(s), s, s * s]), np.array([p for _, p in curve]), rcond=None)[0]
                slowing = -2 * c[2] @ velocity / speed  # cm/s2 along the movement, positive when slowing down
                if slowing > 0:
                    direction = velocity / speed
                    ahead = min(ahead, speed / slowing)  # not beyond where it stops
                    shift = velocity * ahead - 0.5 * slowing * ahead ** 2 * direction
                    position = position - slowing * MOVE_WINDOW ** 2 / 12 * direction  # a line runs ahead of a braking path
        heading = float(np.linalg.norm(self.heading))
        sure = min(1.0, max(0.0, (heading - SLOW_SPEED) / SLOW_SPEED))  # how sure the direction is: 0 to 1
        delta = position + sure * shift - self.out
        along = (delta @ self.heading / heading) * self.heading / heading if heading > 0 else np.zeros(3)
        across = delta - along
        along_time = SLOW_TIME + sure * (ALONG_TIME - SLOW_TIME)
        across_time = SLOW_TIME + sure * (ACROSS_TIME - SLOW_TIME)
        self.out = self.out + along * (1 - math.exp(-dt / along_time)) + across * (1 - math.exp(-dt / across_time))
        return self.out.copy()


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


class Recorder:
    """The tracking log: one JSON item per line, gzip. Any thread puts items; the tracker's thread writes."""

    def __init__(self, path, header):
        self.path, self.lock, self.items, self.count = path, threading.Lock(), [], 0
        self.file = gzip.open(path, "wt", encoding="utf-8")
        self.put(header)

    def put(self, item):
        with self.lock:
            if self.file:
                self.items.append(item)

    def flush(self):
        with self.lock:
            items, self.items = self.items, []
            if self.file:
                self.file.writelines(json.dumps(item, separators=(",", ":")) + "\n" for item in items)
                self.count += len(items)

    def close(self):
        self.flush()
        with self.lock:
            if self.file:
                self.file.close()
                self.file = None


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
        self.intervals = {}    # device id -> smoothed time between its analysed pictures
        self.used = -1         # version of the last update
        self.tracks = {}       # number -> person (also not confirmed ones, and unseen for up to FORGET_AFTER)
        self.next_number = 1
        self.main_seen = 0.0   # when the main person was last seen
        self.filter = Motion()
        self.last_main, self.last_time, self.last_seen, self.times = None, 0.0, 0.0, []
        # Shown in the window (read by the window's thread):
        self.status = "starting"
        self.people = []       # [{"number", "position" (cm), "cameras" (numbers)}] confirmed, seen in the last LOST_AFTER s
        self.main = None       # number of the main person, whose head is sent
        self.chosen = False    # main person chosen by a click (else: automatic, nearest to the wall)
        self.position = None   # head position of the main person that is sent (cm)
        self.motion = None     # "still" or "moving" (Motion), None without a main person
        self.rate = 0.0        # updates of the main person per second
        self.age = None        # ms from the newest picture's capture to sending (median over 1 s)
        self.ages = []
        self.combined = 0      # cameras that saw a person in the pictures of the last update
        self.agreement = {}    # camera number -> degrees its lines of sight point beside the face points (mean)
        self.moved = set()     # camera numbers the calibration watch marks
        self.turns = {number: rotation for number, rotation, _ in self.poses.values()}  # camera to tracking
        self.recorder = None   # Recorder while the tracking log is written
        self.gaps = collections.defaultdict(collections.deque)  # camera number -> (time, x, y) of the offset
        self.watched = 0.0
        self.pending = 0       # people found but not confirmed yet
        self.sent = 0
        for camera in self.cameras:
            camera.on_people = self.on_people

    def stop(self):
        self.running = False
        for camera in self.cameras:
            camera.on_people = None
            camera.worker.pose(None)
        self.stop_recording()

    def start_recording(self, path, calibration):
        """Starts the tracking log at path; calibration: the poses the tracker was given."""
        lenses = {c.device_id: {"number": self.poses[c.device_id][0], "address": str(c.address), "lens": c.lens}
                  for c in self.cameras}
        header = {"tracking_log": 1, "made": time.strftime("%Y-%m-%d %H:%M:%S"), "cameras": lenses,
                  "calibration": calibration, "unreal": [self.settings["unreal_address"], self.settings["moverse_port"]]}
        self.recorder = Recorder(path, json.loads(json.dumps(header, default=float)))

    def stop_recording(self):
        recorder, self.recorder = self.recorder, None
        if recorder:
            recorder.close()

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
        recorder = self.recorder
        if recorder:
            logged = [[[float(v) for v in box], points.tolist(), float(score)] for box, points, score in people]
            arrival = time.perf_counter()
        with self.wake:
            previous = self.views.get(camera.device_id)
            if previous is not None and 0 < captured - previous[0] < 1.0:
                last = self.intervals.get(camera.device_id, captured - previous[0])
                self.intervals[camera.device_id] = 0.8 * last + 0.2 * (captured - previous[0])
            self.views[camera.device_id] = (captured, seen)
            self.version += 1
            if recorder:  # in the order the tracker gets them, numbered as it counts them
                recorder.put({"p": arrival, "v": self.version, "d": camera.device_id, "c": captured, "people": logged})
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
        last_error = None
        while self.running:
            with self.wake:
                self.wake.wait(0.1)
            wait = MIN_INTERVAL - (time.perf_counter() - last_update)
            if wait > 0:
                time.sleep(wait)
            now = last_update = time.perf_counter()
            try:
                changed = self.update(now)
            except Exception:  # an error must not stop the tracking silently: log it (once) and go on
                error = traceback.format_exc()
                if error != last_error:
                    self.log(f"tracking: error in combining, still running:\n{error}")
                    last_error = error
                continue
            recorder = self.recorder
            if recorder:
                recorder.flush()
            if not changed:
                continue
            try:
                if now - last_subject > 1.0:  # sent every second, so Unreal can start at any time
                    sock.sendto(subject, address)
                    last_subject = now
                sock.sendto(frame_packet(self.position, offset), address)
                if self.sent == 0:
                    self.log(f"tracking: first packet sent to {address[0]}:{address[1]}{self.sender(address)}")
                self.sent += 1
            except OSError as error:
                self.log(f"tracking: send failed: {error}")
                time.sleep(0.5)

    def sender(self, address):
        """' from <this PC's address>' the packets leave from (the system picks it by the route to the
        Unreal PC), with a warning when it is on the cameras' network."""
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(address)
            local = probe.getsockname()[0]
            probe.close()
        except OSError:
            return ""
        prefix = local.rsplit(".", 1)[0] + "."
        if any(str(camera.address).startswith(prefix) for camera in self.cameras):
            return f" from {local}: that is the cameras' network, the packets likely do not reach the Unreal PC"
        return f" from this PC's address {local}"

    def update(self, now):
        """One combining step (now: the time on time.perf_counter()); True when there is a head position of
        the main person to send (self.position, also when it stays where it was: standing still)."""
        with self.wake:
            if self.version == self.used:
                return False
            self.used = self.version
            if self.recorder:
                self.recorder.put({"u": now, "v": self.used})
            views = list(self.views.values())
            window = min(SAME_TIME[1], max(SAME_TIME[0], 1.1 * max(self.intervals.values(), default=0.0)))
        if not views:  # no camera has delivered yet (this stopped the tracker in the lab, 2026-11-10)
            return False
        newest = max(captured for captured, _ in views)
        seen = [person for captured, people in views if newest - captured <= window for person in people]
        # The pictures are combined at the middle of their capture times, each line moved along the person's
        # velocity to it: an error in that velocity moves the older and the newer ones apart, not all ahead
        # (combined at the newest one, the head ran past where a person stopped: 9 cm at 80 ms per picture)
        moment = float(np.mean([captured for captured, _ in views if newest - captured <= window]))
        updated = self.locate(seen, moment, now)
        self.combined = len({person["camera"] for person in seen})
        if now - self.watched > 1.0:
            self.watch(moment)
            self.watched = now
        self.pending = sum(not track["confirmed"] for track in self.tracks.values())
        main = self.choose_main(now)
        if main is None or main not in updated:
            if now - self.last_seen > LOST_AFTER:
                self.position = self.motion = None
                self.filter.reset()  # start fresh when someone comes back
            return False
        if newest <= self.last_time:
            return False
        if main != self.last_main:
            self.filter.reset()  # another person: no gliding from the old one's position
            self.last_main = main
        self.last_seen, self.last_time = now, newest
        self.position = self.filter(self.tracks[main]["position"], moment, now)
        self.motion = self.filter.state
        self.times = [t for t in self.times if now - t < 1.0] + [now]
        self.rate = len(self.times)
        self.ages = [(s, a) for s, a in self.ages if now - s < 1.0] + [(now, now - newest)]
        self.age = 1000 * float(np.median([a for _, a in self.ages]))
        if self.recorder:
            self.recorder.put({"s": now, "m": moment, "main": main, "state": self.motion, "pos": self.position.tolist(),
                               "raw": self.tracks[main]["position"].tolist()})
        return True

    def watch(self, t):
        """Calibration watch: per camera the mean offset of its lines of sight from the triangulated face points
        over the last WATCH_SPAN s, in degrees; marks (and logs once) a camera off by more than WATCH_DEGREES."""
        angles = {}
        for number, gaps in self.gaps.items():
            while gaps and t - gaps[0][0] > WATCH_SPAN:
                gaps.popleft()
            if len(gaps) >= 100 and gaps[-1][0] - gaps[0][0] >= WATCH_SPAN * 2 / 3:  # judged on 20 s or more
                offset = np.array([(x, y) for _, x, y in gaps]).mean(0)
                angles[number] = math.degrees(float(np.linalg.norm(offset)))
        moved = {number for number, angle in angles.items() if angle > WATCH_DEGREES}
        for number in sorted(moved - self.moved):
            self.log(f"tracking: camera {number} points {angles[number]:.1f} degrees beside where the other cameras see "
                     f"the people: moved? Calibrate again.")
        self.agreement, self.moved = angles, moved

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
                     "offsets": {}, "path": collections.deque(), "hits": 0, "seen_by": set(), "held": 0, "confirmed": False}
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

    def head(self, track, people, t):
        """(head position, whether from both eyes) of one person from the lines of sight of their face points,
        or None."""
        points = {}
        for k in FACE:
            lines = []
            for person in people:
                line = person["face"].get(k)
                if line is not None:  # moved along the person's velocity to the moment t
                    lines.append(dict(line, origin=line["origin"] + track["velocity"] * (t - line["captured"]),
                                      camera=person["camera"]))
            if len(lines) >= 2:
                point = robust_point(lines)
                if point is not None:
                    points[k] = point
                    if len(lines) >= 3:  # calibration watch (with two lines both are off equally)
                        for line in lines:
                            turn = self.turns[line["camera"]]
                            to_point, along = turn.T @ (point - line["origin"]), turn.T @ line["direction"]
                            if to_point[2] > 0:  # in the camera's picture: where the point is, where it was seen
                                self.gaps[line["camera"]].append(
                                    (t, *(to_point[:2] / to_point[2] - along[:2] / along[2])))
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
        """Where a new person can be: inside the area the cameras surround (else a reflection or an object) and
        not on or behind the LED wall (the side cameras see Frank on it as a person)."""
        if WALL_EDGE_Y[0] - AREA_MARGIN <= point[1] <= WALL_EDGE_Y[-1] + AREA_MARGIN and \
                point[0] > np.interp(point[1], WALL_EDGE_Y, WALL_EDGE_X) - WALL_CLEARANCE:
            return False
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
        path = track["path"]
        path.append((t, head))
        while path and t - path[0][0] > VELOCITY_SPAN:
            path.popleft()
        velocity = line_fit(list(path), t)[1]  # a straight line: less noisy than from two positions
        speed = float(np.linalg.norm(velocity))
        # Slower than the noise of the measurements: standing (else the lines would shake with the noise)
        share = min(1.0, max(0.0, (speed - VELOCITY_DEAD) / VELOCITY_DEAD)) * min(1.0, 300.0 / speed) if speed > 0 else 0.0
        track["velocity"] = velocity * share
        track.update(position=head, time=t, seen=now, cameras=sorted(cameras))
        track["hits"] += 1
        track["seen_by"].update(cameras)
        if track["hits"] >= CONFIRM and len(track["seen_by"]) >= NEW_CAMERAS:
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
