from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np
import onnxruntime


def next_multiple_of_32(length: int) -> int:
    return ((length + 31) // 32) * 32


def yolo_input_of(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    resized = cv2.resize(image, (next_multiple_of_32(width), next_multiple_of_32(height)))
    normalized = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return np.expand_dims(np.transpose(normalized, (2, 0, 1)), axis=0)


class YOLOv10:
    def __init__(self, model_path: str, confidence_threshold: float, threads: int):
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.confidence_threshold = confidence_threshold
        self.session = onnxruntime.InferenceSession(model_path, options, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def detect_objects(self, image: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        input_tensor = yolo_input_of(image)
        outputs = self.session.run(None, {self.input_name: input_tensor})
        return self._detections_in_image_coordinates(outputs[0], image.shape, input_tensor.shape[2:])

    def _detections_in_image_coordinates(self, output: np.ndarray, image_shape, input_shape):
        candidates = output.squeeze(axis=0)
        confident = candidates[candidates[:, 4] > self.confidence_threshold]
        boxes = confident[:, :4].copy()
        boxes[:, [0, 2]] *= image_shape[1] / input_shape[1]
        boxes[:, [1, 3]] *= image_shape[0] / input_shape[0]
        return confident[:, 5].astype(int), boxes.astype(np.int32), confident[:, 4]
