from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np

SAMPLE_COUNT = 30
PICTURE_WITH_KNOWN_FACES = "pedestrian.jpg"
STREET_VIDEO = "CV_Video.mp4"
MODEL_FILE = "face_detection_yunet_2023mar.onnx"
SCORE_THRESHOLD = 0.6
OVERLAP_THRESHOLD = 0.3
MOST_FACES_KEPT = 5000
ENLARGEMENTS_BY_MODEL_SIZE = {1: (1,), 2: (1, 2)}
BOX_COLUMNS = slice(0, 4)
SCORE_COLUMN = 14


@dataclass
class WorkerState:
    detector: Any
    frames: List[np.ndarray]


def init_worker(cfg) -> WorkerState:
    directory = Path(cfg.service_directory)
    detector = cv2.FaceDetectorYN.create(
        str(directory / "fetched" / "models" / MODEL_FILE), "", (320, 320), SCORE_THRESHOLD, OVERLAP_THRESHOLD, MOST_FACES_KEPT
    )
    frames = [at_frame_height(image, int(cfg.data_quality)) for image in sample_images(directory / "data")]
    return WorkerState(detector=detector, frames=frames)


def process(item, cfg, state: WorkerState) -> List[Dict[str, Any]]:
    frame = state.frames[item.sample_index]
    boxes, scores = faces_in(frame, state.detector, ENLARGEMENTS_BY_MODEL_SIZE[int(cfg.model_size)])
    return [{"box": [float(value) for value in box], "score": float(score)} for box, score in zip(boxes, scores)]


def faces_in(frame: np.ndarray, detector: Any, enlargements: Tuple[int, ...]) -> Tuple[np.ndarray, np.ndarray]:
    found = [faces_at_enlargement(frame, detector, enlargement) for enlargement in enlargements]
    boxes = np.vstack([boxes for boxes, _ in found])
    scores = np.concatenate([scores for _, scores in found])
    if len(found) == 1 or len(boxes) == 0:
        return boxes, scores
    kept = np.array(cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), SCORE_THRESHOLD, OVERLAP_THRESHOLD), dtype=int).reshape(-1)
    return boxes[kept], scores[kept]


def faces_at_enlargement(frame: np.ndarray, detector: Any, enlargement: int) -> Tuple[np.ndarray, np.ndarray]:
    searched = frame if enlargement == 1 else cv2.resize(frame, None, fx=enlargement, fy=enlargement, interpolation=cv2.INTER_LINEAR)
    detector.setInputSize((searched.shape[1], searched.shape[0]))
    _, faces = detector.detect(searched)
    if faces is None:
        return np.empty((0, 4), dtype=np.float32), np.empty(0, dtype=np.float32)
    return faces[:, BOX_COLUMNS] / enlargement, faces[:, SCORE_COLUMN]


def at_frame_height(image: np.ndarray, frame_height: int) -> np.ndarray:
    frame_width = 2 * round(image.shape[1] * frame_height / image.shape[0] / 2)
    return cv2.resize(image, (frame_width, frame_height), interpolation=cv2.INTER_AREA)


def sample_images(data_directory: Path) -> List[np.ndarray]:
    picture = cv2.imread(str(data_directory / PICTURE_WITH_KNOWN_FACES))
    if picture is None:
        raise FileNotFoundError(data_directory / PICTURE_WITH_KNOWN_FACES)
    return [picture] + video_frames(data_directory / STREET_VIDEO, SAMPLE_COUNT - 1)


def video_frames(video_path: Path, frame_count: int) -> List[np.ndarray]:
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
