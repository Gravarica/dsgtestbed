from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np
import soundfile

SAMPLE_RATE = 16000
LOWEST_VOICE_HZ = 80.0
HIGHEST_VOICE_HZ = 4000.0
SHARE_OF_FRAMES_TAKEN_AS_NOISE = 0.1
WEIGHT_OF_THE_PREVIOUS_FRAME = 0.98
WEIGHT_OF_THE_OLD_NOISE = 0.95
SMALLEST_POWER = 1e-12
SMALLEST_SPEECH_TO_NOISE = 1e-3
LARGEST_FRAME_TO_NOISE = 1000.0
LEAST_LIKELIHOOD_RATIO = 0.5
LOUD_FRAME_PERCENTILE = 95
DECIBELS_BELOW_LOUD_STILL_SPEECH = 35.0
FLATTEST_SPECTRUM_OF_A_VOICE = 0.35
SECONDS_SPEECH_LINGERS = 0.08
SHORTEST_PAUSE_SECONDS = 0.2
SHORTEST_SPEECH_SECONDS = 0.1


@dataclass
class DetectorSetup:
    clip_ids: List[str]
    audio: List[np.ndarray]
    frame_samples: int
    hop_samples: int
    fft_size: int
    window: np.ndarray
    voice_bins: slice


def init_worker(cfg) -> DetectorSetup:
    clips_directory = Path(cfg.service_directory) / "fetched" / "clips"
    clip_ids = sorted(json.loads((clips_directory / "transcripts.json").read_text()))
    samples_per_clip = int(cfg.data_quality) * SAMPLE_RATE
    frame_samples = int(cfg.frame_length) * SAMPLE_RATE // 1000
    fft_size = next_power_of_two(frame_samples)
    hz_per_bin = SAMPLE_RATE / fft_size
    return DetectorSetup(
        clip_ids=clip_ids,
        audio=[first_samples(clips_directory / f"{clip_id}.flac", samples_per_clip) for clip_id in clip_ids],
        frame_samples=frame_samples,
        hop_samples=frame_samples // 2,
        fft_size=fft_size,
        window=np.hanning(frame_samples).astype(np.float32),
        voice_bins=slice(int(np.ceil(LOWEST_VOICE_HZ / hz_per_bin)), int(HIGHEST_VOICE_HZ / hz_per_bin) + 1),
    )


def process(item, cfg, setup: DetectorSetup) -> List[List[float]]:
    audio = setup.audio[item.sample_index]
    frames = framed(audio, setup.frame_samples, setup.hop_samples) * setup.window
    power = (np.abs(np.fft.rfft(frames, n=setup.fft_size, axis=1)) ** 2)[:, setup.voice_bins].astype(np.float64)
    power = np.maximum(power, SMALLEST_POWER)
    likely = likelihood_ratios(power) > LEAST_LIKELIHOOD_RATIO
    spoken = smoothed(likely & loud_enough(power) & shaped_like_a_voice(power), setup.hop_samples)
    return segments_in_seconds(spoken, setup.hop_samples, len(audio))


def likelihood_ratios(power: np.ndarray) -> np.ndarray:
    noise = noise_of_the_quietest_frames(power)
    speech_before = np.zeros(power.shape[1])
    ratios = np.empty(len(power))
    for position, frame in enumerate(power):
        frame_to_noise = np.minimum(frame / noise, LARGEST_FRAME_TO_NOISE)
        speech_to_noise = WEIGHT_OF_THE_PREVIOUS_FRAME * speech_before / noise + (1 - WEIGHT_OF_THE_PREVIOUS_FRAME) * np.maximum(
            frame_to_noise - 1.0, 0.0
        )
        speech_to_noise = np.maximum(speech_to_noise, SMALLEST_SPEECH_TO_NOISE)
        share_of_speech = speech_to_noise / (1.0 + speech_to_noise)
        ratios[position] = np.mean(frame_to_noise * share_of_speech - np.log1p(speech_to_noise))
        speech_before = share_of_speech**2 * frame
        if ratios[position] <= LEAST_LIKELIHOOD_RATIO:
            noise = WEIGHT_OF_THE_OLD_NOISE * noise + (1 - WEIGHT_OF_THE_OLD_NOISE) * frame
    return ratios


def noise_of_the_quietest_frames(power: np.ndarray) -> np.ndarray:
    frame_energy = power.sum(axis=1)
    quiet_count = max(1, int(SHARE_OF_FRAMES_TAKEN_AS_NOISE * len(power)))
    quietest = np.argpartition(frame_energy, quiet_count - 1)[:quiet_count]
    return power[quietest].mean(axis=0)


def loud_enough(power: np.ndarray) -> np.ndarray:
    decibels = 10.0 * np.log10(power.sum(axis=1))
    return decibels > np.percentile(decibels, LOUD_FRAME_PERCENTILE) - DECIBELS_BELOW_LOUD_STILL_SPEECH


def shaped_like_a_voice(power: np.ndarray) -> np.ndarray:
    flatness = np.exp(np.log(power).mean(axis=1)) / power.mean(axis=1)
    return flatness < FLATTEST_SPECTRUM_OF_A_VOICE


def smoothed(spoken: np.ndarray, hop_samples: int) -> np.ndarray:
    frames_per_second = SAMPLE_RATE / hop_samples
    lingering = widened(spoken, int(round(SECONDS_SPEECH_LINGERS * frames_per_second)))
    without_short_pauses = ~without_short_runs(~lingering, int(round(SHORTEST_PAUSE_SECONDS * frames_per_second)))
    return without_short_runs(without_short_pauses, int(round(SHORTEST_SPEECH_SECONDS * frames_per_second)))


def widened(flags: np.ndarray, frames: int) -> np.ndarray:
    if frames < 1:
        return flags.copy()
    padded = np.concatenate([np.zeros(frames, dtype=bool), flags, np.zeros(frames, dtype=bool)])
    return np.lib.stride_tricks.sliding_window_view(padded, 2 * frames + 1).any(axis=1)


def runs_of(flags: np.ndarray) -> np.ndarray:
    edges = np.flatnonzero(np.diff(np.concatenate([[False], flags, [False]]).astype(np.int8)))
    return edges.reshape(-1, 2)


def without_short_runs(flags: np.ndarray, least_frames: int) -> np.ndarray:
    kept = flags.copy()
    for start, end in runs_of(flags):
        if end - start < least_frames:
            kept[start:end] = False
    return kept


def segments_in_seconds(spoken: np.ndarray, hop_samples: int, sample_count: int) -> List[List[float]]:
    clip_seconds = sample_count / SAMPLE_RATE
    return [
        [start * hop_samples / SAMPLE_RATE, min(end * hop_samples / SAMPLE_RATE, clip_seconds)]
        for start, end in runs_of(spoken)
    ]


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
