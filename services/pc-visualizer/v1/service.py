from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np

SAMPLE_SCAN_COUNT = 60
SCAN_DIRECTORY = Path("data") / "2011_09_26" / "2011_09_26_drive_0001_sync" / "velodyne_points" / "data"
METERS_PER_PIXEL = 0.1
POINT_COLOR = [255, 255, 255]


def init_worker(cfg) -> List[np.ndarray]:
    return read_lidar_scans(cfg.service_directory / SCAN_DIRECTORY, SAMPLE_SCAN_COUNT)


def process(item, cfg, scans: List[np.ndarray]):
    return birds_eye_view(scans[item.sample_index], cfg.data_quality)


def read_lidar_scans(scan_directory: Path, scan_count: int) -> List[np.ndarray]:
    scan_files = sorted(scan_directory.glob("*.bin"))[:scan_count]
    if len(scan_files) < scan_count:
        raise FileNotFoundError(f"{scan_directory} holds {len(scan_files)} scans, {scan_count} are needed. See data/README.md")
    return [np.fromfile(scan_file, dtype=np.float32).reshape(-1, 4) for scan_file in scan_files]


def birds_eye_view(points: np.ndarray, max_distance_meters: int) -> np.ndarray:
    near = points[np.sqrt(points[:, 0] ** 2 + points[:, 1] ** 2) < max_distance_meters]
    half_side = max_distance_meters / METERS_PER_PIXEL
    columns = np.int32(near[:, 0] / METERS_PER_PIXEL + half_side)
    rows = np.int32(near[:, 1] / METERS_PER_PIXEL + half_side)
    side = int(2 * half_side)
    view = np.zeros((side, side, 3), dtype=np.uint8)
    view[rows, columns] = POINT_COLOR
    return view
