from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d
from sklearn.ensemble import IsolationForest

STREAMS_FILE = Path("data") / "streams.npz"
BASELINE_WIDTH = 201
SMOOTHING_WIDTH = 9
MAD_TO_STANDARD_DEVIATION = 1.4826
FIXED_SEED = 0
FOREST_BY_MODEL_SIZE = {2: {"trees": 100, "samples_per_tree": 256}, 3: {"trees": 400, "samples_per_tree": 1024}}
DETECTOR_NAMES = {1: "robust_z_score", 2: "isolation_forest_small", 3: "isolation_forest_large"}


@dataclass
class Streams:
    windows: np.ndarray


def init_worker(cfg) -> Streams:
    with np.load(Path(cfg.service_directory) / STREAMS_FILE) as stored:
        windows = np.array(stored["streams"][:, : int(cfg.window_length)], dtype=np.float64)
    return Streams(windows=windows)


def process(item, cfg, streams: Streams) -> dict:
    window = streams.windows[item.sample_index]
    model_size = int(cfg.model_size)
    positions = np.flatnonzero(robust_z_scores(anomaly_scores(window, model_size)) > float(cfg.threshold))
    return {
        "sample": int(item.sample_index),
        "detector": DETECTOR_NAMES[model_size],
        "readings": int(len(window)),
        "anomalies": positions.tolist(),
    }


def anomaly_scores(window: np.ndarray, model_size: int) -> np.ndarray:
    residual = window - median_filter(window, size=BASELINE_WIDTH, mode="reflect")
    if model_size == 1:
        return np.abs(residual - np.median(residual))
    features = np.column_stack(
        [residual, uniform_filter1d(residual, SMOOTHING_WIDTH), np.diff(window, prepend=window[0])]
    )
    forest_size = FOREST_BY_MODEL_SIZE[model_size]
    forest = IsolationForest(
        n_estimators=forest_size["trees"],
        max_samples=min(forest_size["samples_per_tree"], len(window)),
        random_state=FIXED_SEED,
        n_jobs=1,
    ).fit(features)
    return -forest.score_samples(features)


def robust_z_scores(scores: np.ndarray) -> np.ndarray:
    centre = np.median(scores)
    spread = MAD_TO_STANDARD_DEVIATION * np.median(np.abs(scores - centre))
    return (scores - centre) / max(spread, np.finfo(float).eps)
