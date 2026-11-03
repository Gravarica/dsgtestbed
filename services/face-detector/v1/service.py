from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import cv2
import numpy as np
import onnxruntime

from face_boxes import face_boxes_in_pixels

SAMPLE_FRAME_COUNT = 30
MODEL_INPUT_WIDTHS = {1: "320", 2: "640"}
BOX_COLOR = (0, 0, 255)


@dataclass
class WorkerState:
    session: onnxruntime.InferenceSession
    frames: List[np.ndarray]


def init_worker(cfg) -> WorkerState:
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = cfg.native_threads_per_worker
    options.inter_op_num_threads = 1
    model_path = cfg.service_directory / "models" / f"version-RFB-{MODEL_INPUT_WIDTHS[cfg.model_size]}.onnx"
    return WorkerState(
        session=onnxruntime.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"]),
        frames=read_video_frames(cfg.service_directory / "data" / "CV_Video.mp4", SAMPLE_FRAME_COUNT),
    )


def process(item, cfg, state: WorkerState):
    frame = state.frames[item.sample_index]
    return with_drawn_boxes(frame, detected_faces(state.session, frame))


def detected_faces(session: onnxruntime.InferenceSession, frame: np.ndarray) -> np.ndarray:
    model_input = session.get_inputs()[0]
    width, height = model_input.shape[3], model_input.shape[2]
    resized = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), (width, height))
    normalized = np.transpose((resized - np.array([127, 127, 127])) / 128, [2, 0, 1])
    confidences, boxes = session.run(None, {model_input.name: np.expand_dims(normalized, axis=0).astype(np.float32)})
    return face_boxes_in_pixels(frame.shape[1], frame.shape[0], confidences, boxes)


def with_drawn_boxes(frame: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    drawn = frame.copy()
    for left, top, right, bottom in boxes:
        cv2.rectangle(drawn, (int(left), int(top)), (int(right), int(bottom)), BOX_COLOR, 2)
    return drawn


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
