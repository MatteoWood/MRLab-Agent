"""People and their body points with YOLO11 nano pose (Ultralytics, AGPL-3.0) on this PC.

The model file (runtime/pc_models/yolo11n-pose.onnx, 640x640 input, 17 COCO body points) runs with ONNX
Runtime, on the graphics card through DirectML or on the processor, whichever answers faster here: both
are timed when the model loads. The file declares ONNX version (opset) 22, for which DirectML has no
convolution: it left every convolution to the processor (146 ms per frame on the laptop's RTX 4090, 49 ms
on the tracking PC's RTX 5090). The model is loaded with the version lowered to 21 in memory (the file is
unchanged); the operations it uses are the same in 21 and 22 (22 only added data types), and the results
match the processor's. Laptop RTX 4090, 2026-11-10: 2.8 ms per frame on the graphics card, 45 ms on the
processor. DirectML is asked for the fastest graphics adapter (a built-in one took 36 ms, with wrong results).
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
OPSET = 21  # highest ONNX version DirectML runs this model's convolutions with (see above)


def model_bytes():
    """The model file with its declared ONNX version lowered to OPSET (top-level protobuf fields rewritten,
    everything else byte for byte as in the file)."""
    data = MODEL.read_bytes()

    def varint(b, i):
        value = shift = 0
        while True:
            byte = b[i]
            i += 1
            value |= (byte & 0x7F) << shift
            shift += 7
            if byte < 0x80:
                return value, i

    def encode(value):
        out = bytearray()
        while True:
            byte, value = value & 0x7F, value >> 7
            out.append(byte | 0x80 if value else byte)
            if not value:
                return bytes(out)

    def fields(b):
        i = 0
        while i < len(b):
            start = i
            key, i = varint(b, i)
            number, kind = key >> 3, key & 7
            if kind == 0:
                value, i = varint(b, i)
            elif kind == 2:
                size, i = varint(b, i)
                value, i = b[i:i + size], i + size
            else:  # fixed 64 or 32 bit
                value, i = None, i + (8 if kind == 1 else 4)
            yield number, value, b[start:i]

    out = bytearray()
    for number, value, raw in fields(data):
        if number == 8:  # opset_import: domain (1), version (2)
            entry = {n: v for n, v, _ in fields(value)}
            if not entry.get(1) and entry.get(2, 0) > OPSET:
                body = b"\x10" + encode(OPSET)
                raw = b"\x42" + encode(len(body)) + body
        out += raw
    return bytes(out)


class PoseModel:
    """device: None to time both and use the faster, or the name of one ("graphics card (DirectML)",
    "processor"); threads: processor threads (default half of them)."""

    def __init__(self, log=print, device=None, threads=None):
        import onnxruntime as ort

        if not MODEL.exists():
            raise FileNotFoundError(f"pose model missing: {MODEL}")
        model = model_bytes()
        test = np.zeros((1, 3, SIZE, SIZE), np.float32)
        choices = []
        if "DmlExecutionProvider" in ort.get_available_providers():
            options = ort.SessionOptions()
            options.enable_mem_pattern = False  # DirectML needs these two (ONNX Runtime documentation)
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            dml = ("DmlExecutionProvider", {"performance_preference": "high_performance"})  # not a built-in chip
            choices.append(("graphics card (DirectML)", options, [dml, "CPUExecutionProvider"]))
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads or max(4, (os.cpu_count() or 8) // 2)
        choices.append(("processor", options, ["CPUExecutionProvider"]))
        if device is not None:
            choices = [choice for choice in choices if choice[0] == device]
        best = None
        for name, options, providers in choices:
            try:
                session = ort.InferenceSession(model, options, providers=providers)
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
        if (nw, nh) != (w, h):
            image = cv2.resize(image, (nw, nh))
        # letterbox with grey 114, as the model was trained; then RGB, 0..1, channels first, in one step
        canvas = cv2.copyMakeBorder(image, dy, SIZE - nh - dy, dx, SIZE - nw - dx, cv2.BORDER_CONSTANT, value=(114, 114, 114))
        blob = cv2.dnn.blobFromImage(canvas, 1 / 255.0, swapRB=True)
        out = self.session.run(None, {"images": blob})[0][0]  # (56, 8400): cx, cy, w, h, score, 17 x (x, y, conf)
        keep = np.flatnonzero(out[4] > MIN_SCORE)
        if keep.size == 0:
            return []
        rows = out[:, keep].T
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
