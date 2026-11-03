from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np
import soundfile

SAMPLE_RATE = 16000
HOP_MS = 10
MFCC_COUNT = 13
LOWEST_MEL_HZ = 0.0
HIGHEST_MEL_HZ = SAMPLE_RATE / 2
SMALLEST_ENERGY = 1e-10


@dataclass
class FeatureSetup:
    clip_ids: List[str]
    audio: List[np.ndarray]
    window_frames: int
    hop_frames: int
    fft_size: int
    window: np.ndarray
    mel_filters: np.ndarray
    cosine_transform: np.ndarray


def init_worker(cfg) -> FeatureSetup:
    clips_directory = Path(cfg.service_directory) / "fetched" / "clips"
    clip_ids = sorted(json.loads((clips_directory / "transcripts.json").read_text()))
    frames_per_clip = int(cfg.data_quality) * SAMPLE_RATE
    window_frames = int(cfg.frame_ms) * SAMPLE_RATE // 1000
    fft_size = next_power_of_two(window_frames)
    mel_bands = int(cfg.mel_bands)
    return FeatureSetup(
        clip_ids=clip_ids,
        audio=[first_frames(clips_directory / f"{clip_id}.flac", frames_per_clip) for clip_id in clip_ids],
        window_frames=window_frames,
        hop_frames=HOP_MS * SAMPLE_RATE // 1000,
        fft_size=fft_size,
        window=np.hanning(window_frames).astype(np.float32),
        mel_filters=mel_filter_bank(mel_bands, fft_size),
        cosine_transform=cosine_transform_matrix(mel_bands, MFCC_COUNT),
    )


def process(item, cfg, setup: FeatureSetup) -> np.ndarray:
    frames = framed(setup.audio[item.sample_index], setup.window_frames, setup.hop_frames) * setup.window
    power_spectrum = np.abs(np.fft.rfft(frames, n=setup.fft_size, axis=1)) ** 2
    log_mel = np.log(np.maximum(power_spectrum @ setup.mel_filters.T, SMALLEST_ENERGY))
    mfcc = log_mel @ setup.cosine_transform.T
    return np.hstack([log_mel, mfcc]).astype(np.float32)


def framed(audio: np.ndarray, window_frames: int, hop_frames: int) -> np.ndarray:
    frame_count = 1 + (len(audio) - window_frames) // hop_frames
    return np.lib.stride_tricks.sliding_window_view(audio, window_frames)[::hop_frames][:frame_count]


def next_power_of_two(number: int) -> int:
    return 1 << (number - 1).bit_length()


def hz_to_mel(hz):
    return 2595.0 * np.log10(1.0 + np.asarray(hz) / 700.0)


def mel_to_hz(mel):
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def mel_filter_bank(mel_bands: int, fft_size: int) -> np.ndarray:
    bin_frequencies = np.linspace(0.0, SAMPLE_RATE / 2, fft_size // 2 + 1)
    edges = mel_to_hz(np.linspace(hz_to_mel(LOWEST_MEL_HZ), hz_to_mel(HIGHEST_MEL_HZ), mel_bands + 2))
    lower, centre, upper = edges[:-2, None], edges[1:-1, None], edges[2:, None]
    rising = (bin_frequencies - lower) / (centre - lower)
    falling = (upper - bin_frequencies) / (upper - centre)
    return np.maximum(0.0, np.minimum(rising, falling)).astype(np.float32)


def cosine_transform_matrix(mel_bands: int, coefficient_count: int) -> np.ndarray:
    band_positions = np.arange(mel_bands) + 0.5
    coefficients = np.arange(coefficient_count)[:, None]
    return (np.sqrt(2.0 / mel_bands) * np.cos(np.pi * coefficients * band_positions / mel_bands)).astype(np.float32)


def first_frames(flac_file: Path, frames: int) -> np.ndarray:
    audio, rate = soundfile.read(str(flac_file), frames=frames, dtype="float32")
    if rate != SAMPLE_RATE:
        raise ValueError(f"{flac_file} is recorded at {rate} Hz")
    return audio
