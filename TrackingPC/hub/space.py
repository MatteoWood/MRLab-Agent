"""3D view of the lab (hub page "3D view"): floor grid, the LED wall, the calibrated cameras and every tracked person, live.

Tracking space as NDC_Basic uses it (cm; X towards the wall, Y to the right seen facing the wall, Z up).
The wall comes from led_wall.json (tools/led_wall_from_fbx.py). Each person is a glowing point at their
head with a light line down to a ring on the floor (to read the height), a trail of the last
TRAIL_SECONDS, and their number; the main person (whose head goes to Unreal) is bigger. Drag with the
mouse to turn the view around the lab and tilt it; nothing else moves the camera.
Drawn with QPainter, no OpenGL needed. The grid and the wall are drawn as thin lines and get their glow
from a blurred copy added on top (bloom, with OpenCV); that picture is made again only when the view turns
(about 25 ms). Each frame paints it plus the people (a few ms). Drawing the glow as wide soft lines with
QPainter took 0.7 s per frame (laptop, 2026-11-10).
"""
import collections
import json
import math
import pathlib
import time

import cv2
import numpy as np
from PySide6.QtCore import QLineF, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

WALL = json.loads(pathlib.Path(__file__).with_name("led_wall.json").read_text())
TARGET = np.array([150.0, 16.0, 120.0])  # the view turns around this point: in front of the wall, low
DISTANCE = 950.0                          # cm from the camera to TARGET
FOV = 50.0                                # degrees, vertically
NEAR = 10.0
TRAIL_SECONDS = 2.5
# Minimal style: thin lines, muted colours, only a trace of glow.
BACKGROUND = QColor(5, 7, 11)
WALL_COLOUR = QColor(150, 200, 240)   # pale ice blue
GRID_COLOUR = QColor(110, 140, 180)
CAMERA_COLOUR = QColor(200, 205, 215)  # calibrated cameras: a dot and a line where they look
CAMERA_LINE = 45.0                     # cm
GRID_FADE = 420.0  # cm from the middle of the floor where the grid has faded out
BLOOM = 0.45       # strength of the glow added to the grid and the wall
PEOPLE_COLOURS = [QColor(240, 130, 170), QColor(240, 180, 110), QColor(150, 210, 150), QColor(230, 215, 130),
                  QColor(170, 160, 240), QColor(235, 120, 120), QColor(120, 205, 210)]


