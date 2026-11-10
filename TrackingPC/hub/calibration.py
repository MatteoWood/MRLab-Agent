"""Calibration of the cameras with the checkerboard (hub page "Calibration").

Finds where each camera is and where it points, in tracking space as NDC_Basic uses it (cm; X towards the
wall, Y to the right seen facing the wall, Z up), and each camera's focal length and picture centre; the
lens distortion comes from the camera itself (factory calibration).

1. Walk: someone walks through the space holding the board (BOARD inner corners, SQUARE cm squares) and
   turns it towards different cameras. Every SHOT_INTERVAL the hub finds the board's corners in each
   camera's pictures around one moment, interpolated to that moment (board_at). A moment where two or more
   cameras see the board tells how those cameras sit relative to each other.
2. Floor: the board lies flat on the floor, face up, its long side parallel to the wall and centred on
   the wall's middle; the distance from the bottom of the wall to the near edge of the black and white
   pattern is measured. This ties the cameras to the wall.
3. Solve: each camera's focal length and picture centre from its own views (measure_lens); then first
   guesses from the moments two cameras share (from the camera with the most shared moments
   outwards), then all camera positions and board positions are refined together so the board corners land
   where the cameras saw them (in turns: each board with the cameras fixed, each camera with the boards
   fixed). Views that fit badly are dropped.
4. Score (0 to 100): per camera from how far, in pixels, the corners land from where the camera saw them
   (0.3 px or less: full marks, 2 px or more: none), how many views it had, and, for cameras with a measured
   height (KNOWN_HEIGHTS), whether its height comes out as measured; the total is the mean over all cameras.
"""
import collections
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

BOARD = (10, 7)    # inner corners of the lab's board: 11 x 8 squares
SQUARE = 6.5       # cm
# Board frame: as the board is seen with its long side horizontal and its light corner square top left:
# x along the long side (to the right), y along the short side (down), z into the board.
BOARD_POINTS = np.array([[i * SQUARE, j * SQUARE, 0.0] for j in range(BOARD[1]) for i in range(BOARD[0])])
WALL_X, WALL_Y = 309.0, 16.0  # middle of the LED wall at the floor, tracking space (README 4.3)
KNOWN_HEIGHTS = {1: 314.0}     # cm, measured by the owner (2026-11-10); the cameras do not all hang at one height
FRONT_CAMERAS = (1, 2, 6)      # cameras at the wall: they tell on which side of the floor board the wall is
SHOT_INTERVAL = 0.25           # s between moments taken
SAME_MOMENT = 0.002            # s: a picture this close to a moment is used as it is, else two are interpolated
MAX_GAP = 0.04                 # s: the two pictures around a moment at most this far apart (one dropped picture)
MAX_STEP = 25.0                # px: the board moved more than this between them: too fast, not used
MIN_SHARED = 3                 # moments two cameras must share to be linked
GOOD_VIEWS = 20                # views a camera needs for full marks
MAX_VIEW_ERROR = 3.0           # px: views that fit worse (or worse than 3 x the median) are dropped
FLOOR_SECONDS = 2.0
MIN_LENS_VIEWS = 30            # views a camera needs to measure its own focal length and picture centre


# ---------- lens and board ----------

def normalize(points, lens):
    """Pixels (N, 2) of a camera's full-size picture to normalized image coordinates (N, 2): x / z and
    y / z of the direction the pixel looks in, with the lens distortion removed."""
    matrix, distortion = np.array(lens["matrix"], float), np.array(lens["distortion"], float)
    points = np.asarray(points, np.float64).reshape(-1, 1, 2)
    if lens["fisheye"]:
        out = cv2.fisheye.undistortPoints(points, matrix, distortion[:4])
    elif distortion.size and np.any(distortion):
        # more steps than undistortPoints' default 5: the wide lens bends the picture edges strongly
        criteria = (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 40, 1e-10)
        out = cv2.undistortPointsIter(points, matrix, distortion, None, None, criteria)
    else:
        out = cv2.undistortPoints(points, matrix, None)
    return out.reshape(-1, 2)


