"""Frank's eyes (README 4.12): describes the people the frontal camera sees and sends the text to Unreal.

- FrameStore keeps the newest frame of the frontal camera and SEQUENCE_STEPS earlier ones, SEQUENCE_STEP apart.
- Describer checks the picture CHECK_INTERVAL times a second; as soon as it has changed, a local vision
  model (Ollama) gets the newest frame plus the earlier ones and describes the people, what they do now
  and what they did across the frames. A description counts as new only when its text differs.
- Sender sends the current description to the Unreal PC every SEND_INTERVAL seconds as one UDP packet
  (JSON): {"seq", "description", "age_ms", "frame_age_ms"}; age_ms is the age of the newest camera frame
  (camera alive), frame_age_ms the age of the newest frame the description was made from.
Images never leave this PC.
"""
import base64
import collections
import http.client
import json
import os
import socket
import threading
import time

import cv2
import numpy as np

DEFAULT_MODEL = "qwen3.5:4b"
CHECK_INTERVAL = 0.2  # seconds between checks of an unchanged picture
SEND_INTERVAL = 0.2   # seconds between packets to Unreal
SEQUENCE_STEPS = 3    # earlier frames given to the model with the newest one
SEQUENCE_STEP = 0.5   # seconds between those frames
# The picture counts as changed when more than CHANGED_SHARE of its pixels (at 80x50, greyscale)
# differ by more than CHANGED_LEVEL grey levels from the last described picture.
CHANGED_LEVEL = 30
CHANGED_SHARE = 0.01
# Fixed fields in few words: the same scene gives the same text (temperature 0), so small movements do not
# produce a reworded copy, and only real changes reach Frank. The images are mirrored before the model sees
# them: it names hands correctly more often then (laptop test 2026-11-09: 6 of 7 instead of 5 of 7).
# Measured on the laptop RTX 4090 with a free GPU: about 1 s for one person (newest frame 640 px wide,
# earlier frames 320 px; writing the about 70 output tokens takes most of it).
PROMPT = (
    "You are the eyes of Frank, a digital human who lives on a large LED wall. "
    "You get {n} images from a camera on top of the wall, looking at the visitors in front of it, "
    "taken over the last {secs} seconds, oldest first; the last image is now. "
    "Describe only the people, never the room, furniture or objects nobody holds. "
    "Use exactly this format, a few words per field, no full sentences, one line per person, "
    "numbered from Frank's left to Frank's right:\n"
    "Person 1: position: <Frank's left, centre or right; near or far>; clothes: <items and colours, "
    "any text or picture on them>; details: <glasses, hair, beard, hat>; holding: <object and which hand, or nothing>; "
    "pose now: <body and head in the last image>; gesture now: <gesture, which hand, how many fingers shown, or none>; "
    "action: <what they did across the images, for example standing still, waving, jumping jacks, "
    "walking to Frank's right, sitting down>; expression: <face>.\n"
    "If nobody is in view, write only: Nobody in view.\n"
    "The images are mirrored, like a mirror the visitors look into: the right side of the images is Frank's left, "
    "and a person's right hand appears on the right side of the image."
)


def ollama_address():
    host, port = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").rsplit(":", 1)
    return host, int(port)


def ollama_request(method, path, body=None, timeout=30):
    conn = http.client.HTTPConnection(*ollama_address(), timeout=timeout)
    conn.request(method, path, json.dumps(body) if body is not None else None, {"Content-Type": "application/json"})
    reply = json.loads(conn.getresponse().read() or b"{}")
    if "error" in reply:
        raise RuntimeError(f"Ollama: {reply['error']}")
    return reply


def load_model(model):
    # The first start in a fresh folder also builds the NVIDIA driver's caches, for the text part and again
    # for the first image: more than 30 s each on the laptop (2026-11-09). So the model is loaded with one
    # small image and a long time limit, before the descriptions (30 s limit) start.
    black = base64.b64encode(cv2.imencode(".jpg", np.zeros((64, 64, 3), np.uint8))[1].tobytes()).decode()
    ollama_request("POST", "/api/chat", {
        "model": model, "stream": False, "think": False, "keep_alive": -1, "options": {"num_predict": 1},
        "messages": [{"role": "user", "content": "OK?", "images": [black]}],
    }, timeout=600)


