"""MRLab camera service: Frank's eyes (README 4.12).

Runs on the tracking PC, next to the cameras. Keeps a short description of the
people the frontal camera sees and sends it to the PC that runs Unreal.
- The picture is checked CHECK_INTERVAL times a second. As soon as it has
  changed, a local vision model (Ollama) gets the newest frame plus the frames
  of the last SEQUENCE_STEPS * SEQUENCE_STEP seconds and describes the people,
  what they do now and what they did across the frames (waving, jumping jacks).
  A description counts as new only when its text differs.
- Every SEND_INTERVAL seconds the current description goes to the Unreal PC as
  one UDP packet (JSON): {"seq", "description", "age_ms", "frame_age_ms"};
  seq grows with every new description, age_ms is the age of the newest camera
  frame (camera alive), frame_age_ms the age of the newest frame the description
  was made from. Unreal (plugin MRLabLive) listens for these packets.
Images never leave this PC, and the service writes no files.

Run:  python mrlab_camera_service.py --source oak      (frontal OAK camera)
      python mrlab_camera_service.py --source webcam   (laptop testing)
Needs: Ollama with MODEL pulled (address from OLLAMA_HOST, default 127.0.0.1:11434),
opencv-python, depthai (only for --source oak).
Local settings, not in Git (the repo is public): mrlab_camera_service.local.json
next to this file, {"send_to": "<Unreal PC address>:<port>", "oak_device": "<device id or address>"}.
"""
import argparse
import base64
import collections
import http.client
import json
import os
import pathlib
import socket
import threading
import time

import cv2

MODEL = "qwen3.5:4b"
OLLAMA = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").rsplit(":", 1)
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

latest = None  # (BGR image, capture time on time.monotonic())
history = collections.deque(maxlen=SEQUENCE_STEPS)  # earlier frames, SEQUENCE_STEP apart
view = None    # {"description", "seq", "made" (capture time of the newest frame used), "model_ms"}
lock = threading.Lock()


def publish(image, captured):
    global latest
    with lock:
        if latest and (not history or latest[1] - history[-1][1] >= SEQUENCE_STEP):
            history.append(latest)
        latest = (image, captured)


def grab_webcam():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    while True:
        ok, image = cap.read()
        if ok:
            publish(image, time.monotonic())


def grab_oak(device_id):
    import depthai as dai

    with dai.Pipeline(dai.Device(dai.DeviceInfo(device_id))) as pipeline:
        cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
        queue = cam.requestOutput((640, 400), dai.ImgFrame.Type.BGR888i, fps=10).createOutputQueue(maxSize=1, blocking=False)
        pipeline.start()
        while pipeline.isRunning():
            frame = queue.get()
            age = (dai.Clock.now() - frame.getTimestamp()).total_seconds()
            publish(frame.getCvFrame(), time.monotonic() - age)


def encode(image, width):
    image = cv2.flip(cv2.resize(image, (width, width * image.shape[0] // image.shape[1])), 1)
    return base64.b64encode(cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()).decode()


def load_model():
    # The first start in a fresh folder also builds the NVIDIA driver's caches: more than 30 s on the
    # laptop (2026-11-09), so the model is loaded once with a long time limit.
    print("Loading the vision model (the first start in this folder can take a few minutes)...", flush=True)
    conn = http.client.HTTPConnection(OLLAMA[0], int(OLLAMA[1]), timeout=600)
    conn.request("POST", "/api/generate", json.dumps({"model": MODEL, "keep_alive": -1}), {"Content-Type": "application/json"})
    reply = json.loads(conn.getresponse().read())
    if "error" in reply:
        raise SystemExit(f"Ollama: {reply['error']}")


def describe(frames):
    images = [encode(image, 320) for image, _ in frames[:-1]] + [encode(frames[-1][0], 640)]
    secs = frames[-1][1] - frames[0][1]
    body = json.dumps({
        "model": MODEL,
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "options": {"temperature": 0},  # same picture, same words: unchanged views are not sent again
        "messages": [
            {"role": "system", "content": PROMPT.format(n=len(frames), secs=f"{secs:.1f}")},
            {"role": "user", "content": "What do the people do?", "images": images},
        ],
    })
    conn = http.client.HTTPConnection(OLLAMA[0], int(OLLAMA[1]), timeout=30)
    conn.request("POST", "/api/chat", body, {"Content-Type": "application/json"})
    reply = json.loads(conn.getresponse().read())
    if "error" in reply:
        raise RuntimeError(f"Ollama: {reply['error']}")
    return " ".join(reply["message"]["content"].replace("<", "").replace(">", "").split())


def describe_loop():
    global view
    described = None  # small greyscale copy of the last described picture
    while True:
        with lock:
            frames = list(history) + [latest]
        small = cv2.cvtColor(cv2.resize(frames[-1][0], (80, 50)), cv2.COLOR_BGR2GRAY)
        if described is not None and (cv2.absdiff(small, described) > CHANGED_LEVEL).mean() <= CHANGED_SHARE:
            time.sleep(CHECK_INTERVAL)
            continue
        start = time.monotonic()
        try:
            text = describe(frames)
        except (OSError, RuntimeError, ValueError) as error:  # Ollama down or busy: say so and try again
            print(f"{time.strftime('%H:%M:%S')} description failed: {error}", flush=True)
            time.sleep(2)
            continue
        model_ms = round((time.monotonic() - start) * 1000)
        if view and text == view["description"]:
            # Keep comparing with the last described picture, so a slow change is still checked.
            print(f"{time.strftime('%H:%M:%S')} unchanged (model {model_ms} ms)", flush=True)
            continue
        described = small
        with lock:
            view = {"description": text, "seq": view["seq"] + 1 if view else 1, "made": frames[-1][1], "model_ms": model_ms}
        print(f"{time.strftime('%H:%M:%S')} view {view['seq']} (model {model_ms} ms): {text}", flush=True)


def send_loop(address):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while True:
        with lock:
            v, captured = dict(view), latest[1]
        now = time.monotonic()
        packet = json.dumps({
            "seq": v["seq"],
            "description": v["description"],
            "age_ms": round((now - captured) * 1000),
            "frame_age_ms": round((now - v["made"]) * 1000),
        }).encode()
        try:
            sock.sendto(packet, address)
        except OSError as error:  # network down for a moment: keep going, Unreal tells Frank he cannot see
            print(f"{time.strftime('%H:%M:%S')} send failed: {error}", flush=True)
        time.sleep(SEND_INTERVAL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["oak", "webcam"], required=True)
    args = parser.parse_args()
    settings = json.loads(pathlib.Path(__file__).with_name("mrlab_camera_service.local.json").read_text())
    host, port = settings["send_to"].rsplit(":", 1)

    if args.source == "oak":
        threading.Thread(target=grab_oak, args=(settings["oak_device"],), daemon=True).start()
    else:
        threading.Thread(target=grab_webcam, daemon=True).start()
    load_model()
    while latest is None:
        time.sleep(0.1)
    threading.Thread(target=describe_loop, daemon=True).start()
    while view is None:  # the first description also loads the model into GPU memory
        time.sleep(0.1)
    print(f"Sending to {settings['send_to']}, model {MODEL}, source {args.source}", flush=True)
    send_loop((host, int(port)))


if __name__ == "__main__":
    main()
