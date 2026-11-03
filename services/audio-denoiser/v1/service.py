from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np
import soundfile

SAMPLE_RATE = 16000
HOP_FRAMES = 128
NOISE_SEED = 20261012
NOISE_BELOW_CLIP_DB = 5.0
QUIET_SHARE_OF_FRAMES = 0.2
QUIET_POWER_OVER_MEAN_NOISE_POWER = -np.log(1.0 - QUIET_SHARE_OF_FRAMES)
OVERSUBTRACTION = 1.5
LOWEST_GAIN = 0.05
SMALLEST_POWER = 1e-12


@dataclass
class DenoisingSetup:
    clip_ids: List[str]
    clean: List[np.ndarray]
    noisy: List[np.ndarray]
    fft_size: int
    window: np.ndarray


def init_worker(cfg) -> DenoisingSetup:
    clips_directory = Path(cfg.service_directory) / "fetched" / "clips"
    clip_ids = sorted(json.loads((clips_directory / "transcripts.json").read_text()))
    frames_per_clip = int(cfg.data_quality) * SAMPLE_RATE
    fft_size = int(cfg.resolution)
    clean = [first_frames(clips_directory / f"{clip_id}.flac", frames_per_clip) for clip_id in clip_ids]
    return DenoisingSetup(
        clip_ids=clip_ids,
        clean=clean,
        noisy=[with_noise(audio, sample_index) for sample_index, audio in enumerate(clean)],
        fft_size=fft_size,
        window=np.hanning(fft_size + 1)[:-1].astype(np.float32),
    )


def process(item, cfg, setup: DenoisingSetup) -> np.ndarray:
    noisy = setup.noisy[item.sample_index]
    padded = np.pad(noisy, setup.fft_size, mode="reflect")
    spectrum = np.fft.rfft(framed(padded, setup.fft_size) * setup.window, axis=1)
    power = spectrum.real**2 + spectrum.imag**2
    gain = np.maximum(1.0 - OVERSUBTRACTION * noise_power_per_bin(power) / np.maximum(power, SMALLEST_POWER), LOWEST_GAIN)
    cleaned_frames = np.fft.irfft(spectrum * gain, n=setup.fft_size, axis=1) * setup.window
    cleaned = overlap_added(cleaned_frames, len(padded)) / overlap_added_window(setup.window, len(cleaned_frames), len(padded))
    return cleaned[setup.fft_size : setup.fft_size + len(noisy)].astype(np.float32)


def noise_power_per_bin(power: np.ndarray) -> np.ndarray:
    quiet_position = int(QUIET_SHARE_OF_FRAMES * len(power))
    quiet_power = np.partition(power, quiet_position, axis=0)[quiet_position]
    return quiet_power / QUIET_POWER_OVER_MEAN_NOISE_POWER


def framed(audio: np.ndarray, fft_size: int) -> np.ndarray:
    return np.lib.stride_tricks.sliding_window_view(audio, fft_size)[::HOP_FRAMES]


def overlap_added(frames: np.ndarray, length: int) -> np.ndarray:
    total = np.zeros(length + frames.shape[1], dtype=np.float64)
    covered = len(frames) * HOP_FRAMES
    for part in range(frames.shape[1] // HOP_FRAMES):
        start = part * HOP_FRAMES
        total[start : start + covered] += frames[:, start : start + HOP_FRAMES].ravel()
    return total[:length]


def overlap_added_window(window: np.ndarray, frame_count: int, length: int) -> np.ndarray:
    squared = np.broadcast_to(window.astype(np.float64) ** 2, (frame_count, len(window)))
    return np.maximum(overlap_added(squared, length), SMALLEST_POWER)


def with_noise(audio: np.ndarray, sample_index: int) -> np.ndarray:
    randomness = np.random.default_rng(NOISE_SEED + sample_index)
    noise_level = np.sqrt(np.mean(audio.astype(np.float64) ** 2) / 10.0 ** (NOISE_BELOW_CLIP_DB / 10.0))
    return (audio + noise_level * randomness.standard_normal(len(audio))).astype(np.float32)


def first_frames(flac_file: Path, frames: int) -> np.ndarray:
    audio, rate = soundfile.read(str(flac_file), frames=frames, dtype="float32")
    if rate != SAMPLE_RATE:
        raise ValueError(f"{flac_file} is recorded at {rate} Hz")
    return audio
