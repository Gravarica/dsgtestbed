from __future__ import annotations

import io
from pathlib import Path
from typing import List

import cv2
import numpy as np
from PIL import Image

SAMPLE_FRAME_COUNT = 60
LOWEST_ENCODING_QUALITY = 10
HIGHEST_ENCODING_QUALITY = 95
LOWEST_PNG_COMPRESS_LEVEL = 1
HIGHEST_PNG_COMPRESS_LEVEL = 9
PILLOW_FORMAT_NAMES = {"jpeg": "JPEG", "webp": "WEBP", "png": "PNG"}


def init_worker(cfg) -> List[Image.Image]:
    frames = read_video_frames(cfg.service_directory / "data" / "QR_Video.mp4", SAMPLE_FRAME_COUNT)
    return [as_rgb_image(resized_to_height(frame, cfg.data_quality)) for frame in frames]


def process(item, cfg, images):
    return encoded(images[item.sample_index], cfg.format, cfg.encoding_quality)


def encoded(image: Image.Image, image_format: str, encoding_quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=PILLOW_FORMAT_NAMES[image_format], **encoder_options(image_format, encoding_quality))
    return buffer.getvalue()


def encoder_options(image_format: str, encoding_quality: int) -> dict:
    if image_format == "png":
        return {"compress_level": png_compress_level_for(encoding_quality)}
    return {"quality": int(encoding_quality)}


def png_compress_level_for(encoding_quality: int) -> int:
    share = (int(encoding_quality) - LOWEST_ENCODING_QUALITY) / (HIGHEST_ENCODING_QUALITY - LOWEST_ENCODING_QUALITY)
    return LOWEST_PNG_COMPRESS_LEVEL + round(share * (HIGHEST_PNG_COMPRESS_LEVEL - LOWEST_PNG_COMPRESS_LEVEL))


def decoded(encoded_bytes: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(encoded_bytes)).convert("RGB"))


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


def as_rgb_image(frame: np.ndarray) -> Image.Image:
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    image.load()
    return image
