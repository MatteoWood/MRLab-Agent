"""People and their body points with YOLO11 nano pose (Ultralytics, AGPL-3.0) on this PC.

The model file (runtime/pc_models/yolo11n-pose.onnx, 640x640 input, 17 COCO body points) runs with ONNX
Runtime, on the graphics card through DirectML or on the processor, whichever answers faster here: both
are timed when the model loads. Laptop RTX 4090 / i9-13980HX, 2026-11-09: processor 45 ms (16 threads),
DirectML about 190 ms (slower there for reasons not found); a desktop graphics card may differ.
"""
import os
import pathlib
import time

import cv2
import numpy as np

MODEL = pathlib.Path(__file__).resolve().parent.parent / "runtime" / "pc_models" / "yolo11n-pose.onnx"
SIZE = 640
MIN_SCORE = 0.4  # person confidence
NMS_OVERLAP = 0.5
# COCO body points: 0 nose, 1 left eye, 2 right eye, 3 left ear, 4 right ear, 5 left shoulder, ...
NOSE, LEFT_EYE, RIGHT_EYE, LEFT_EAR, RIGHT_EAR = range(5)


class PoseModel:
    def __init__(self, log=print):
        import onnxruntime as ort

        if not MODEL.exists():
            raise FileNotFoundError(f"pose model missing: {MODEL}")
        test = np.zeros((1, 3, SIZE, SIZE), np.float32)
        choices = []
        if "DmlExecutionProvider" in ort.get_available_providers():
            options = ort.SessionOptions()
            options.enable_mem_pattern = False  # DirectML needs these two (ONNX Runtime documentation)
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            choices.append(("graphics card (DirectML)", options, ["DmlExecutionProvider", "CPUExecutionProvider"]))
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(4, (os.cpu_count() or 8) // 2)
        choices.append(("processor", options, ["CPUExecutionProvider"]))
        best = None
        for name, options, providers in choices:
            try:
                session = ort.InferenceSession(str(MODEL), options, providers=providers)
                for _ in range(3):
                    session.run(None, {"images": test})
                start = time.perf_counter()
                for _ in range(8):
                    session.run(None, {"images": test})
                ms = (time.perf_counter() - start) / 8 * 1000
            except Exception as error:  # this device cannot run it: use the other one
                log(f"pose model on the {name}: {error}")
                continue
            log(f"pose model on the {name}: {ms:.0f} ms per frame")
            if best is None or ms < best[2]:
                best = (session, name, ms)
        if best is None:
            raise RuntimeError("the pose model runs on neither the graphics card nor the processor")
        self.session, self.device, self.ms = best

    def __call__(self, image):
        """People in a BGR image: [{"box": (x0, y0, x1, y1), "points": array (17, 3) of x, y, confidence,
        "score"}], in the image's pixels."""
        h, w = image.shape[:2]
        scale = min(SIZE / w, SIZE / h)
        nw, nh = round(w * scale), round(h * scale)
        dx, dy = (SIZE - nw) // 2, (SIZE - nh) // 2
        canvas = np.full((SIZE, SIZE, 3), 114, np.uint8)  # letterbox, as the model was trained
        canvas[dy:dy + nh, dx:dx + nw] = cv2.resize(image, (nw, nh))
        blob = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        rows = self.session.run(None, {"images": blob})[0][0].T  # (8400, 56): cx, cy, w, h, score, 17 x (x, y, conf)
        rows = rows[rows[:, 4] > MIN_SCORE]
        if len(rows) == 0:
            return []
        boxes = np.stack([rows[:, 0] - rows[:, 2] / 2, rows[:, 1] - rows[:, 3] / 2, rows[:, 2], rows[:, 3]], 1)
        keep = cv2.dnn.NMSBoxes(boxes.tolist(), rows[:, 4].tolist(), MIN_SCORE, NMS_OVERLAP)
        people = []
        for i in np.array(keep).flatten():
            x, y, bw, bh = boxes[i]
            points = rows[i, 5:].reshape(17, 3).copy()
            points[:, 0] = (points[:, 0] - dx) / scale
            points[:, 1] = (points[:, 1] - dy) / scale
            people.append({
                "box": ((x - dx) / scale, (y - dy) / scale, (x + bw - dx) / scale, (y + bh - dy) / scale),
                "points": points,
                "score": float(rows[i, 4]),
            })
        return people
