from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np

from coco_classes import CLASS_NAMES
from yolov10_onnx import YOLOv10, nearest_multiple_of_the_stride

SAMPLE_FRAME_COUNT = 60
CONFIDENCE_THRESHOLD = 0.3
YOLO_MODEL_SIZES = {1: "n", 2: "s", 3: "m", 4: "l"}


@dataclass
class WorkerState:
    detector: YOLOv10
    frames: List[np.ndarray]


def init_worker(cfg) -> WorkerState:
    model_path = cfg.service_directory / "models" / f"yolov10{YOLO_MODEL_SIZES[int(cfg.model_size)]}.onnx"
    if not model_path.exists():
        raise FileNotFoundError(f"{model_path} is missing. Run: just prepare cv-analyzer v2")
    frames = read_video_frames(cfg.service_directory / "data" / "CV_Video.mp4", SAMPLE_FRAME_COUNT)
    return WorkerState(
        detector=YOLOv10(str(model_path), CONFIDENCE_THRESHOLD, cfg.native_threads_per_worker),
        frames=[resized_to_height(frame, int(cfg.data_quality)) for frame in frames],
    )


def process(item, cfg, state: WorkerState) -> List[Dict[str, Any]]:
    class_ids, boxes, confidences = state.detector.detect_objects(state.frames[item.sample_index])
    return [
        {"class": CLASS_NAMES[class_id], "box": [int(edge) for edge in box], "score": float(confidence)}
        for class_id, box, confidence in zip(class_ids, boxes, confidences)
    ]


def read_video_frames(video_path: Path, frame_count: int) -> List[np.ndarray]:
    video = cv2.VideoCapture(str(video_path))
    if not video.isOpened():
        raise FileNotFoundError(video_path)
    video.read()
    frames = []
    while len(frames) < frame_count:
        was_read, frame = video.read()
        if not was_read:
            break
        frames.append(frame)
    video.release()
    return frames


def resized_to_height(frame: np.ndarray, asked_height: int) -> np.ndarray:
    height = nearest_multiple_of_the_stride(asked_height)
    width = nearest_multiple_of_the_stride(frame.shape[1] * height / frame.shape[0])
    return cv2.resize(frame, (width, height))