def floor_grid():
    """Floor lines every 50 cm (every 100 cm a little brighter), cut into 25 cm pieces, each with a brightness
    that fades with the distance from the middle of the floor: [(segments, alpha)], grouped by brightness."""
    centre = np.array([0.0, 16.0])
    groups = {}
    lines = [((x, -384), (x, 416), x % 100 == 0) for x in range(-350, 301, 50)]
    lines += [((-350, y), (300, y), (y - 16) % 100 == 0) for y in range(-384, 417, 50)]
    for start, end, major in lines:
        start, end = np.array(start, float), np.array(end, float)
        pieces = max(1, int(np.linalg.norm(end - start) // 25))
        for i in range(pieces):
            a, b = start + (end - start) * i / pieces, start + (end - start) * (i + 1) / pieces
            fade = max(0.0, 1.0 - (np.linalg.norm((a + b) / 2 - centre) / GRID_FADE) ** 2)
            alpha = round((0.22 if major else 0.11) * fade, 3)
            if alpha > 0.005:
                groups.setdefault(alpha, []).append([a[0], a[1], 0, b[0], b[1], 0])
    return [(np.array(segments), alpha) for alpha, segments in groups.items()]


GRID = floor_grid()
WALL_PANELS = np.array(WALL["panels"], float)
WALL_OUTLINE = np.array(WALL["outline"], float)


def faded(colour, alpha):
    c = QColor(colour)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


class Space(QWidget):
    def __init__(self, people, cameras):
        """people: function returning [(number, is_main, position as array (x, y, z) in cm)];
        cameras: function returning [(number, position, looking direction)] of the calibrated cameras."""
        super().__init__()
        self.people, self.cameras = people, cameras
        self.yaw, self.pitch = -35.0, 10.0  # degrees: seen from behind the visitors, to the left, about 3 m up
        self.drag = None
        self.cache, self.cache_key = None, None  # grid and wall with their glow, for the current view
        self.trails = collections.defaultdict(collections.deque)  # number -> (time, position)
        self.setMinimumSize(400, 300)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.timer = QTimer(self, interval=33, timeout=self.update)  # about 30 frames a second while shown

    def showEvent(self, event):
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()

    def mousePressEvent(self, event):
        self.drag = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        self.drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseMoveEvent(self, event):
        if self.drag is None:
            return
        delta = event.position() - self.drag
        self.drag = event.position()
        self.yaw -= delta.x() * 0.3
        self.pitch = max(3.0, min(85.0, self.pitch + delta.y() * 0.3))
        self.update()

    # ---------- projection ----------

    def camera(self):
        yaw, pitch = math.radians(self.yaw), math.radians(self.pitch)
        eye = TARGET + DISTANCE * np.array([-math.cos(pitch) * math.cos(yaw), -math.cos(pitch) * math.sin(yaw), math.sin(pitch)])
        forward = (TARGET - eye) / np.linalg.norm(TARGET - eye)
        # Tracking space is left-handed (X forward, Y right, Z up): right = up x forward keeps it unmirrored.
        right = np.cross([0.0, 0.0, 1.0], forward)
        right /= np.linalg.norm(right)
        up = np.cross(forward, right)
        focal = (self.height() / 2) / math.tan(math.radians(FOV) / 2)
        return eye, forward, right, up, focal

    def to_screen(self, points, view):
        """(N, 3) points to (N, 2) pixels and their depth; points behind the camera get depth <= NEAR."""
        eye, forward, right, up, focal = view
        d = points - eye
        z = d @ forward
        safe = np.where(z > NEAR, z, NEAR)
        x = self.width() / 2 + focal * (d @ right) / safe
        y = self.height() / 2 - focal * (d @ up) / safe
        return np.column_stack([x, y]), z

    def segments(self, lines, view):
        """(N, 6) segments in cm to QLineF, cut where they pass behind the camera."""
        a, b = lines[:, :3].copy(), lines[:, 3:].copy()
        eye, forward = view[0], view[1]
        za, zb = (a - eye) @ forward, (b - eye) @ forward
        keep = (za > NEAR) | (zb > NEAR)
        a, b, za, zb = a[keep], b[keep], za[keep], zb[keep]
        cut = a + ((NEAR - za) / np.where(zb != za, zb - za, 1.0))[:, None] * (b - a)  # where the line meets NEAR
        a, b = np.where((za < NEAR)[:, None], cut, a), np.where((zb < NEAR)[:, None], cut, b)
        pa, _ = self.to_screen(a, view)
        pb, _ = self.to_screen(b, view)
        return [QLineF(x1, y1, x2, y2) for (x1, y1), (x2, y2) in zip(pa, pb)]

    # ---------- drawing ----------

    @staticmethod
    def line(painter, lines, colour, width, alpha):
        # flat ends: round ends of neighbouring trail pieces overlap and add up to bright beads
        painter.setPen(QPen(faded(colour, alpha), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        painter.drawLines(lines)

    @staticmethod
    def light(painter, centre, radius, colour):
        """An LED dot: small bright core, faint halo."""
        gradient = QRadialGradient(centre, radius * 2.2)
        gradient.setColorAt(0.0, faded(QColor(255, 255, 255), 0.9))
        gradient.setColorAt(0.3, faded(colour, 0.85))
        gradient.setColorAt(0.45, faded(colour, 0.12))
        gradient.setColorAt(1.0, faded(colour, 0.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(centre, radius * 2.2, radius * 2.2)

    def scenery(self, view):
        """Grid and wall with their glow for the current view (made again only when the view changes)."""
        w, h = self.width(), self.height()
        key = (self.yaw, self.pitch, w, h)
        if key == self.cache_key:
            return self.cache
        image = QImage(w, h, QImage.Format.Format_RGB32)
        image.fill(BACKGROUND)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        layers = [(lines, faded(GRID_COLOUR, alpha), 0.8) for lines, alpha in GRID]
        layers += [(WALL_PANELS, faded(WALL_COLOUR, 0.22), 0.6), (WALL_OUTLINE, faded(WALL_COLOUR, 0.9), 1.1)]
        for lines, colour, width in layers:
            painter.setPen(QPen(colour, width))
            painter.drawLines(self.segments(lines, view))
        painter.end()
        pixels = np.frombuffer(image.constBits(), np.uint8).reshape(h, image.bytesPerLine() // 4, 4)[:, :w, :3]
        small = cv2.resize(pixels, (max(1, w // 4), max(1, h // 4)), interpolation=cv2.INTER_AREA)
        small = cv2.subtract(small, np.full_like(small, (BACKGROUND.blue(), BACKGROUND.green(), BACKGROUND.red())))  # glow from the lines only
        glow = cv2.resize(cv2.GaussianBlur(small, (0, 0), 1.5), (w, h), interpolation=cv2.INTER_LINEAR)
        lit = np.ascontiguousarray(cv2.addWeighted(pixels, 1.0, glow, BLOOM, 0))
        # in the screen's own format, so painting it each frame needs no conversion
        self.cache = QImage(lit.data, w, h, w * 3, QImage.Format.Format_BGR888).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self.cache_key = key
        return self.cache

    def paintEvent(self, event):
        painter = QPainter(self)
        view = self.camera()
        painter.drawImage(0, 0, self.scenery(view))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)

        now = time.monotonic()
        seen = set()
        people = sorted(self.people(), key=lambda p: p[1])  # the main person drawn last, on top
        for number, main, position in people:
            seen.add(number)
            trail = self.trails[number]
            if not trail or np.linalg.norm(trail[-1][1] - position) > 0.5:
                trail.append((now, np.array(position, float)))
        for number in list(self.trails):
            trail = self.trails[number]
            while trail and now - trail[0][0] > TRAIL_SECONDS:
                trail.popleft()
            if not trail:
                del self.trails[number]

        painter.setFont(QFont("Segoe UI", 8))
        for number, position, direction in self.cameras():  # where the calibration put the cameras
            ends = np.array([[*position, *(position + CAMERA_LINE * direction)]])
            self.line(painter, self.segments(ends, view), CAMERA_COLOUR, 1.0, 0.7)
            (pixel,), (depth,) = self.to_screen(np.asarray(position, float)[None], view)
            if depth > NEAR:
                self.light(painter, QPointF(*pixel), max(2.0, view[4] * 3.0 / depth), CAMERA_COLOUR)
                painter.setPen(faded(CAMERA_COLOUR, 0.8))
                painter.drawText(QPointF(pixel[0] + 7, pixel[1] - 5), str(number))
        for number, main, position in people:
            colour = PEOPLE_COLOURS[(number - 1) % len(PEOPLE_COLOURS)]
            trail = self.trails[number]
            if len(trail) > 1:  # the trail fades out over TRAIL_SECONDS
                points = np.array([p for _, p in trail])
                ages = np.array([now - t for t, _ in trail])
                pixels, depth = self.to_screen(points, view)
                for i in range(1, len(points)):
                    if depth[i] > NEAR and depth[i - 1] > NEAR:
                        line = [QLineF(*pixels[i - 1], *pixels[i])]
                        self.line(painter, line, colour, 1.4 if main else 1.0, 0.8 * (1.0 - ages[i] / TRAIL_SECONDS))
            head = np.array(position, float)
            floor = head * np.array([1, 1, 0])
            ring = np.array([floor + [22 * math.cos(a), 22 * math.sin(a), 0] for a in np.linspace(0, 2 * math.pi, 33)])
            ring_lines = np.column_stack([ring[:-1], ring[1:]])
            self.line(painter, self.segments(ring_lines, view), colour, 0.8, 0.45)
            self.line(painter, self.segments(np.array([[*head, *floor]]), view), colour, 0.6, 0.25)
            (pixel,), (depth,) = self.to_screen(head[None], view)
            if depth <= NEAR:
                continue
            focal = view[4]
            radius = max(2.5, focal * (5.5 if main else 3.5) / depth)  # cm to pixels at that distance
            self.light(painter, QPointF(*pixel), radius, colour)
            painter.setPen(faded(colour, 0.75))
            painter.drawText(QPointF(pixel[0] + radius * 1.8, pixel[1] - radius * 1.2), f"P{number}" + ("  main" if main else ""))

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setPen(QColor(90, 100, 118))
        painter.setFont(QFont("Segoe UI", 8))
        hint = "Drag to look around"
        if not people:
            hint += "  |  nobody tracked (start tracking on the Tracking page)"
        painter.drawText(QPointF(14, self.height() - 14), hint)
        painter.end()
