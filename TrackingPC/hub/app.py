"""MRLab Hub: the tracking PC program with a window (started by MRLabHub.exe).

Pages: Cameras (search, connect, the 8 camera pictures, choose the frontal camera for Frank's view),
Calibration (where the cameras are, with the checkerboard), Tracking (head position from all calibrated
cameras, sent to Unreal as Moverse packets), 3D view, Vision (the local vision model and Frank's view sent
to Unreal). Settings and the calibration are saved in hub.local.json next to MRLabHub.exe (not in Git).
Run from the folder: runtime\\python\\pythonw.exe -m hub [--webcam]   (--webcam: laptop testing)
"""
import collections
import ctypes
import json
import pathlib
import sys
import threading
import time

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton,
                               QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from hub import calibration, cameras, space, tracking, vision
from hub.ollama import OllamaServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "hub.local.json"
# Lab defaults (the Unreal PC address and the Moverse port, as Moverse uses them) live in the runtime folder,
# which comes by USB stick and is not in Git: the repo is public, lab addresses stay out of it (README D13).
LAB_DEFAULTS = ROOT / "runtime" / "defaults.json"
DEFAULTS = {
    "unreal_address": "", "vision_port": 0, "moverse_port": 0, "frontal_id": "", "model": vision.DEFAULT_MODEL,
    "filter_min_cutoff": 1.0, "filter_beta": 0.05,
    "floor_distance": 50.0,  # cm from the bottom of the wall to the board's pattern, calibration step 2
    "calibration": None,     # hub/calibration.py solve() result in use
}
PAGES = ["Cameras", "Calibration", "Tracking", "3D view", "Vision"]

ACCENT, OK, WARN, BAD, MUTED = "#3B82F6", "#3FB950", "#D29922", "#F85149", "#5A6070"
STYLE = """
* { font-family: "Segoe UI"; font-size: 10pt; color: #E6E8EC; }
QMainWindow, #page { background: #0F1115; }
#sidebar { background: #14171D; border-right: 1px solid #22262E; }
#brand { font-size: 15pt; font-weight: 600; }
#muted { color: #8A90A0; }
#small { color: #8A90A0; font-size: 9pt; }
#title { font-size: 18pt; font-weight: 600; }
#cardTitle { font-size: 11pt; font-weight: 600; }
#value { font-size: 15pt; font-weight: 600; font-family: "Consolas"; }
#nav { text-align: left; padding: 9px 14px; border: none; border-radius: 8px; color: #9AA1AE; background: transparent; }
#nav:checked { background: #1F2430; color: #FFFFFF; }
#nav:hover:!checked { background: #191D25; }
#card { background: #14171D; border: 1px solid #22262E; border-radius: 12px; }
#tile { background: #14171D; border: 1px solid #22262E; border-radius: 12px; }
#tileFrontal { background: #14171D; border: 1px solid #3B82F6; border-radius: 12px; }
#picture { background: #0A0C0F; border-radius: 8px; color: #5A6070; }
#badge { background: #1E3A6E; color: #BFD5FF; border-radius: 6px; padding: 1px 7px; font-size: 8pt; font-weight: 600; }
QPushButton { background: #222733; border: 1px solid #2C3240; border-radius: 8px; padding: 7px 14px; }
QPushButton:hover { background: #2A3040; }
QPushButton:disabled { color: #5A6070; background: #181B22; }
QPushButton#primary { background: #3B82F6; border: none; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #4C8DF7; }
QPushButton#primary:disabled { background: #22304A; color: #7A8AA8; }
QPushButton#stop { background: #3A1F24; border: 1px solid #5A2A30; color: #FF9A9A; font-weight: 600; }
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QPlainTextEdit {
    background: #0F1115; border: 1px solid #2C3240; border-radius: 6px; padding: 5px 8px; selection-background-color: #3B82F6; }
QDoubleSpinBox, QSpinBox { padding: 0px 8px; min-height: 30px; }
QAbstractSpinBox QLineEdit { padding: 0px; border: none; background: transparent; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width: 18px; border: none; background: transparent; }
QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow { width: 7px; height: 7px; }
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #3B82F6; }
QPlainTextEdit { font-family: "Consolas"; font-size: 9pt; }
QComboBox QAbstractItemView { background: #14171D; border: 1px solid #2C3240; selection-background-color: #1F2430; }
"""


def label(text="", name=None, wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def card(title=None):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 18)
    layout.setSpacing(10)
    if title:
        layout.addWidget(label(title, "cardTitle"))
    return frame, layout


def dot(color):
    widget = QLabel()
    widget.setFixedSize(9, 9)
    widget.setStyleSheet(f"background: {color}; border-radius: 4px;")
    return widget


def set_dot(widget, color):
    style = f"background: {color}; border-radius: 4px;"
    if widget.styleSheet() != style:
        widget.setStyleSheet(style)


def set_variant(widget, name):
    """Switch a widget to another style (object name) only when it changes."""
    if widget.objectName() != name:
        widget.setObjectName(name)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def to_pixmap(image, width, height):
    image = image.copy()
    qimage = QImage(image.data, image.shape[1], image.shape[0], image.strides[0], QImage.Format.Format_BGR888)
    return QPixmap.fromImage(qimage).scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