def measure_lens(views, lens, most=40):
    """(lens, text): the camera's focal length and picture centre measured from its own board views (pixels),
    the lens distortion kept as the camera reports it (distortion is set in normalized coordinates, so it
    stays right when the picture is a scaled or cropped version of what the factory calibrated). In the lab
    the cameras' own lens data made the space about 4 % too large (2026-11-10). The camera's values are kept
    with fewer than MIN_LENS_VIEWS views or when the measured focal length is more than 15 % off. Uses `most`
    views spread over the walk: 40 views took 2 s and gave the focal length within 0.1 % in a simulation,
    100 took 77 s for no better result."""
    old = np.array(lens["matrix"], float)
    if len(views) < MIN_LENS_VIEWS:
        return lens, "lens as the camera reports it (too few views to measure it)"
    views = views[::max(1, len(views) // most)][:most]
    objects = [BOARD_POINTS.astype(np.float32).reshape(-1, 1, 3) for _ in views]
    images = [np.asarray(v, np.float32).reshape(-1, 1, 2) for v in views]
    size = tuple(int(s) for s in lens["size"])
    distortion = np.array(lens["distortion"], float)
    criteria = (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 100, 1e-9)
    try:
        if lens["fisheye"]:
            f = cv2.fisheye
            flags = (f.CALIB_USE_INTRINSIC_GUESS | f.CALIB_RECOMPUTE_EXTRINSIC | f.CALIB_FIX_SKEW
                     | f.CALIB_FIX_K1 | f.CALIB_FIX_K2 | f.CALIB_FIX_K3 | f.CALIB_FIX_K4)
            _, new, _, _, _ = f.calibrate(objects, images, size, old.copy(), distortion[:4].reshape(4, 1).copy(),
                                          flags=flags, criteria=criteria)
        else:
            full = np.zeros(14)
            full[:min(14, distortion.size)] = distortion[:14]
            flags = (cv2.CALIB_USE_INTRINSIC_GUESS | cv2.CALIB_FIX_ASPECT_RATIO | cv2.CALIB_FIX_TANGENT_DIST
                     | cv2.CALIB_FIX_K1 | cv2.CALIB_FIX_K2 | cv2.CALIB_FIX_K3 | cv2.CALIB_FIX_K4 | cv2.CALIB_FIX_K5
                     | cv2.CALIB_FIX_K6 | cv2.CALIB_RATIONAL_MODEL | cv2.CALIB_THIN_PRISM_MODEL
                     | cv2.CALIB_FIX_S1_S2_S3_S4 | cv2.CALIB_TILTED_MODEL | cv2.CALIB_FIX_TAUX_TAUY)
            _, new, _, _, _ = cv2.calibrateCamera(objects, images, size, old.copy(), full, flags=flags, criteria=criteria)
    except cv2.error as error:
        return lens, f"lens as the camera reports it (measuring failed: {error.msg})"
    change = new[0, 0] / old[0, 0] - 1
    if abs(change) > 0.15:
        return lens, f"lens as the camera reports it (measured focal length {change * 100:+.0f} %, not plausible)"
    measured = dict(lens, matrix=new.tolist())
    return measured, f"focal length {new[0, 0]:.1f} px (camera: {old[0, 0]:.1f}, {change * 100:+.1f} %)"


def find_board(gray):
    """The board's inner corners (70, 2) in pixels, in BOARD_POINTS order, or None."""
    found, corners = cv2.findChessboardCornersSB(gray, BOARD, flags=cv2.CALIB_CB_NORMALIZE_IMAGE)
    if not found:
        return None
    grid = corners.reshape(BOARD[1], BOARD[0], 2).astype(np.float64)
    a, b = grid[0, 1] - grid[0, 0], grid[1, 0] - grid[0, 0]
    if a[0] * b[1] - a[1] * b[0] < 0:  # rows listed the other way round (mirrored): turn them
        grid = grid[:, ::-1]
    corners = grid.reshape(-1, 2)
    if brightness(gray, corners, 0) < brightness(gray, corners, 1):
        corners = corners[::-1].copy()  # counted from the other end: the first square must be the light one
    return corners


def brightness(gray, corners, i):
    """Mean brightness in the middle of the square right of and below corner i."""
    square = corners[[i, i + 1, i + BOARD[0], i + 1 + BOARD[0]]]
    x, y = np.round(square.mean(0)).astype(int)
    r = max(1, int(np.linalg.norm(square[1] - square[0]) / 5))
    patch = gray[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1]
    return float(patch.mean()) if patch.size else 0.0


# ---------- poses (4 x 4 matrices mapping points from one frame to another) ----------

def matrix(rvec, tvec):
    m = np.eye(4)
    m[:3, :3] = cv2.Rodrigues(np.asarray(rvec, float).reshape(3))[0]
    m[:3, 3] = np.asarray(tvec, float).reshape(3)
    return m


def vector(m):
    return np.concatenate([cv2.Rodrigues(m[:3, :3])[0].ravel(), m[:3, 3]])


def inverse(m):
    out = np.eye(4)
    out[:3, :3] = m[:3, :3].T
    out[:3, 3] = -m[:3, :3].T @ m[:3, 3]
    return out


def view_pose(normalized):
    """Board to camera from one view (normalized corners)."""
    ok, rvec, tvec = cv2.solvePnP(BOARD_POINTS, normalized, np.eye(3), None, flags=cv2.SOLVEPNP_IPPE)
    return matrix(rvec, tvec)


def errors(points, camera, normalized, focal):
    """Pixel distance of each point (N, 3 in the reference frame) from where the camera saw it."""
    seen = points @ camera[:3, :3].T + camera[:3, 3]
    return np.linalg.norm(seen[:, :2] / seen[:, 2:3] - normalized, axis=1) * focal


def refine_board(board, observations, rounds=8):
    """Board-to-reference pose that best fits all cameras that saw it: [(camera, normalized, focal)]
    with camera = reference-to-camera pose. Gauss-Newton on the six pose numbers."""
    def residuals(x):
        points = BOARD_POINTS @ cv2.Rodrigues(x[:3])[0].T + x[3:]
        out = []
        for camera, normalized, focal in observations:
            seen = points @ camera[:3, :3].T + camera[:3, 3]
            out.append(((seen[:, :2] / seen[:, 2:3] - normalized) * focal).ravel())
        return np.concatenate(out)

    x = vector(board)
    for _ in range(rounds):
        r = residuals(x)
        jacobian = np.empty((r.size, 6))
        for k in range(6):
            dx = np.zeros(6)
            dx[k] = 1e-6
            jacobian[:, k] = (residuals(x + dx) - r) / 1e-6
        step = np.linalg.lstsq(jacobian, -r, rcond=None)[0]
        x = x + step
        if np.linalg.norm(step) < 1e-8:
            break
    return matrix(x[:3], x[3:])


def mean_pose(poses):
    rotation = np.mean([p[:3, :3] for p in poses], axis=0)
    u, _, vt = np.linalg.svd(rotation)
    out = np.eye(4)
    out[:3, :3] = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
    out[:3, 3] = np.mean([p[:3, 3] for p in poses], axis=0)
    return out


def medoid(poses):
    """The pose closest to all others (robust first guess from many noisy ones)."""
    def distance(a, b):
        angle = np.arccos(np.clip((np.trace(a[:3, :3].T @ b[:3, :3]) - 1) / 2, -1, 1))
        return np.linalg.norm(a[:3, 3] - b[:3, 3]) + 50.0 * angle  # 1 radian counts like 50 cm
    return min(poses, key=lambda a: sum(distance(a, b) for b in poses))


# ---------- collecting ----------

def board_at(history, moment):
    """The board's corners at the moment, from one camera's pictures [(capture time, jpeg)], or None.

    The cameras do not take their pictures at the same instant (at 60 fps up to 8 ms apart from any moment)
    and the board moves: in the lab, pictures up to 12 ms apart gave about 1 px of error. So the corners are
    interpolated between the camera's pictures just before and just after the moment; a picture within
    SAME_MOMENT of it is used as it is. The second picture is searched only when the first shows the board."""
    before = max((h for h in history if h[0] <= moment), key=lambda h: h[0], default=None)
    after = min((h for h in history if h[0] > moment), key=lambda h: h[0], default=None)
    near = sorted((h for h in (before, after) if h is not None), key=lambda h: abs(h[0] - moment))
    if not near:
        return None
    first = find_board(cv2.imdecode(np.frombuffer(near[0][1], np.uint8), cv2.IMREAD_GRAYSCALE))
    if first is None or abs(near[0][0] - moment) <= SAME_MOMENT:
        return first
    if len(near) < 2 or after[0] - before[0] > MAX_GAP:
        return None
    second = find_board(cv2.imdecode(np.frombuffer(near[1][1], np.uint8), cv2.IMREAD_GRAYSCALE))
    if second is None:
        return None
    early, late = (first, second) if near[0] is before else (second, first)
    if np.mean(np.linalg.norm(late - early, axis=1)) > MAX_STEP:
        return None  # moved too fast to trust
    return early + (late - early) * (moment - before[0]) / (after[0] - before[0])


class Collector(threading.Thread):
    """Takes the pictures the cameras took at the same moments and finds the board in them.

    cameras: [(number, Camera)] streaming; mode "walk" (keeps moments seen by 2+ cameras) or "floor"
    (moments seen by 1+ cameras, for FLOOR_SECONDS)."""

    def __init__(self, cameras, mode, log=print):
        super().__init__(daemon=True)
        self.cameras, self.mode, self.log = cameras, mode, log
        self.running = True
        self.shots = []                       # [{number: corners in pixels (70, 2)}]
        self.views = collections.Counter()    # number -> views kept
        self.partners = collections.defaultdict(set)  # number -> cameras it saw the board together with
        self.seen = {}                        # number -> when the board was last found in its picture
        self.checked = 0                      # moments looked at

    def run(self):
        pool = ThreadPoolExecutor(max(1, len(self.cameras)))
        end = time.perf_counter() + FLOOR_SECONDS
        while self.running and (self.mode == "walk" or time.perf_counter() < end):
            started = time.perf_counter()
            moment = started - 0.05  # a little in the past, so every camera has pictures before and after it
            numbers = [number for number, _ in self.cameras]
            found = pool.map(lambda camera: board_at(list(camera.history), moment), [c for _, c in self.cameras])
            shot = {number: corners for number, corners in zip(numbers, found) if corners is not None}
            self.checked += 1
            for number in shot:
                self.seen[number] = time.perf_counter()
            if len(shot) >= (2 if self.mode == "walk" else 1):
                self.shots.append(shot)
                for number in shot:
                    self.views[number] += 1
                    self.partners[number] |= set(shot) - {number}
            time.sleep(max(0.0, SHOT_INTERVAL - (time.perf_counter() - started)))
        pool.shutdown(wait=False)
        self.running = False


# ---------- solving ----------

def solve(walk, floor, cameras, distance):
    """Camera positions in tracking space.

    walk, floor: shots [{number: corners in pixels}]; cameras: {number: (device id, lens)};
    distance: cm from the bottom of the wall to the near edge of the board's pattern (floor shots).
    Returns {"cameras": {device id: {"number", "rotation" (camera to tracking, 3 x 3), "position" (cm),
    "error_px", "views", "score"}}, "score", "report" (lines of text)} or raises ValueError."""
    lenses, lens_notes = {}, {}
    for n, (_, lens) in cameras.items():
        lenses[n], lens_notes[n] = measure_lens([shot[n] for shot in walk if n in shot], lens)
    focal = {n: float(lens["matrix"][0][0]) for n, lens in lenses.items()}
    walk = [{n: normalize(c, lenses[n]) for n, c in shot.items() if n in cameras} for shot in walk]
    walk = [shot for shot in walk if len(shot) >= 2]
    floor = [{n: normalize(c, lenses[n]) for n, c in shot.items() if n in cameras} for shot in floor]
    floor = [shot for shot in floor if shot]
    if not walk:
        raise ValueError("no moment where two cameras saw the board: walk with the board first")
    if not floor:
        raise ValueError("no camera saw the board on the floor")

    # First guesses: each view gives the board's pose in that camera; two cameras sharing a moment give
    # their relative pose. Link cameras from the one with the most shared moments outwards.
    views = [{n: view_pose(c) for n, c in shot.items()} for shot in walk]
    shared = collections.defaultdict(list)
    for shot in views:
        for a in shot:
            for b in shot:
                if a != b:
                    shared[a, b].append(shot[a] @ inverse(shot[b]))  # b's frame to a's
    count = collections.Counter({n: sum(len(v) for (a, _), v in shared.items() if a == n) for n in cameras})
    reference = 1 if count[1] else count.most_common(1)[0][0]
    poses = {reference: np.eye(4)}  # number -> reference-to-camera pose
    while True:
        links = [(len(v), a, b) for (a, b), v in shared.items() if a in poses and b not in poses and len(v) >= MIN_SHARED]
        if not links:
            break
        _, a, b = max(links)
        poses[b] = inverse(medoid(shared[a, b])) @ poses[a]  # reference -> a -> b
    missing = sorted(set(cameras) - set(poses))
    if len(poses) < 2:
        raise ValueError(f"no two cameras saw the board together at {MIN_SHARED} or more moments: hold it high, within "
                         "about 2 to 3 m of two neighbouring cameras, facing both")

    # Refine everything together, in turns, dropping views that fit badly.
    used = [{n: c for n, c in shot.items() if n in poses} for shot in walk]
    used = [shot for shot in used if len(shot) >= 2]
    boards = []
    for shot in used:
        n = next(iter(shot))
        boards.append(inverse(poses[n]) @ view_pose(shot[n]))
    for round_ in range(20):
        boards = [refine_board(board, [(poses[n], c, focal[n]) for n, c in shot.items()]) for board, shot in zip(boards, used)]
        for n in poses:
            if n == reference:
                continue
            points = [BOARD_POINTS @ b[:3, :3].T + b[:3, 3] for b, shot in zip(boards, used) if n in shot]
            seen = [shot[n] for shot in used if n in shot]
            if not points:  # all its views were dropped: it keeps its first guess and scores 0
                continue
            rvec, tvec = cv2.Rodrigues(poses[n][:3, :3])[0], poses[n][:3, 3].copy()
            _, rvec, tvec = cv2.solvePnP(np.concatenate(points), np.concatenate(seen), np.eye(3), None, rvec, tvec,
                                         useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE)
            poses[n] = matrix(rvec, tvec)
        if round_ in (5, 11) and used:
            fits =[{n: float(np.sqrt(np.mean(errors(BOARD_POINTS @ b[:3, :3].T + b[:3, 3], poses[n], c, focal[n]) ** 2)))
                     for n, c in shot.items()} for b, shot in zip(boards, used)]
            limit = min(MAX_VIEW_ERROR, 3 * float(np.median([e for fit in fits for e in fit.values()])))
            kept = [({n: c for n, c in shot.items() if fit[n] <= max(limit, 0.5)}, b) for shot, fit, b in zip(used, fits, boards)]
            kept = [(shot, b) for shot, b in kept if len(shot) >= 2]
            used, boards = [s for s, _ in kept], [b for _, b in kept]

    # Floor: the board's pose from every camera that saw it, averaged over the moments.
    on_floor = []
    for shot in floor:
        known = {n: c for n, c in shot.items() if n in poses}
        if known:
            n = next(iter(known))
            guess = inverse(poses[n]) @ view_pose(known[n])
            on_floor.append(refine_board(guess, [(poses[k], c, focal[k]) for k, c in known.items()]))
    if not on_floor:
        raise ValueError("the board on the floor was seen only by cameras that could not be linked to the others")
    board = mean_pose(on_floor)
    floor_cameras = sorted({n for shot in floor for n in shot if n in poses})

    # Tracking space from the floor board: up (square to the board), floor height, the wall's direction (the
    # board's short side, towards the cameras at the wall) and position; Y = right seen facing the wall.
    # When only one camera saw the floor board, up is taken square to the plane through the cameras instead
    # (one far camera's view can be 1 degree off: 13 cm at far cameras in a simulation); that plane is only
    # level if the cameras hang at one height, which in the lab they do not (2026-11-10).
    centres = {n: inverse(p)[:3, 3] for n, p in poses.items()}
    centre = board[:3, :3] @ BOARD_POINTS.mean(0) + board[:3, 3]
    normal = board[:3, :3][:, 2]
    board_up = -normal if np.mean([(c - centre) @ -normal for c in centres.values()]) > 0 else normal
    up, tilt, from_board = board_up, None, len(floor_cameras) >= 2
    if len(centres) >= 3:
        spread = np.array(list(centres.values())) - np.mean(list(centres.values()), axis=0)
        _, sizes, axes = np.linalg.svd(spread)
        if sizes[1] > 100.0 * np.sqrt(len(centres)):  # the cameras span a plane (not one line)
            plane_up = axes[2] if axes[2] @ board_up > 0 else -axes[2]
            tilt = float(np.degrees(np.arccos(np.clip(plane_up @ board_up, -1, 1))))
            if not from_board:
                up = plane_up
    front = [n for n in FRONT_CAMERAS if n in centres] or list(centres)
    short = board[:3, :3][:, 1]
    x_axis = short if short @ (np.mean([centres[n] for n in front], axis=0) - centre) > 0 else -short
    x_axis = x_axis - (x_axis @ up) * up
    x_axis /= np.linalg.norm(x_axis)
    to_tracking = np.array([x_axis, np.cross(x_axis, up), up])  # rows: X, Y (right), Z; a mirror (det -1)
    offset = np.array([WALL_X - distance - BOARD[1] / 2 * SQUARE - SQUARE / 2, WALL_Y, 0.0])

    result, report = {}, []
    for n in sorted(cameras):
        device_id = cameras[n][0]
        if n not in poses:
            report.append(f"Camera {n}: not calibrated (did not see the board together with the other cameras often enough)")
            continue
        position = offset + to_tracking @ (centres[n] - centre)
        view_errors = [errors(BOARD_POINTS @ b[:3, :3].T + b[:3, 3], poses[n], shot[n], focal[n])
                       for b, shot in zip(boards, used) if n in shot]
        count_views = len(view_errors)
        error = float(np.sqrt(np.mean(np.concatenate(view_errors) ** 2))) if view_errors else float("inf")
        height_off = abs(position[2] - KNOWN_HEIGHTS[n]) if n in KNOWN_HEIGHTS else 0.0
        score = (100 * np.clip((2.0 - error) / 1.7, 0, 1) * min(1.0, count_views / GOOD_VIEWS)
                 * (1.0 if height_off <= 10 else 0.5 if height_off <= 25 else 0.0))
        result[device_id] = {
            "number": n, "rotation": (to_tracking @ inverse(poses[n])[:3, :3]).tolist(),
            "position": position.tolist(), "error_px": round(error, 2), "views": count_views, "score": round(float(score)),
            "matrix": [list(map(float, row)) for row in lenses[n]["matrix"]],  # the lens the tracker must use
        }
        report.append(f"Camera {n}: score {score:.0f}  |  {error:.2f} px  |  {count_views} views  |  at X {position[0]:.0f}, "
                      f"Y {position[1]:.0f}, height {position[2]:.0f} cm" + (f" (measured {KNOWN_HEIGHTS[n]:.0f})" if n in KNOWN_HEIGHTS else "")
                      + f"  |  {lens_notes[n]}")
    if 2 in poses and 6 in poses:
        gap = np.linalg.norm(centres[2] - centres[6]) / 100
        report.append(f"Check with a tape: cameras 2 and 6 (top left and right of the wall) are {gap:.2f} m apart.")
    total = float(np.mean([result[cameras[n][0]]["score"] if cameras[n][0] in result else 0 for n in cameras]))
    report.insert(0, f"Score {total:.0f} of 100  |  {len(used)} moments with 2+ cameras  |  floor board seen by camera(s) "
                     + ", ".join(str(n) for n in floor_cameras))
    if from_board or tilt is None:
        report.append("Up: square to the floor board" + (f"; the plane through the cameras lies {tilt:.1f} deg from it." if tilt is not None else "."))
    else:
        report.append(f"Up: square to the plane through the cameras (only one camera saw the floor board); the board lies {tilt:.1f} deg from it.")
    if missing:
        report.append("Not linked: camera(s) " + ", ".join(str(n) for n in missing) + ". Walk with the board where they "
                      "and a neighbouring camera both see it.")
    return {"cameras": result, "score": round(total), "report": report}
