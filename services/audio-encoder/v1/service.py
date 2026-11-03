from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np
import soundfile

SAMPLE_RATE = 16000
CHANNELS = 1
FRAMES_PER_WRITE = SAMPLE_RATE
CONTAINER_AND_CODEC = {"flac": ("FLAC", "PCM_16"), "ogg": ("OGG", "VORBIS")}


@dataclass
class EncoderSetup:
    clip_ids: List[str]
    audio: List[np.ndarray]
    container: str
    codec: str


def init_worker(cfg) -> EncoderSetup:
    clips_directory = Path(cfg.service_directory) / "fetched" / "clips"
    clip_ids = sorted(json.loads((clips_directory / "transcripts.json").read_text()))
    frames_per_clip = int(cfg.data_quality) * SAMPLE_RATE
    container, codec = CONTAINER_AND_CODEC[str(cfg.format)]
    return EncoderSetup(
        clip_ids=clip_ids,
        audio=[first_frames(clips_directory / f"{clip_id}.flac", frames_per_clip) for clip_id in clip_ids],
        container=container,
        codec=codec,
    )


def process(item, cfg, setup: EncoderSetup) -> bytes:
    return encoded(setup.audio[item.sample_index], setup.container, setup.codec)


def encoded(samples: np.ndarray, container: str, codec: str) -> bytes:
    encoded_file = io.BytesIO()
    with soundfile.SoundFile(encoded_file, mode="w", samplerate=SAMPLE_RATE, channels=CHANNELS, format=container, subtype=codec) as writer:
        for first_frame in range(0, len(samples), FRAMES_PER_WRITE):
            writer.write(samples[first_frame : first_frame + FRAMES_PER_WRITE])
    return encoded_file.getvalue()


def decoded(encoded_bytes: bytes) -> np.ndarray:
    samples, rate = soundfile.read(io.BytesIO(encoded_bytes), dtype="int16")
    if rate != SAMPLE_RATE:
        raise ValueError(f"decoded audio is at {rate} Hz")
    return samples


def first_frames(flac_file: Path, frames: int) -> np.ndarray:
    audio, rate = soundfile.read(str(flac_file), frames=frames, dtype="int16")
    if rate != SAMPLE_RATE:
        raise ValueError(f"{flac_file} is recorded at {rate} Hz")
    return audio
