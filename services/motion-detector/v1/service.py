from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import cv2
import numpy as np

SAMPLE_PAIR_COUNT = 60
BLUR_SIDE_SHARE_OF_HEIGHT = 0.03
SPECKLE_SIDE_SHARE_OF_HEIGHT = 0.01
BRIGHTNESS_CHANGE_THAT_COUNTS = 25
FLOW_SHARE_OF_HEIGHT_THAT_COUNTS = 0.004
SMALLEST_REGION_SIDE_SHARE_OF_HEIGHT = 0.02
MERGING_KERNEL_SHARE_OF_HEIGHT = 0.02
FLOW_PYRAMID_SCALE = 0.5
FLOW_PYRAMID_LEVELS = 3
FLOW_WINDOW = 15
FLOW_ITERATIONS = 3
FLOW_POLYNOMIAL_NEIGHBOURHOOD = 5
FLOW_POLYNOMIAL_SIGMA = 1.2


def init_worker(cfg) -> List[np.ndarray]:
    frames = read_video_frames(cfg.service_directory / "data" / "QR_Video.mp4", SAMPLE_PAIR_COUNT + 1)
    return [resized_to_height(frame, cfg.data_quality) for frame in frames]


def process(item, cfg, frames):
    return moved_regions(frames[item.sample_index + 1], frames[item.sample_index], cfg.method)


def moved_regions(frame: np.ndarray, frame_before: np.ndarray, method: str) -> List[Dict[str, int]]:
    grey, grey_before = as_grey(frame), as_grey(frame_before)
    moved = moved_by_optical_flow(grey, grey_before) if method == "optical_flow" else moved_by_difference(grey, grey_before)
    return regions_of(moved)


def as_grey(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def moved_by_difference(grey: np.ndarray, grey_before: np.ndarray) -> np.ndarray:
    blur_side = odd_side(BLUR_SIDE_SHARE_OF_HEIGHT * grey.shape[0])
    difference = cv2.absdiff(smoothed(grey, blur_side), smoothed(grey_before, blur_side))
    changed = (difference > BRIGHTNESS_CHANGE_THAT_COUNTS).astype(np.uint8)
    speckle_side = odd_side(SPECKLE_SIDE_SHARE_OF_HEIGHT * grey.shape[0])
    return cv2.morphologyEx(changed, cv2.MORPH_OPEN, np.ones((speckle_side, speckle_side), np.uint8))


def smoothed(grey: np.ndarray, blur_side: int) -> np.ndarray:
    return cv2.GaussianBlur(cv2.medianBlur(grey, 5), (blur_side, blur_side), 0)


def odd_side(length: float) -> int:
    return max(3, int(length) // 2 * 2 + 1)


def moved_by_optical_flow(grey: np.ndarray, grey_before: np.ndarray) -> np.ndarray:
    flow = cv2.calcOpticalFlowFarneback(
        grey_before,
        grey,
        None,
        FLOW_PYRAMID_SCALE,
        FLOW_PYRAMID_LEVELS,
        FLOW_WINDOW,
        FLOW_ITERATIONS,
        FLOW_POLYNOMIAL_NEIGHBOURHOOD,
        FLOW_POLYNOMIAL_SIGMA,
        0,
    )
    distance_moved = np.hypot(flow[..., 0], flow[..., 1])
    return (distance_moved > FLOW_SHARE_OF_HEIGHT_THAT_COUNTS * grey.shape[0]).astype(np.uint8)


def regions_of(moved: np.ndarray) -> List[Dict[str, int]]:
    height = moved.shape[0]
    kernel_side = max(3, int(MERGING_KERNEL_SHARE_OF_HEIGHT * height))
    merged = cv2.dilate(moved, np.ones((kernel_side, kernel_side), np.uint8))
    contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    smallest_side = SMALLEST_REGION_SIDE_SHARE_OF_HEIGHT * height
    regions = []
    for contour in contours:
        left, top, width, region_height = cv2.boundingRect(contour)
        if width >= smallest_side and region_height >= smallest_side:
            regions.append({"left": int(left), "top": int(top), "width": int(width), "height": int(region_height)})
    return sorted(regions, key=lambda region: (region["top"], region["left"]))


def read_video_frames(video_path: Path, frame_count: int) -> List[np.ndarray]:
    video = cv2.VideoCapture(str(video_path))
    if not video.isOpened():
        raise FileNotFoundError(video_path)
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
    return cv2.resize(frame, (int(frame.shape[1] / ratio), int(target_height)))
