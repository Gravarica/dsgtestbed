from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np

SAMPLE_FRAME_COUNT = 60
SMOOTHING_COLOR_SPREAD = 40.0
SMOOTHING_SPACE_SPREAD_PER_KERNEL_PIXEL = 0.5
LOWER_THRESHOLD_SHARE_OF_MEDIAN = 0.66
UPPER_THRESHOLD_SHARE_OF_MEDIAN = 1.33
SHORTEST_CONTOUR_IN_PIXELS = 12.0
POLYGON_TOLERANCE_SHARE_OF_LENGTH = 0.01


def init_worker(cfg) -> List[np.ndarray]:
    frames = read_video_frames(cfg.service_directory / "data" / "QR_Video.mp4", SAMPLE_FRAME_COUNT)
    return [resized_to_height(frame, cfg.data_quality) for frame in frames]


def process(item, cfg, frames) -> List[Dict[str, Any]]:
    edges = edge_map(frames[item.sample_index], cfg.smoothing)
    return [described(contour) for contour in contours_of(edges)]


def edge_map(frame: np.ndarray, smoothing: int) -> np.ndarray:
    smoothed = smoothed_keeping_edges(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), smoothing)
    brightness = float(np.median(smoothed))
    lower = int(max(0, LOWER_THRESHOLD_SHARE_OF_MEDIAN * brightness))
    upper = int(min(255, UPPER_THRESHOLD_SHARE_OF_MEDIAN * brightness))
    return cv2.Canny(smoothed, lower, upper)


def smoothed_keeping_edges(gray: np.ndarray, smoothing: int) -> np.ndarray:
    kernel_size = odd_kernel_size(smoothing)
    return cv2.bilateralFilter(gray, kernel_size, SMOOTHING_COLOR_SPREAD, SMOOTHING_SPACE_SPREAD_PER_KERNEL_PIXEL * kernel_size)


def odd_kernel_size(smoothing: int) -> int:
    return int(smoothing) | 1


def contours_of(edges: np.ndarray) -> List[np.ndarray]:
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    return [contour for contour in contours if cv2.arcLength(contour, False) >= SHORTEST_CONTOUR_IN_PIXELS]


def described(contour: np.ndarray) -> Dict[str, Any]:
    length = float(cv2.arcLength(contour, True))
    polygon = cv2.approxPolyDP(contour, POLYGON_TOLERANCE_SHARE_OF_LENGTH * length, True)
    left, top, width, height = cv2.boundingRect(contour)
    hull_area = float(cv2.contourArea(cv2.convexHull(contour)))
    area = float(cv2.contourArea(contour))
    return {
        "polygon": polygon.reshape(-1, 2).tolist(),
        "box": [int(left), int(top), int(width), int(height)],
        "length": length,
        "area": area,
        "solidity": area / hull_area if hull_area > 0 else 0.0,
        "points": int(len(contour)),
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
