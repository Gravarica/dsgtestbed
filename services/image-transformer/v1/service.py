from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np

SAMPLE_FRAME_COUNT = 30
CORRECTIONS_WITH_COLOUR = ("colour", "geometric")
SHARPENING_BLUR_SIGMA = 1.0
SHARPENING_AMOUNT = 0.5
CONTRAST_CLIP_LIMIT = 2.0
CONTRAST_TILES = (8, 8)
GAMMA = 0.9
RADIAL_DISTORTION = (-0.25, 0.08, 0.0, 0.0, 0.0)
FOCAL_LENGTH_IN_FRAME_WIDTHS = 0.8
KEYSTONE_SHARE_OF_WIDTH = 0.04
GEOMETRIC_INTERPOLATION = cv2.INTER_LANCZOS4


@dataclass
class Transformation:
    source_frames: List[np.ndarray]
    target_size: Tuple[int, int]
    gamma_table: np.ndarray
    undistortion_map_x: np.ndarray
    undistortion_map_y: np.ndarray
    keystone_matrix: np.ndarray


def init_worker(cfg) -> Transformation:
    source_frames = read_video_frames(cfg.service_directory / "data" / "QR_Video.mp4", SAMPLE_FRAME_COUNT)
    target_size = size_at_height(source_frames[0], cfg.data_quality)
    map_x, map_y = undistortion_maps(target_size)
    return Transformation(source_frames, target_size, gamma_table(GAMMA), map_x, map_y, keystone_matrix(target_size))


def process(item, cfg, transformation: Transformation) -> np.ndarray:
    frame = resized_and_sharpened(transformation.source_frames[item.sample_index], transformation.target_size)
    if cfg.correction in CORRECTIONS_WITH_COLOUR:
        frame = colour_corrected(frame, transformation.gamma_table)
    if cfg.correction == "geometric":
        frame = geometrically_corrected(frame, transformation)
    return frame


def size_at_height(frame: np.ndarray, target_height: int) -> Tuple[int, int]:
    height, width = frame.shape[:2]
    return max(1, round(width * int(target_height) / height)), int(target_height)


def resized_and_sharpened(frame: np.ndarray, target_size: Tuple[int, int]) -> np.ndarray:
    resized = cv2.resize(frame, target_size, interpolation=cv2.INTER_AREA)
    blurred = cv2.GaussianBlur(resized, (0, 0), SHARPENING_BLUR_SIGMA)
    return cv2.addWeighted(resized, 1 + SHARPENING_AMOUNT, blurred, -SHARPENING_AMOUNT, 0)


def colour_corrected(frame: np.ndarray, table: np.ndarray) -> np.ndarray:
    return white_balanced(cv2.LUT(contrast_equalized(frame), table))


def contrast_equalized(frame: np.ndarray) -> np.ndarray:
    lightness, green_red, blue_yellow = cv2.split(cv2.cvtColor(frame, cv2.COLOR_BGR2LAB))
    equalizer = cv2.createCLAHE(clipLimit=CONTRAST_CLIP_LIMIT, tileGridSize=CONTRAST_TILES)
    return cv2.cvtColor(cv2.merge((equalizer.apply(lightness), green_red, blue_yellow)), cv2.COLOR_LAB2BGR)


def white_balanced(frame: np.ndarray) -> np.ndarray:
    channel_means = frame.reshape(-1, 3).mean(axis=0)
    gains = channel_means.mean() / np.maximum(channel_means, 1e-6)
    return np.clip(frame.astype(np.float32) * gains, 0, 255).astype(np.uint8)


def gamma_table(gamma: float) -> np.ndarray:
    levels = np.arange(256, dtype=np.float32) / 255.0
    return np.clip(np.power(levels, gamma) * 255.0, 0, 255).astype(np.uint8)


def geometrically_corrected(frame: np.ndarray, transformation: Transformation) -> np.ndarray:
    undistorted = cv2.remap(frame, transformation.undistortion_map_x, transformation.undistortion_map_y, GEOMETRIC_INTERPOLATION)
    return cv2.warpPerspective(undistorted, transformation.keystone_matrix, transformation.target_size, flags=GEOMETRIC_INTERPOLATION)


def camera_matrix(target_size: Tuple[int, int]) -> np.ndarray:
    width, height = target_size
    focal_length = FOCAL_LENGTH_IN_FRAME_WIDTHS * width
    return np.array([[focal_length, 0, width / 2], [0, focal_length, height / 2], [0, 0, 1]], dtype=np.float64)


def undistortion_maps(target_size: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
    camera = camera_matrix(target_size)
    return cv2.initUndistortRectifyMap(camera, np.array(RADIAL_DISTORTION), None, camera, target_size, cv2.CV_32FC1)


def keystone_corners(target_size: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
    width, height = target_size
    inset = KEYSTONE_SHARE_OF_WIDTH * width
    seen = np.float32([[inset, 0], [width - 1 - inset, 0], [width - 1, height - 1], [0, height - 1]])
    corrected = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    return seen, corrected


def keystone_matrix(target_size: Tuple[int, int]) -> np.ndarray:
    seen, corrected = keystone_corners(target_size)
    return cv2.getPerspectiveTransform(seen, corrected)


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
