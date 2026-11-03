from __future__ import annotations

import zlib
from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np

SAMPLE_FRAME_COUNT = 60
FRAME_HEIGHT = 640
CHECKSUMS = {"crc32": zlib.crc32, "adler32": zlib.adler32}


def init_worker(cfg) -> List[np.ndarray]:
    frames = read_video_frames(cfg.service_directory / "data" / "QR_Video.mp4", SAMPLE_FRAME_COUNT)
    return [np.ascontiguousarray(resized_to_height(frame, FRAME_HEIGHT)) for frame in frames]


def process(item, cfg, frames) -> Dict[str, Any]:
    frame = frames[item.sample_index]
    return {
        "frame": int(item.sample_index),
        "height": int(frame.shape[0]),
        "width": int(frame.shape[1]),
        "checksum": int(CHECKSUMS[cfg.checksum](memoryview(frame))),
    }


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