class ClickablePicture(QLabel):
    """Picture that reports clicks as fractions of the shown image (the image is centred and scaled to fit)."""

    def __init__(self, on_click):
        super().__init__()
        self.on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return
        x0, y0 = (self.width() - pixmap.width()) / 2, (self.height() - pixmap.height()) / 2
        x, y = (event.position().x() - x0) / pixmap.width(), (event.position().y() - y0) / pixmap.height()
        if 0 <= x <= 1 and 0 <= y <= 1:
            self.on_click(x, y)


class Tile(QFrame):
    """One camera: picture, name, address, status, frontal choice."""

    def __init__(self, number, on_frontal):
        super().__init__()
        self.setObjectName("tile")
        self.camera = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 12)
        layout.setSpacing(6)
        self.picture = label("no camera", "picture")
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setMinimumSize(240, 150)
        self.picture.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.picture, 1)
        top = QHBoxLayout()
        self.name = label(f"Camera {number}", "cardTitle")
        self.badge = label("FRONTAL", "badge")
        self.badge.hide()
        top.addWidget(self.name)
        top.addWidget(self.badge)
        top.addStretch()
        self.frontal_button = QPushButton("Use as frontal")
        self.frontal_button.clicked.connect(lambda: on_frontal(self.camera))
        self.frontal_button.setEnabled(False)
        top.addWidget(self.frontal_button)
        layout.addLayout(top)
        self.address = label("", "small")
        layout.addWidget(self.address)
        status = QHBoxLayout()
        self.dot = dot(MUTED)
        self.status = label("empty slot", "muted")
        status.addWidget(self.dot)
        status.addWidget(self.status, 1)
        layout.addLayout(status)

    def show_camera(self, camera, frontal):
        self.camera = camera
        self.frontal_button.setEnabled(camera is not None and not frontal)
        self.badge.setVisible(frontal)
        set_variant(self, "tileFrontal" if frontal else "tile")
        if camera is None:
            self.address.setText("")
            self.status.setText("empty slot")
            set_dot(self.dot, MUTED)
            self.picture.setPixmap(QPixmap())
            self.picture.setText("no camera")
            return
        product = f"{camera.product}  |  " if camera.product else ""
        self.address.setText(f"{product}ID {camera.device_id}  |  {camera.address}")
        text = camera.status
        if camera.status == "streaming":
            text += f"  |  {camera.fps:.0f} fps" + (f"  |  pose {camera.pose_ms:.0f} ms" if camera.pose_ms else "")
        self.status.setText(text)
        if camera.status in ("streaming", "found"):
            color = OK if camera.status == "streaming" else ACCENT
        elif camera.status.startswith(("error", "in use")):
            color = BAD
        else:
            color = MUTED if camera.status == "disconnected" else WARN  # starting, restarting
        set_dot(self.dot, color)
        if camera.preview is not None and camera.status == "streaming":
            self.picture.setPixmap(to_pixmap(camera.preview, self.picture.width(), self.picture.height()))
        else:
            self.picture.setPixmap(QPixmap())
            self.picture.setText(camera.status)


