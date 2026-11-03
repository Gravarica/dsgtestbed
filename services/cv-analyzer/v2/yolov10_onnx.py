from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np
import onnxruntime

YOLO_STRIDE = 32


def nearest_multiple_of_the_stride(length: float) -> int:
    return max(YOLO_STRIDE, int(round(length / YOLO_STRIDE)) * YOLO_STRIDE)


def yolo_input_of(image: np.ndarray) -> np.ndarray:
    normalized = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return np.expand_dims(np.transpose(normalized, (2, 0, 1)), axis=0)


class YOLOv10:
    def __init__(self, model_path: str, confidence_threshold: float, threads: int):
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.session = onnxruntime.InferenceSession(model_path, options, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def detect_objects(self, image: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        outputs = self.session.run(None, {self.input_name: yolo_input_of(image)})
        candidates = outputs[0].squeeze(axis=0)
        confident = candidates[candidates[:, 4] > self.confidence_threshold]
        return confident[:, 5].astype(int), confident[:, :4].astype(np.int32), confident[:, 4]
