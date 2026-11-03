from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import List

import numpy as np
import soundfile
from scipy import signal

SOURCE_RATE = 16000
FILTER_TAPS_PER_RATE_STEP = 10
KAISER_BETA = 5.0
TARGET_LOUDNESS_DB = -23.0
LOUDNESS_BLOCK_SECONDS = 0.4
LOUDNESS_BLOCK_STEP_SECONDS = 0.1
ABSOLUTE_GATE_DB = -70.0
RELATIVE_GATE_DB = -10.0
SMALLEST_POWER = 1e-12
HIGHEST_PEAK = 1.0


@dataclass
class ResamplingSetup:
    clip_ids: List[str]
    audio: List[np.ndarray]
    target_rate: int
    up: int
    down: int
    anti_aliasing_filter: np.ndarray


def init_worker(cfg) -> ResamplingSetup:
    clips_directory = Path(cfg.service_directory) / "fetched" / "clips"
    clip_ids = sorted(json.loads((clips_directory / "transcripts.json").read_text()))
    frames_per_clip = int(cfg.data_quality) * SOURCE_RATE
    target_rate = int(cfg.target_rate)
    ratio = Fraction(target_rate, SOURCE_RATE)
    return ResamplingSetup(
        clip_ids=clip_ids,
        audio=[first_frames(clips_directory / f"{clip_id}.flac", frames_per_clip) for clip_id in clip_ids],
        target_rate=target_rate,
        up=ratio.numerator,
        down=ratio.denominator,
        anti_aliasing_filter=low_pass_filter(ratio.numerator, ratio.denominator),
    )


def process(item, cfg, setup: ResamplingSetup) -> np.ndarray:
    centred = without_offset(setup.audio[item.sample_index])
    resampled = signal.resample_poly(centred, setup.up, setup.down, window=setup.anti_aliasing_filter)
    return at_target_loudness(resampled, setup.target_rate).astype(np.float32)


def low_pass_filter(up: int, down: int) -> np.ndarray:
    largest_step = max(up, down)
    tap_count = 2 * FILTER_TAPS_PER_RATE_STEP * largest_step + 1
    return signal.firwin(tap_count, 1.0 / largest_step, window=("kaiser", KAISER_BETA)).astype(np.float32)


def without_offset(audio: np.ndarray) -> np.ndarray:
    return audio - audio.mean()


def gated_loudness_db(audio: np.ndarray, rate: int) -> float:
    block = int(LOUDNESS_BLOCK_SECONDS * rate)
    step = int(LOUDNESS_BLOCK_STEP_SECONDS * rate)
    power_so_far = np.concatenate(([0.0], np.cumsum(audio.astype(np.float64) ** 2)))
    starts = np.arange(0, len(audio) - block + 1, step)
    block_power = (power_so_far[starts + block] - power_so_far[starts]) / block
    block_db = 10.0 * np.log10(np.maximum(block_power, SMALLEST_POWER))
    loud_enough = block_power[block_db > ABSOLUTE_GATE_DB]
    if loud_enough.size == 0:
        return ABSOLUTE_GATE_DB
    relative_gate_db = 10.0 * np.log10(loud_enough.mean()) + RELATIVE_GATE_DB
    return float(10.0 * np.log10(block_power[block_db > max(ABSOLUTE_GATE_DB, relative_gate_db)].mean()))


def at_target_loudness(audio: np.ndarray, rate: int) -> np.ndarray:
    gain = 10.0 ** ((TARGET_LOUDNESS_DB - gated_loudness_db(audio, rate)) / 20.0)
    peak = float(np.abs(audio).max())
    if peak * gain > HIGHEST_PEAK:
        gain = HIGHEST_PEAK / peak
    return audio * gain


def first_frames(flac_file: Path, frames: int) -> np.ndarray:
    audio, rate = soundfile.read(str(flac_file), frames=frames, dtype="float32")
    if rate != SOURCE_RATE:
        raise ValueError(f"{flac_file} is recorded at {rate} Hz")
    return audio