def encode(image, width):
    image = cv2.flip(cv2.resize(image, (width, width * image.shape[0] // image.shape[1])), 1)
    return base64.b64encode(cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()).decode()


def describe(model, frames):
    images = [encode(image, 320) for image, _ in frames[:-1]] + [encode(frames[-1][0], 640)]
    secs = frames[-1][1] - frames[0][1]
    reply = ollama_request("POST", "/api/chat", {
        "model": model,
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "options": {"temperature": 0},  # same picture, same words: unchanged views are not sent again
        "messages": [
            {"role": "system", "content": PROMPT.format(n=len(frames), secs=f"{secs:.1f}")},
            {"role": "user", "content": "What do the people do?", "images": images},
        ],
    })
    return " ".join(reply["message"]["content"].replace("<", "").replace(">", "").split())


class FrameStore:
    """Newest frame of the frontal camera plus earlier ones; filled by the camera thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.latest = None  # (BGR image, capture time on time.monotonic())
        self.history = collections.deque(maxlen=SEQUENCE_STEPS)

    def publish(self, image, captured):
        with self.lock:
            if self.latest and (not self.history or self.latest[1] - self.history[-1][1] >= SEQUENCE_STEP):
                self.history.append(self.latest)
            self.latest = (image, captured)

    def frames(self):
        with self.lock:
            return list(self.history) + [self.latest] if self.latest else []


class Describer(threading.Thread):
    """Keeps self.view = {"description", "seq", "made", "model_ms"} up to date while running."""

    def __init__(self, store, model, log=print):
        super().__init__(daemon=True)
        self.store, self.model, self.log = store, model, log
        self.view = None
        self.running = True
        self.error = ""

    def run(self):
        described = None  # small greyscale copy of the last described picture
        while self.running:
            frames = self.store.frames()
            if not frames:
                time.sleep(CHECK_INTERVAL)
                continue
            small = cv2.cvtColor(cv2.resize(frames[-1][0], (80, 50)), cv2.COLOR_BGR2GRAY)
            if described is not None and (cv2.absdiff(small, described) > CHANGED_LEVEL).mean() <= CHANGED_SHARE:
                time.sleep(CHECK_INTERVAL)
                continue
            start = time.monotonic()
            try:
                text = describe(self.model, frames)
            except (OSError, RuntimeError, ValueError) as error:  # Ollama down or busy: say so and try again
                self.error = str(error)
                self.log(f"description failed: {error}")
                time.sleep(2)
                continue
            self.error = ""
            model_ms = round((time.monotonic() - start) * 1000)
            if self.view and text == self.view["description"]:
                continue  # keep comparing with the last described picture, so a slow change is still checked
            described = small
            seq = self.view["seq"] + 1 if self.view else 1
            self.view = {"description": text, "seq": seq, "made": frames[-1][1], "model_ms": model_ms}
            self.log(f"view {seq} (model {model_ms} ms): {text}")


class Sender(threading.Thread):
    """Sends the describer's current view to (host, port) every SEND_INTERVAL seconds."""

    def __init__(self, store, describer, address, log=print):
        super().__init__(daemon=True)
        self.store, self.describer, self.address, self.log = store, describer, address, log
        self.running = True
        self.sent = 0

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        while self.running:
            view, frames = self.describer.view, self.store.frames()
            if view and frames:
                now = time.monotonic()
                packet = json.dumps({
                    "seq": view["seq"],
                    "description": view["description"],
                    "age_ms": round((now - frames[-1][1]) * 1000),
                    "frame_age_ms": round((now - view["made"]) * 1000),
                }).encode()
                try:
                    sock.sendto(packet, self.address)
                    self.sent += 1
                except OSError as error:  # network down for a moment: keep going, Unreal tells Frank he cannot see
                    self.log(f"send failed: {error}")
            time.sleep(SEND_INTERVAL)
