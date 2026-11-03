from __future__ import annotations

from pathlib import Path
from typing import List

import cv2
import numpy as np

SAMPLE_FRAME_COUNT = 60
NOISE_SEED = 20261012
NOISE_STANDARD_DEVIATION = 15.0
SMALLEST_NEIGHBOURHOOD_PIXELS = 5
NEIGHBOURHOOD_PIXELS_PER_STRENGTH_STEP = 2
COLOUR_SIGMA = 45.0
SPACE_SIGMA_SHARE_OF_NEIGHBOURHOOD = 0.5


def init_worker(cfg) -> List[np.ndarray]:
    return noisy_frames(clean_frames(cfg))


def process(item, cfg, frames):
    return denoised(frames[item.sample_index], cfg.strength)


def denoised(noisy_frame: np.ndarray, strength: int) -> np.ndarray:
    neighbourhood = neighbourhood_pixels_for(strength)
    return cv2.bilateralFilter(noisy_frame, neighbourhood, COLOUR_SIGMA, SPACE_SIGMA_SHARE_OF_NEIGHBOURHOOD * neighbourhood)


def neighbourhood_pixels_for(strength: int) -> int:
    return SMALLEST_NEIGHBOURHOOD_PIXELS + NEIGHBOURHOOD_PIXELS_PER_STRENGTH_STEP * (int(strength) - 1)


def clean_frames(cfg) -> List[np.ndarray]:
    frames = read_video_frames(cfg.service_directory / "data" / "QR_Video.mp4", SAMPLE_FRAME_COUNT)
    return [resized_to_height(frame, cfg.data_quality) for frame in frames]


def noisy_frames(frames: List[np.ndarray]) -> List[np.ndarray]:
    randomness = np.random.default_rng(NOISE_SEED)
    return [with_noise(frame, randomness) for frame in frames]


def with_noise(frame: np.ndarray, randomness: np.random.Generator) -> np.ndarray:
    noise = randomness.normal(0.0, NOISE_STANDARD_DEVIATION, frame.shape)
    return np.clip(frame.astype(np.float32) + noise, 0, 255).astype(np.uint8)


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
    return cv2.resize(frame, (int(frame.shape[1] / ratio), int(target_height)), interpolation=cv2.INTER_AREA)
