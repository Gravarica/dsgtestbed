from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np
import soundfile

SAMPLE_RATE = 16000
FRAME_MS = 40
LOWEST_PITCH_HZ = 60.0
HIGHEST_PITCH_HZ = 400.0
UNVOICED = 0.0
LEAST_PERIODICITY_OF_A_VOICED_FRAME = 0.5
SHARE_OF_THE_BEST_PEAK_THAT_AN_EARLIER_PEAK_NEEDS = 0.9
SHARE_OF_THE_LOUDEST_FRAME_THAT_COUNTS_AS_SOUND = 0.01
SMALLEST_ENERGY = 1e-10


@dataclass
class PitchSetup:
    clip_ids: List[str]
    audio: List[np.ndarray]
    frame_samples: int
    hop_samples: int
    fft_size: int
    shortest_lag: int
    longest_lag: int
    overlap_per_lag: np.ndarray


def init_worker(cfg) -> PitchSetup:
    clips_directory = Path(cfg.service_directory) / "fetched" / "clips"
    clip_ids = sorted(json.loads((clips_directory / "transcripts.json").read_text()))
    samples_per_clip = int(cfg.data_quality) * SAMPLE_RATE
    frame_samples = FRAME_MS * SAMPLE_RATE // 1000
    shortest_lag = int(SAMPLE_RATE / HIGHEST_PITCH_HZ)
    longest_lag = int(np.ceil(SAMPLE_RATE / LOWEST_PITCH_HZ))
    lags = np.arange(shortest_lag - 1, longest_lag + 2)
    return PitchSetup(
        clip_ids=clip_ids,
        audio=[first_samples(clips_directory / f"{clip_id}.flac", samples_per_clip) for clip_id in clip_ids],
        frame_samples=frame_samples,
        hop_samples=int(cfg.hop_length) * SAMPLE_RATE // 1000,
        fft_size=next_power_of_two(2 * frame_samples),
        shortest_lag=shortest_lag,
        longest_lag=longest_lag,
        overlap_per_lag=(frame_samples / (frame_samples - lags)).astype(np.float32),
    )


def process(item, cfg, setup: PitchSetup) -> np.ndarray:
    return pitch_per_frame(setup.audio[item.sample_index], setup)


def pitch_per_frame(audio: np.ndarray, setup: PitchSetup) -> np.ndarray:
    frames = framed(audio, setup.frame_samples, setup.hop_samples)
    frames = frames - frames.mean(axis=1, keepdims=True)
    spectrum = np.fft.rfft(frames, n=setup.fft_size, axis=1)
    autocorrelation = np.fft.irfft(spectrum.real**2 + spectrum.imag**2, n=setup.fft_size, axis=1)
    energy = np.maximum(autocorrelation[:, 0], SMALLEST_ENERGY)
    searched = autocorrelation[:, setup.shortest_lag - 1 : setup.longest_lag + 2] * setup.overlap_per_lag / energy[:, None]
    inner = searched[:, 1:-1]
    is_peak = (inner >= searched[:, :-2]) & (inner > searched[:, 2:])
    peaks = np.where(is_peak, inner, -1.0)
    best = peaks.max(axis=1)
    first_strong_peak = np.argmax(peaks >= SHARE_OF_THE_BEST_PEAK_THAT_AN_EARLIER_PEAK_NEEDS * best[:, None], axis=1)
    rows = np.arange(len(frames))
    before, at, after = searched[rows, first_strong_peak], inner[rows, first_strong_peak], searched[rows, first_strong_peak + 2]
    curvature = before - 2.0 * at + after
    shift = np.where(curvature < 0, 0.5 * (before - after) / np.where(curvature < 0, curvature, 1.0), 0.0)
    lag = setup.shortest_lag + first_strong_peak + shift
    loud_enough = energy >= SHARE_OF_THE_LOUDEST_FRAME_THAT_COUNTS_AS_SOUND * energy.max()
    voiced = (best >= LEAST_PERIODICITY_OF_A_VOICED_FRAME) & loud_enough
    return np.where(voiced, SAMPLE_RATE / lag, UNVOICED).astype(np.float32)


def framed(audio: np.ndarray, frame_samples: int, hop_samples: int) -> np.ndarray:
    frame_count = 1 + (len(audio) - frame_samples) // hop_samples
    return np.lib.stride_tricks.sliding_window_view(audio, frame_samples)[::hop_samples][:frame_count]


def next_power_of_two(number: int) -> int:
    return 1 << (number - 1).bit_length()


def first_samples(flac_file: Path, samples: int) -> np.ndarray:
    audio, rate = soundfile.read(str(flac_file), frames=samples, dtype="float32")
    if rate != SAMPLE_RATE:
        raise ValueError(f"{flac_file} is recorded at {rate} Hz")
    return audio
