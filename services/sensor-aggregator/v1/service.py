from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np

BAND_EDGES_HZ = (0.0, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0)
PERCENTILES = (5.0, 50.0, 95.0)
AUTOCORRELATION_LAGS = 32
SPECTRAL = ("spectral", "full")
OUTLIER_DEVIATIONS = 3.5
READINGS_PER_SEGMENT = 100


@dataclass
class Windows:
    readings: np.ndarray
    readings_per_second: float


def init_worker(cfg) -> Windows:
    readings_directory = Path(cfg.service_directory) / "fetched" / "readings"
    layout = json.loads((readings_directory / "windows.json").read_text())
    shape = (layout["windows"], layout["channels"], layout["readings_per_window"])
    everything = np.fromfile(readings_directory / "readings.f32", dtype="<f4").reshape(shape)
    kept = everything[:, : int(cfg.channels), : int(cfg.window_length)].astype(np.float64)
    return Windows(readings=np.ascontiguousarray(kept), readings_per_second=float(layout["readings_per_second"]))


def process(item, cfg, windows: Windows) -> Dict:
    window = windows.readings[item.sample_index]
    per_channel = basic_statistics(window)
    record = {"readings_per_channel": int(window.shape[1]), "channel_count": int(window.shape[0])}
    if cfg.feature_set in SPECTRAL:
        per_channel.update(spectral_features(window, windows.readings_per_second))
    if cfg.feature_set == "full":
        per_channel.update(autocorrelations(window))
        record["correlations"] = np.corrcoef(window).tolist() if window.shape[0] > 1 else [[1.0]]
    record["channels"] = channel_records(per_channel, window.shape[0])
    return record


def basic_statistics(window: np.ndarray) -> Dict[str, np.ndarray]:
    positions = np.arange(window.shape[1], dtype=np.float64)
    centred_positions = positions - positions.mean()
    means = window.mean(axis=1)
    slopes = ((window - means[:, None]) @ centred_positions) / max(float(centred_positions @ centred_positions), 1.0)
    low, median, high = np.percentile(window, PERCENTILES, axis=1)
    deviations = window - means[:, None]
    standard_deviations = window.std(axis=1)
    scale = np.maximum(standard_deviations, 1e-12)
    absolute_from_median = np.abs(window - median[:, None])
    median_absolute_deviations = np.median(absolute_from_median, axis=1)
    return {
        "mean": means,
        "std": standard_deviations,
        "min": window.min(axis=1),
        "max": window.max(axis=1),
        "p05": low,
        "p50": median,
        "p95": high,
        "slope_per_reading": slopes,
        "median_absolute_deviation": median_absolute_deviations,
        "skewness": (deviations**3).mean(axis=1) / scale**3,
        "kurtosis": (deviations**4).mean(axis=1) / scale**4,
        "outlier_count": (absolute_from_median > OUTLIER_DEVIATIONS * np.maximum(median_absolute_deviations, 1e-12)[:, None]).sum(axis=1),
        "mean_crossing_rate": (np.diff(np.signbit(deviations), axis=1)).mean(axis=1),
        "per_segment": segment_summaries(window),
    }


def segment_summaries(window: np.ndarray) -> np.ndarray:
    readings_per_segment = min(READINGS_PER_SEGMENT, window.shape[1])
    segment_count = window.shape[1] // readings_per_segment
    whole_segments = window[:, : segment_count * readings_per_segment]
    segments = whole_segments.reshape(window.shape[0], segment_count, readings_per_segment)
    return np.stack([segments.mean(axis=2), segments.min(axis=2), segments.max(axis=2)], axis=2)


def spectral_features(window: np.ndarray, readings_per_second: float) -> Dict[str, np.ndarray]:
    detrended = window - window.mean(axis=1, keepdims=True)
    power = np.abs(np.fft.rfft(detrended * np.hanning(window.shape[1]), axis=1)) ** 2
    frequencies = np.fft.rfftfreq(window.shape[1], d=1.0 / readings_per_second)
    band_energies = np.stack(
        [power[:, (frequencies >= low) & (frequencies < high)].sum(axis=1) for low, high in zip(BAND_EDGES_HZ, BAND_EDGES_HZ[1:])],
        axis=1,
    )
    shares = power[:, 1:] / np.maximum(power[:, 1:].sum(axis=1, keepdims=True), 1e-300)
    entropy = -(shares * np.log(np.maximum(shares, 1e-300))).sum(axis=1)
    return {
        "band_energies": band_energies,
        "dominant_frequency_hz": frequencies[1 + np.argmax(power[:, 1:], axis=1)],
        "spectral_entropy": entropy,
    }


def autocorrelations(window: np.ndarray) -> Dict[str, np.ndarray]:
    length = window.shape[1]
    centred = window - window.mean(axis=1, keepdims=True)
    spectrum = np.fft.rfft(centred, n=2 * length, axis=1)
    correlation = np.fft.irfft(np.abs(spectrum) ** 2, axis=1)[:, : AUTOCORRELATION_LAGS + 1]
    return {"autocorrelation": correlation[:, 1:] / np.maximum(correlation[:, :1], 1e-300)}


def channel_records(per_channel: Dict[str, np.ndarray], channel_count: int) -> List[Dict]:
    as_lists = {name: values.tolist() for name, values in per_channel.items()}
    return [{name: values[channel] for name, values in as_lists.items()} for channel in range(channel_count)]