class Hub(QMainWindow):
    def __init__(self, webcam):
        super().__init__()
        self.webcam = webcam
        self.settings = dict(DEFAULTS)
        if LAB_DEFAULTS.exists():
            self.settings.update(json.loads(LAB_DEFAULTS.read_text()))
        if SETTINGS.exists():
            self.settings.update(json.loads(SETTINGS.read_text()))
        self.log_lines = collections.deque(maxlen=300)
        self.cameras, self.searching = [], False
        self.vision_store = vision.FrameStore()
        self.collector = None           # calibration.Collector while taking moments
        self.walk, self.floor = [], []  # calibration moments taken (step 1 and step 2)
        self.result, self.computing = None, False  # last computed calibration, not yet in use
        self.view_picked = False        # Tracking page camera choice set to the frontal camera once
        self.tracker = self.describer = self.sender = None
        self.vision_state = "off"
        self.ollama = OllamaServer()
        self.ollama_state = None
        self.ollama.start()

        self.setWindowTitle("MRLab Hub")
        self.resize(1360, 860)
        root = QWidget()
        self.setCentralWidget(root)
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.build_sidebar())
        self.pages = QStackedWidget()
        self.pages.addWidget(self.build_cameras())
        self.pages.addWidget(self.build_calibration())
        self.pages.addWidget(self.build_tracking())
        self.pages.addWidget(self.build_space())
        self.pages.addWidget(self.build_vision())
        row.addWidget(self.pages, 1)
        self.select_page(0)

        self.timer = QTimer(self, interval=100, timeout=self.refresh)
        self.timer.start()
        self.slow_timer = QTimer(self, interval=2000, timeout=self.check_ollama)
        self.slow_timer.start()
        self.check_ollama()
        self.search()

    # ---------- layout ----------

    def build_sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(16, 22, 16, 18)
        layout.setSpacing(4)
        layout.addWidget(label("MRLab Hub", "brand"))
        layout.addWidget(label("Tracking PC", "muted"))
        layout.addSpacing(22)
        self.nav = []
        for index, name in enumerate(PAGES):
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _, i=index: self.select_page(i))
            layout.addWidget(button)
            self.nav.append(button)
        layout.addStretch()
        self.side_status = {}
        for key in ["Cameras", "Calibration", "Tracking", "Vision", "Model"]:
            line = QHBoxLayout()
            indicator = dot(MUTED)
            text = label(key, "small")
            line.addWidget(indicator)
            line.addWidget(text, 1)
            layout.addLayout(line)
            self.side_status[key] = (indicator, text)
        return side

    def page(self, title, subtitle):
        widget = QWidget()
        widget.setObjectName("page")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(title, "title"))
        sub = label(subtitle, "muted")
        titles.addWidget(sub)
        head.addLayout(titles)
        head.addStretch()
        layout.addLayout(head)
        return widget, layout, head, sub

    def build_cameras(self):
        widget, layout, head, self.cameras_sub = self.page("Cameras", "Searching...")
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.search)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("primary")
        self.connect_button.clicked.connect(self.connect_cameras)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect_cameras)
        for button in (self.search_button, self.disconnect_button, self.connect_button):
            head.addWidget(button)
        layout.addWidget(label("Moverse must be closed: it holds the cameras. All cameras are used for tracking; "
                               "the frontal camera (blue frame) also gives Frank's view.", "muted", wrap=True))
        grid = QGridLayout()
        grid.setSpacing(14)
        self.tiles = []
        for i in range(8):
            tile = Tile(i + 1, self.use_as_frontal)
            grid.addWidget(tile, i // 4, i % 4)
            self.tiles.append(tile)
        layout.addLayout(grid, 1)
        return widget

    def number_field(self, key, low, high, decimals=1, step=1.0, integer=False):
        field = QSpinBox() if integer else QDoubleSpinBox()
        field.setRange(low, high)
        if not integer:
            field.setDecimals(decimals)
            field.setSingleStep(step)
        field.setValue(self.settings[key])
        # Hidden arrow buttons (NoButtons) would shrink the number to 1 pixel under this style sheet (Qt 6.12),
        # so the arrows stay, styled away.
        field.editingFinished.connect(lambda: self.change(key, field.value()))
        return field

    def address_field(self):
        field = QLineEdit(self.settings["unreal_address"])
        field.setPlaceholderText("address of the PC that runs Unreal")
        field.editingFinished.connect(lambda: self.change("unreal_address", field.text().strip()))
        self.address_fields.append(field)
        return field

    def build_calibration(self):
        widget, layout, _, _ = self.page("Calibration", "Where each camera is and where it points, found with the "
                                                        "checkerboard (11 x 8 squares of 6.5 cm)")
        top = QHBoxLayout()
        top.setSpacing(16)

        walk, walk_box = card("1. Walk with the board")
        walk_box.addWidget(label(
            "Hold the board by its edges (the pattern fully visible), high (about 2 m), facing two or three "
            "neighbouring cameras at once, and tilt it now and then (tilted views measure each camera's lens). "
            "Move slowly from group to group around the whole space, about 3 minutes. Green frame: that camera finds "
            "the board now. Each camera needs 20 or more views; a view counts when another camera finds the board "
            "at the same moment.", "small", wrap=True))
        self.walk_button = QPushButton("Start")
        self.walk_button.setObjectName("primary")
        self.walk_button.clicked.connect(self.toggle_walk)
        walk_box.addWidget(self.walk_button)
        self.walk_info = label("", "muted", wrap=True)
        walk_box.addWidget(self.walk_info)
        walk_box.addStretch()
        top.addWidget(walk, 1)

        floor, floor_box = card("2. Board on the floor")
        floor_box.addWidget(label(
            "Lay the board flat on the floor, face up, its long side parallel to the wall, its middle in front of "
            "the middle of the wall. Measure from the bottom of the LED wall to the near edge of the black and "
            "white pattern (not the white border). Step away so the cameras see it.", "small", wrap=True))
        form = QFormLayout()
        form.addRow("Distance (cm)", self.number_field("floor_distance", 0, 500))
        floor_box.addLayout(form)
        self.floor_button = QPushButton("Take the floor board (2 s)")
        self.floor_button.clicked.connect(self.take_floor)
        floor_box.addWidget(self.floor_button)
        self.floor_info = label("", "muted", wrap=True)
        floor_box.addWidget(self.floor_info)
        floor_box.addStretch()
        top.addWidget(floor, 1)

        result, result_box = card("3. Result")
        buttons = QHBoxLayout()
        self.compute_button = QPushButton("Compute")
        self.compute_button.setObjectName("primary")
        self.compute_button.clicked.connect(self.compute_calibration)
        self.use_button = QPushButton("Use this calibration")
        self.use_button.clicked.connect(self.use_calibration)
        buttons.addWidget(self.compute_button)
        buttons.addWidget(self.use_button)
        buttons.addStretch()
        result_box.addLayout(buttons)
        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        result_box.addWidget(self.result_text, 1)
        top.addWidget(result, 2)
        layout.addLayout(top, 1)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.board_views = []
        for i in range(8):
            view = label(f"Camera {i + 1}", "picture")
            view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            view.setMinimumSize(200, 125)
            view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            grid.addWidget(view, i // 4, i % 4)
            self.board_views.append(view)
        layout.addLayout(grid, 1)
        return widget

    def build_tracking(self):
        self.address_fields = []
        widget, layout, head, _ = self.page("Tracking", "Head position from all calibrated cameras, sent to Unreal in Moverse's format")
        self.track_button = QPushButton("Start tracking")
        self.track_button.setObjectName("primary")
        self.track_button.clicked.connect(self.toggle_tracking)
        head.addWidget(self.track_button)
        body = QHBoxLayout()
        body.setSpacing(16)

        settings, form_box = card("Settings")
        form = QFormLayout()
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.addRow("Unreal PC", self.address_field())
        form.addRow("Moverse port", self.number_field("moverse_port", 0, 65535, integer=True))
        form_box.addLayout(form)
        form_box.addWidget(label("Camera positions: from the calibration (Calibration page).", "small", wrap=True))
        self.calibration_line = label("", "muted", wrap=True)
        form_box.addWidget(self.calibration_line)
        form_box.addWidget(label("Smoothing (One Euro filter): lower min cutoff = calmer when still, "
                                 "higher beta = less lag when moving", "small", wrap=True))
        smooth = QFormLayout()
        smooth.addRow("Min cutoff (Hz)", self.number_field("filter_min_cutoff", 0.01, 20, 2, 0.1))
        smooth.addRow("Beta", self.number_field("filter_beta", 0, 5, 3, 0.01))
        form_box.addLayout(smooth)
        form_box.addStretch()
        settings.setFixedWidth(360)
        body.addWidget(settings)

        live, live_box = card()
        top = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("What a camera sees", "cardTitle"))
        titles.addWidget(label("Click a person to make them the main person: only their head drives the 3D view "
                               "and Frank's gaze. P1, P2, ...: the same person in every camera.", "small", wrap=True))
        top.addLayout(titles, 1)
        self.view_choice = QComboBox()
        self.view_choice.addItems([f"Camera {i + 1}" for i in range(8)])
        top.addWidget(self.view_choice)
        self.auto_button = QPushButton("Automatic (nearest to the wall)")
        self.auto_button.clicked.connect(self.follow_nearest)
        top.addWidget(self.auto_button)
        live_box.addLayout(top)
        self.track_picture = ClickablePicture(self.pick_person)
        self.track_picture.setObjectName("picture")
        self.track_picture.setText("camera not streaming")
        self.track_picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.track_picture.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        live_box.addWidget(self.track_picture, 1)
        numbers = QGridLayout()
        self.track_values = {}
        for column, key in enumerate(["X", "Y", "Z", "Rate"]):
            numbers.addWidget(label(key if key != "Rate" else "Rate (Hz)", "small"), 0, column)
            value = label("-", "value")
            numbers.addWidget(value, 1, column)
            self.track_values[key] = value
        live_box.addLayout(numbers)
        self.track_info = label("", "muted", wrap=True)
        live_box.addWidget(self.track_info)
        body.addWidget(live, 1)
        layout.addLayout(body, 1)
        return widget

    def build_space(self):
        widget, layout, _, _ = self.page("3D view", "The lab in tracking space: the LED wall, the floor and every tracked person, live")
        self.space = space.Space(self.tracked_people, self.calibrated_cameras)
        frame, box = card()
        box.setContentsMargins(2, 2, 2, 2)
        box.addWidget(self.space)
        layout.addWidget(frame, 1)
        return widget

    def tracked_people(self):
        """[(number, is main, position in tracking space cm)] for the 3D view; the main person at the
        smoothed position that is sent to Unreal."""
        tracker = self.tracker
        if not tracker:
            return []
        found = []
        for person in tracker.people:
            main = person["number"] == tracker.main
            position = tracker.position if main and tracker.position is not None else person["position"]
            found.append((person["number"], main, position))
        return found

    def calibrated_cameras(self):
        """[(number, position, looking direction)] of the cameras in the calibration in use, for the 3D view."""
        poses = (self.settings.get("calibration") or {}).get("cameras", {})
        return [(p["number"], np.array(p["position"]), np.array(p["rotation"]) @ [0.0, 0.0, 1.0]) for p in poses.values()]

    def build_vision(self):
        widget, layout, head, _ = self.page("Vision", "Local vision model; Frank gets a description of the people in front of the wall")
        self.vision_button = QPushButton("Start vision")
        self.vision_button.setObjectName("primary")
        self.vision_button.clicked.connect(self.toggle_vision)
        head.addWidget(self.vision_button)
        top = QHBoxLayout()
        top.setSpacing(16)

        model, model_box = card("Model")
        self.ollama_line = label("Ollama: checking...", "muted", wrap=True)
        model_box.addWidget(self.ollama_line)
        self.model_choice = QComboBox()
        self.model_choice.addItem(self.settings["model"])
        self.model_choice.currentTextChanged.connect(lambda text: text and self.change("model", text))
        model_box.addWidget(self.model_choice)
        self.model_memory = label("", "small", wrap=True)
        model_box.addWidget(self.model_memory)
        model_box.addStretch()
        model.setFixedWidth(360)
        top.addWidget(model)

        send, send_box = card("Sending to Unreal")
        form = QFormLayout()
        form.addRow("Unreal PC", self.address_field())
        form.addRow("Vision port", self.number_field("vision_port", 0, 65535, integer=True))
        send_box.addLayout(form)
        self.vision_info = label("", "muted", wrap=True)
        send_box.addWidget(self.vision_info)
        send_box.addStretch()
        top.addWidget(send, 1)
        layout.addLayout(top)

        view, view_box = card("What Frank sees")
        self.view_text = QPlainTextEdit()
        self.view_text.setReadOnly(True)
        view_box.addWidget(self.view_text)
        layout.addWidget(view, 1)
        logs, log_box = card("Log")
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        log_box.addWidget(self.log_text)
        layout.addWidget(logs, 1)
        return widget

    def select_page(self, index):
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(self.nav):
            button.setChecked(i == index)

    # ---------- actions ----------

    def log(self, text):
        line = f"{time.strftime('%H:%M:%S')} {text}"
        self.log_lines.append(line)
        print(line, flush=True)  # also in the console when started from one (MRLabHub.exe has none)

    def change(self, key, value):
        if self.settings.get(key) == value:
            return
        self.settings[key] = value
        SETTINGS.write_text(json.dumps(self.settings, indent=1))
        if key == "unreal_address":
            for field in self.address_fields:
                field.setText(value)
        if self.tracker and key not in ("vision_port", "model", "frontal_id"):
            self.stop_tracking()
            self.start_tracking()
        if self.describer and key in ("unreal_address", "vision_port", "model"):
            self.stop_vision()
            self.start_vision()

    def search(self):
        if self.searching:
            return
        self.disconnect_cameras()
        self.searching = True
        self.cameras_sub.setText("Searching for cameras...")

        def work():
            found, error = cameras.search(include_webcam=self.webcam)
            if error:
                self.log(f"camera search failed: {error}")
            # Camera 1 to 8 in the order of the lab's camera addresses (runtime\defaults.json, not in Git);
            # cameras not in that list after them. Camera 1 is the frontal camera unless another was chosen.
            order = self.settings.get("camera_order", [])
            found.sort(key=lambda c: (order.index(c.address) if c.address in order else len(order), c.address))
            if not self.settings["frontal_id"] and order and found and found[0].address == order[0]:
                self.settings["frontal_id"] = found[0].device_id
            self.cameras = found[:8]
            self.searching = False
            self.log(f"found {len(found)} camera(s)")

        threading.Thread(target=work, daemon=True).start()

    def connect_cameras(self):
        """Start every camera at once (each in its own helper program)."""
        for camera in self.cameras:
            if camera.worker is None and camera.state == "available":
                camera.vision = self.vision_store if camera.device_id == self.settings["frontal_id"] else None
                worker = cameras.WebcamWorker if camera.device_id == cameras.WEBCAM else cameras.CameraWorker
                camera.worker = worker(camera, self.log)
                camera.worker.start()

    def disconnect_cameras(self):
        self.stop_tracking()
        self.stop_vision()
        if self.collector:
            self.collector.running = False
        for camera in self.cameras:  # all at once: each helper takes a few seconds to close its camera
            if camera.worker is not None:
                camera.worker.running = False
        for camera in self.cameras:
            if camera.worker is not None:
                camera.worker.join(timeout=8)
                camera.worker = None
                camera.status, camera.preview, camera.latest, camera.vision = "found", None, None, None

    def use_as_frontal(self, camera):
        """Frank's view comes from this camera from now on (no reconnecting: all cameras send the same)."""
        for c in self.cameras:
            c.vision = None
        self.change("frontal_id", camera.device_id)
        self.vision_store.clear()
        if camera.worker is not None:
            camera.vision = self.vision_store

    def frontal_streaming(self):
        return any(c.device_id == self.settings["frontal_id"] and c.status == "streaming" for c in self.cameras)

    def main_person(self):
        """(number, box, others seen, position text) of the tracker's main person for the vision model, or None
        (no tracking, or the frontal camera does not see the main person). Distance from the wall and side as
        Frank sees it (+Y, the visitor's right, is Frank's left)."""
        tracker = self.tracker
        main = tracker.main_box(self.settings["frontal_id"]) if tracker else None
        position = tracker.position if tracker else None
        if main is None or position is None:
            return None
        distance = (calibration.WALL_X - position[0]) / 100
        side = (position[1] - calibration.WALL_Y) / 100
        where = "in the middle" if abs(side) < 0.3 else f"{abs(side):.1f} m to Frank's {'left' if side > 0 else 'right'}"
        return main[0], main[1], len(tracker.people) > 1, f"about {distance:.1f} m from the wall, {where}"

    def shown_camera(self):
        index = self.view_choice.currentIndex()
        return self.cameras[index] if 0 <= index < len(self.cameras) else None

    def pick_person(self, x, y):
        camera = self.shown_camera()
        if self.tracker and camera:
            number = self.tracker.select(camera.device_id, x, y)
            if number is not None:
                self.log(f"tracking: main person P{number} (clicked)")

    def follow_nearest(self):
        if self.tracker:
            self.tracker.automatic()
            self.log("tracking: main person chosen automatically (nearest to the wall)")

    def toggle_tracking(self):
        if self.tracker:
            self.stop_tracking()
        else:
            self.start_tracking()

    def start_tracking(self):
        s = self.settings
        poses = (s.get("calibration") or {}).get("cameras", {})
        ready = [c for c in self.cameras if c.status == "streaming" and c.device_id in poses]
        if not (s["unreal_address"] and s["moverse_port"]) or len(ready) < 2:
            self.log("tracking needs the calibration (Calibration page), two or more calibrated cameras streaming, "
                     "the Unreal PC address and the Moverse port")
            return
        self.tracker = tracking.Tracker(ready, poses, dict(s), self.log)
        self.tracker.start()
        self.log(f"tracking started with {len(ready)} cameras, sending to {s['unreal_address']}:{s['moverse_port']}")

    def stop_tracking(self):
        if self.tracker:
            self.tracker.stop()
            self.tracker = None
            self.log("tracking stopped")

    # ---------- calibration ----------

    def calibratable(self):
        """[(number, Camera)] of the OAK cameras streaming with their lens data."""
        return [(i + 1, c) for i, c in enumerate(self.cameras)
                if c.status == "streaming" and c.lens and c.device_id != cameras.WEBCAM]

    def toggle_walk(self):
        if self.collector and self.collector.running:
            self.collector.running = False
            self.log(f"calibration: walk stopped, {len(self.walk)} moments")
            return
        found = self.calibratable()
        if len(found) < 2:
            self.log("calibration needs two or more cameras streaming")
            return
        self.collector = calibration.Collector(found, "walk", self.log)
        self.walk = self.collector.shots  # the same list, filled while walking
        self.collector.start()
        self.log("calibration: walk started")

    def take_floor(self):
        found = self.calibratable()
        if not found or (self.collector and self.collector.running):
            return
        self.collector = calibration.Collector(found, "floor", self.log)
        self.floor = self.collector.shots
        self.collector.start()

    def compute_calibration(self):
        if self.computing:
            return
        lenses = {i + 1: (c.device_id, c.lens) for i, c in enumerate(self.cameras) if c.lens and c.device_id != cameras.WEBCAM}
        walk, floor, distance = list(self.walk), list(self.floor), float(self.settings["floor_distance"])
        self.computing, self.result = True, None

        def work():
            try:
                self.result = calibration.solve(walk, floor, lenses, distance)
                self.log(f"calibration computed: score {self.result['score']}")
            except (ValueError, np.linalg.LinAlgError, cv2.error) as error:
                self.result = {"error": str(error)}
                self.log(f"calibration failed: {error}")
            self.computing = False

        threading.Thread(target=work, daemon=True).start()

    def use_calibration(self):
        if self.result and "cameras" in self.result:
            self.change("calibration", {"cameras": self.result["cameras"], "score": self.result["score"],
                                        "report": self.result["report"], "made": time.strftime("%Y-%m-%d %H:%M")})
            self.log(f"calibration in use (score {self.result['score']}), saved in hub.local.json")

    def toggle_vision(self):
        if self.describer or self.vision_state == "loading":
            self.stop_vision()
        else:
            self.start_vision()

    def start_vision(self):
        s = self.settings
        if not (s["unreal_address"] and s["vision_port"] and self.frontal_streaming()):
            self.log("vision needs the frontal camera streaming, the Unreal PC address and the vision port")
            return
        self.vision_state = "loading"
        self.log(f"loading {s['model']} (the first start in this folder can take a few minutes)")

        def work():
            try:
                vision.load_model(s["model"])
            except (OSError, RuntimeError, ValueError) as error:
                self.log(f"model did not load: {error}")
                self.vision_state = "off"
                return
            if self.vision_state != "loading":
                return  # stopped meanwhile
            self.describer = vision.Describer(self.vision_store, s["model"], self.log, self.main_person)
            self.sender = vision.Sender(self.vision_store, self.describer, (s["unreal_address"], int(s["vision_port"])), self.log)
            self.describer.start()
            self.sender.start()
            self.vision_state = "on"
            self.log(f"vision started, sending to {s['unreal_address']}:{s['vision_port']}")

        threading.Thread(target=work, daemon=True).start()

    def stop_vision(self):
        if self.describer:
            self.describer.running = False
            self.sender.running = False
            self.describer = self.sender = None
            self.log("vision stopped")
        self.vision_state = "off"

    def check_ollama(self):
        def work():
            try:
                self.ollama_state = OllamaServer.status()
            except (OSError, RuntimeError, ValueError):
                self.ollama_state = None

        threading.Thread(target=work, daemon=True).start()

    # ---------- refresh ----------

    def refresh(self):
        if not self.view_picked and self.cameras:  # show the frontal camera on the Tracking page at first
            frontal = [i for i, c in enumerate(self.cameras) if c.device_id == self.settings["frontal_id"]]
            if frontal:
                self.view_choice.setCurrentIndex(frontal[0])
            self.view_picked = True
        for i, tile in enumerate(self.tiles):
            camera = self.cameras[i] if i < len(self.cameras) else None
            tile.show_camera(camera, camera is not None and camera.device_id == self.settings["frontal_id"])
        streaming = sum(c.status == "streaming" for c in self.cameras)
        if not self.searching:
            self.cameras_sub.setText(f"{len(self.cameras)} of 8 found  |  {streaming} streaming")
        self.connect_button.setEnabled(not self.searching and any(c.worker is None and c.state == "available" for c in self.cameras))
        self.disconnect_button.setEnabled(any(c.worker is not None for c in self.cameras))
        self.search_button.setEnabled(not self.searching)
        self.refresh_calibration()
        self.refresh_tracking()
        self.refresh_vision()
        self.refresh_sidebar(streaming)

    def refresh_calibration(self):
        collector = self.collector
        busy = bool(collector and collector.running)
        walking = busy and collector.mode == "walk"
        self.walk_button.setText("Stop" if walking else "Start")
        set_variant(self.walk_button, "stop" if walking else "primary")
        self.walk_button.setEnabled(not busy or walking)
        self.floor_button.setEnabled(not busy)
        views = collections.Counter(n for shot in list(self.walk) for n in shot)
        if self.walk or walking:
            lines = [f"{len(self.walk)} moments with two or more cameras"]
            lines += ["  ".join(f"Camera {n}: {views[n]}" for n in range(row, row + 4)) for row in (1, 5)]
            self.walk_info.setText("\n".join(lines))
        else:
            self.walk_info.setText("Not started.")
        if busy and collector.mode == "floor":
            self.floor_info.setText("Taking the floor board...")
        elif self.floor:
            seen = sorted({n for shot in self.floor for n in shot})
            self.floor_info.setText(f"Seen by camera(s) {', '.join(map(str, seen))} in {len(self.floor)} moments.")
        else:
            self.floor_info.setText("Not taken yet.")
        self.compute_button.setEnabled(bool(self.walk and self.floor) and not self.computing and not busy)
        self.use_button.setEnabled(bool(self.result and "cameras" in self.result))
        used = self.settings.get("calibration")
        in_use = f"In use: score {used['score']}, made {used['made']}." if used else "In use: none (tracking needs one)."
        if self.computing:
            text = "Computing (up to two minutes)..."
        elif self.result and "error" in self.result:
            text = f"Did not work: {self.result['error']}"
        elif self.result:
            text = "\n".join(self.result["report"]) + "\n\nNot in use yet: press Use this calibration."
        else:
            text = "\n".join(used["report"]) if used else ""
        text = f"{in_use}\n\n{text}".strip()
        if self.result_text.toPlainText() != text:
            self.result_text.setPlainText(text)
        if self.pages.currentIndex() != PAGES.index("Calibration"):
            return
        now = time.perf_counter()
        for i, view in enumerate(self.board_views):
            camera = self.cameras[i] if i < len(self.cameras) else None
            if camera is None or camera.preview is None or camera.status != "streaming":
                view.setPixmap(QPixmap())
                view.setText(f"Camera {i + 1}")
                continue
            image = camera.preview.copy()
            if collector is not None and now - collector.seen.get(i + 1, -10.0) < 0.6:
                cv2.rectangle(image, (1, 1), (image.shape[1] - 2, image.shape[0] - 2), (80, 200, 120), 4)
            cv2.putText(image, f"{i + 1}  {views[i + 1]}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            view.setPixmap(to_pixmap(image, view.width(), view.height()))

    def refresh_tracking(self):
        tracker = self.tracker
        camera = self.shown_camera()
        if self.pages.currentIndex() == PAGES.index("Tracking"):
            if camera and camera.latest and camera.status == "streaming":
                image = cv2.imdecode(np.frombuffer(camera.latest[0], np.uint8), cv2.IMREAD_REDUCED_COLOR_2)
                w, h = image.shape[1], image.shape[0]
                for box, head, number in (tracker.seen_by(camera.device_id) if tracker else []):
                    main = number is not None and number == tracker.main
                    colour = (246, 130, 59) if main else (150, 150, 150)  # blue accent for the main person, else grey
                    x0, y0 = int(box[0] * w), int(box[1] * h)
                    cv2.rectangle(image, (x0, y0), (int(box[2] * w), int(box[3] * h)), colour, 3 if main else 1)
                    cv2.circle(image, (int(head[0] * w), int(head[1] * h)), 5, (80, 200, 120) if main else colour, -1)
                    name = (f"P{number}" if number is not None else "?") + ("  MAIN" if main else "")
                    cv2.rectangle(image, (x0, max(0, y0 - 22)), (x0 + 12 * len(name) + 10, max(22, y0)), colour, -1)
                    cv2.putText(image, name, (x0 + 5, max(16, y0 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
                self.track_picture.setPixmap(to_pixmap(image, self.track_picture.width(), self.track_picture.height()))
            else:
                self.track_picture.setPixmap(QPixmap())
                self.track_picture.setText("camera not streaming")
        used = self.settings.get("calibration")
        self.calibration_line.setText(f"Calibration in use: score {used['score']}, {len(used['cameras'])} cameras, "
                                      f"made {used['made']}." if used else "No calibration yet: tracking needs one.")
        position = tracker.position if tracker else None
        for key, index in (("X", 0), ("Y", 1), ("Z", 2)):
            self.track_values[key].setText(f"{position[index]:.1f}" if position is not None else "-")
        self.track_values["Rate"].setText(f"{tracker.rate:.0f}" if tracker else "-")
        self.auto_button.setEnabled(bool(tracker and tracker.chosen))
        if tracker:
            people = list(tracker.people)
            main = next((p for p in people if p["number"] == tracker.main), None)
            if main is not None and position is not None:
                how = "clicked" if tracker.chosen else "automatic: nearest to the wall"
                seen = (f"{len(people)} seen, main person P{tracker.main} ({how}), seen by camera(s) "
                        + ", ".join(map(str, main["cameras"])))
            elif tracker.chosen:
                seen = f"{len(people)} seen, waiting for P{tracker.main} (clicked) to be visible again"
            else:
                seen = f"{len(people)} seen" if people else "nobody found (a person needs two cameras)"
            seen += f"  |  {tracker.combined} cameras combined in the last update, {tracker.pending} not confirmed yet"
            self.track_info.setText(f"{seen}  |  {tracker.status}  |  {tracker.sent} packets sent to "
                                    f"{self.settings['unreal_address']}:{self.settings['moverse_port']}")
        else:
            self.track_info.setText("Stopped. Moverse must not run at the same time (both would send to the same port).")
        self.track_button.setText("Stop tracking" if tracker else "Start tracking")
        set_variant(self.track_button, "stop" if tracker else "primary")

    def refresh_vision(self):
        state = self.ollama_state
        if state is None:
            self.ollama_line.setText(f"Ollama at {OllamaServer.address()}: not reachable" + (" (starting...)" if self.ollama.own else ""))
        else:
            own = "own server" if self.ollama.own else "server already running"
            self.ollama_line.setText(f"Ollama {state['version']} at {OllamaServer.address()} ({own})")
            current = self.model_choice.currentText()
            if state["models"] and [self.model_choice.itemText(i) for i in range(self.model_choice.count())] != state["models"]:
                self.model_choice.blockSignals(True)
                self.model_choice.clear()
                self.model_choice.addItems(state["models"])
                self.model_choice.setCurrentText(current if current in state["models"] else state["models"][0])
                self.model_choice.blockSignals(False)
            loaded = state["loaded"].get(self.settings["model"])
            self.model_memory.setText(f"loaded, {loaded / 1e9:.1f} GB on the GPU" if loaded else "not loaded yet (loads when vision starts)")
        describer, sender = self.describer, self.sender
        if describer and describer.view:
            v = describer.view
            text = v["description"].replace("; ", ";\n    ").replace(". Person", ".\nPerson")
            if self.view_text.toPlainText() != text:
                self.view_text.setPlainText(text)
            self.vision_info.setText(f"view {v['seq']}  |  model {v['model_ms']} ms  |  {sender.sent} packets sent"
                                     + (f"  |  last error: {describer.error}" if describer.error else ""))
        elif self.vision_state == "loading":
            self.vision_info.setText("loading the model...")
        elif describer:
            self.vision_info.setText("waiting for the first description" + (f"  |  last error: {describer.error}" if describer.error else ""))
        else:
            self.vision_info.setText("Stopped.")
        running = self.vision_state != "off"
        self.vision_button.setText("Stop vision" if running else "Start vision")
        set_variant(self.vision_button, "stop" if running else "primary")
        lines = list(self.log_lines) + [f"ollama: {line}" for line in list(self.ollama.log)[-5:]]
        text = "\n".join(lines[-60:])
        if self.log_text.toPlainText() != text:
            self.log_text.setPlainText(text)
            self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def refresh_sidebar(self, streaming):
        model_ready = self.ollama_state is not None and self.settings["model"] in self.ollama_state["loaded"]
        used = self.settings.get("calibration")
        rows = {
            "Cameras": (f"Cameras  {streaming}/8 streaming", OK if streaming else MUTED),
            "Calibration": (f"Calibration  score {used['score']}" if used else "Calibration  none", OK if used else MUTED),
            "Tracking": ("Tracking  on" if self.tracker else "Tracking  off", OK if self.tracker else MUTED),
            "Vision": (f"Vision  {self.vision_state}", OK if self.vision_state == "on" else WARN if self.vision_state == "loading" else MUTED),
            "Model": ("Model  ready" if model_ready else "Model  not loaded", OK if model_ready else MUTED),
        }
        for key, (text, color) in rows.items():
            indicator, line = self.side_status[key]
            line.setText(text)
            set_dot(indicator, color)

    def closeEvent(self, event):
        self.disconnect_cameras()
        self.ollama.stop()
        super().closeEvent(event)


def main():
    # The hub runs in Python's pythonw.exe: an app id of its own makes the taskbar show the hub's icon
    # (hub/icon.png) instead of Python's. Only for this process, nothing on the PC is changed.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MRLab.Hub")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(pathlib.Path(__file__).with_name("icon.png"))))
    app.setStyleSheet(STYLE)
    window = Hub(webcam="--webcam" in sys.argv)
    window.show()
    sys.exit(app.exec())
