from __future__ import annotations

from pathlib import Path
from typing import List

import cv2
import numpy as np
from pyzbar.pyzbar import decode

SAMPLE_FRAME_COUNT = 60
HIGHLIGHT_COLOR = (0, 255, 0)


def init_worker(cfg) -> List[np.ndarray]:
    frames = read_video_frames(cfg.service_directory / "data" / "QR_Video.mp4", SAMPLE_FRAME_COUNT)
    return [resized_to_height(frame, cfg.data_quality) for frame in frames]


def process(item, cfg, frames):
    frame = frames[item.sample_index].copy()
    decoded_codes = decode(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    return with_highlighted_codes(frame, decoded_codes)


def decoded_texts(frame: np.ndarray) -> List[str]:
    return [code.data.decode("utf-8") for code in decode(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))]


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


def resized_to_height(frame: np.ndarray, target_height: int) -> np.ndarray:
    ratio = frame.shape[0] / int(target_height)
    return cv2.resize(frame, (int(frame.shape[1] / ratio), int(frame.shape[0] / ratio)))


def with_highlighted_codes(frame: np.ndarray, decoded_codes) -> np.ndarray:
    for code in decoded_codes:
        if len(code.polygon) == 4:
            corners = np.array(code.polygon, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(frame, [corners], True, HIGHLIGHT_COLOR, 4)
        label = f"{code.type}: {code.data.decode('utf-8')}"
        cv2.putText(frame, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, HIGHLIGHT_COLOR, 2)
    return frame
