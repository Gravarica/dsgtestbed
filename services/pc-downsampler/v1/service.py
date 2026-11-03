from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np

SAMPLE_SCAN_COUNT = 60
SCAN_DIRECTORY = Path("fetched") / "scans"


def init_worker(cfg) -> List[np.ndarray]:
    scans = read_lidar_scans(cfg.service_directory / SCAN_DIRECTORY, SAMPLE_SCAN_COUNT)
    return [points_within_distance(scan, cfg.data_quality) for scan in scans]


def process(item, cfg, scans_within_distance: List[np.ndarray]) -> np.ndarray:
    return voxel_centroids(scans_within_distance[item.sample_index], cfg.voxel_size)


def read_lidar_scans(scan_directory: Path, scan_count: int) -> List[np.ndarray]:
    scan_files = sorted(scan_directory.glob("*.bin"))[:scan_count]
    if len(scan_files) < scan_count:
        raise FileNotFoundError(f"{scan_directory} holds {len(scan_files)} scans, {scan_count} are needed. Run just prepare")
    return [np.fromfile(scan_file, dtype=np.float32).reshape(-1, 4) for scan_file in scan_files]


def points_within_distance(scan: np.ndarray, max_distance_meters: float) -> np.ndarray:
    within_distance = np.hypot(scan[:, 0], scan[:, 1]) < max_distance_meters
    return np.ascontiguousarray(scan[within_distance, :3])


def voxel_of_each_point(points: np.ndarray, voxel_size_meters: float) -> np.ndarray:
    return np.floor(points / voxel_size_meters).astype(np.int64)


def voxel_centroids(points: np.ndarray, voxel_size_meters: float) -> np.ndarray:
    if len(points) == 0:
        return np.zeros((0, 3), dtype=np.float32)
    voxels = voxel_of_each_point(points, voxel_size_meters)
    voxels -= voxels.min(axis=0)
    cells_along_y, cells_along_z = voxels[:, 1].max() + 1, voxels[:, 2].max() + 1
    voxel_number = (voxels[:, 0] * cells_along_y + voxels[:, 1]) * cells_along_z + voxels[:, 2]
    order = np.argsort(voxel_number, kind="stable")
    sorted_numbers = voxel_number[order]
    voxel_starts = np.flatnonzero(np.r_[True, sorted_numbers[1:] != sorted_numbers[:-1]])
    points_per_voxel = np.diff(np.r_[voxel_starts, len(sorted_numbers)])
    coordinate_sums = np.add.reduceat(points[order].astype(np.float64), voxel_starts, axis=0)
    return (coordinate_sums / points_per_voxel[:, None]).astype(np.float32)
