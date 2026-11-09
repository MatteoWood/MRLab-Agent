"""MRLab camera service without a window (README 4.12): the vision part of the hub (hub/vision.py) on its own.

Reads the frontal camera, describes the people with the local vision model and sends the text to the
Unreal PC as UDP packets. The hub program (MRLabHub.exe) does the same with a window, plus tracking.

Run:  python mrlab_camera_service.py --source oak      (frontal OAK camera)
      python mrlab_camera_service.py --source webcam   (laptop testing)
Needs: Ollama with the model pulled (address from OLLAMA_HOST, default 127.0.0.1:11434),
opencv-python, depthai (only for --source oak).
Local settings, not in Git (the repo is public): mrlab_camera_service.local.json
next to this file, {"send_to": "<Unreal PC address>:<port>", "oak_device": "<device id or address>"}.
"""
import argparse
import json
import pathlib
import threading
import time

import cv2

from hub.vision import DEFAULT_MODEL, Describer, FrameStore, Sender, load_model


def grab_webcam(store):
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    while True:
        ok, image = cap.read()
        if ok:
            store.publish(image, time.monotonic())


def grab_oak(store, device_id):
    import depthai as dai

    with dai.Pipeline(dai.Device(dai.DeviceInfo(device_id))) as pipeline:
        cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
        queue = cam.requestOutput((640, 400), dai.ImgFrame.Type.BGR888i, fps=10).createOutputQueue(maxSize=1, blocking=False)
        pipeline.start()
        while pipeline.isRunning():
            frame = queue.get()
            age = (dai.Clock.now() - frame.getTimestamp()).total_seconds()
            store.publish(frame.getCvFrame(), time.monotonic() - age)


def log(text):
    print(f"{time.strftime('%H:%M:%S')} {text}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["oak", "webcam"], required=True)
    args = parser.parse_args()
    settings = json.loads(pathlib.Path(__file__).with_name("mrlab_camera_service.local.json").read_text())
    host, port = settings["send_to"].rsplit(":", 1)

    log("Loading the vision model (the first start in this folder can take a few minutes)...")
    load_model(DEFAULT_MODEL)
    store = FrameStore()
    if args.source == "oak":
        threading.Thread(target=grab_oak, args=(store, settings["oak_device"]), daemon=True).start()
    else:
        threading.Thread(target=grab_webcam, args=(store,), daemon=True).start()
    describer = Describer(store, DEFAULT_MODEL, log)
    describer.start()
    while describer.view is None:
        time.sleep(0.1)
    log(f"Sending to {settings['send_to']}, model {DEFAULT_MODEL}, source {args.source}")
    sender = Sender(store, describer, (host, int(port)), log)
    sender.run()


if __name__ == "__main__":
    main()
