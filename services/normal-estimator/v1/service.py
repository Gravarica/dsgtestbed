from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np
from scipy.spatial import cKDTree

SAMPLE_SCAN_COUNT = 60
SCAN_DIRECTORY = Path("fetched") / "scans"
THINNING_VOXEL_SIZE_METERS = 0.3
KD_TREE_THREADS = 1


def init_worker(cfg) -> List[np.ndarray]:
    scans = read_lidar_scans(cfg.service_directory / SCAN_DIRECTORY, SAMPLE_SCAN_COUNT)
    return [thinned_points_within(scan, cfg.data_quality) for scan in scans]


def process(item, cfg, thinned_scans: List[np.ndarray]) -> np.ndarray:
    return surface_normals(thinned_scans[item.sample_index], int(cfg.neighbours))


def read_lidar_scans(scan_directory: Path, scan_count: int) -> List[np.ndarray]:
    scan_files = sorted(scan_directory.glob("*.bin"))[:scan_count]
    if len(scan_files) < scan_count:
        raise FileNotFoundError(f"{scan_directory} holds {len(scan_files)} scans, {scan_count} are needed. Run just prepare")
    return [np.fromfile(scan_file, dtype=np.float32).reshape(-1, 4) for scan_file in scan_files]


def thinned_points_within(scan: np.ndarray, max_distance_meters: float) -> np.ndarray:
    points = scan[np.hypot(scan[:, 0], scan[:, 1]) < max_distance_meters, :3]
    voxel_of_point = np.floor(points / THINNING_VOXEL_SIZE_METERS).astype(np.int64)
    _, first_point_in_voxel = np.unique(voxel_of_point, axis=0, return_index=True)
    return np.ascontiguousarray(points[np.sort(first_point_in_voxel)], dtype=np.float64)


def surface_normals(points: np.ndarray, neighbour_count: int) -> np.ndarray:
    if len(points) == 0:
        return np.zeros((0, 3), dtype=np.float32)
    neighbours_asked = min(neighbour_count, len(points))
    _, neighbour_indices = cKDTree(points).query(points, k=neighbours_asked, workers=KD_TREE_THREADS)
    neighbourhoods = points[neighbour_indices.reshape(len(points), neighbours_asked)]
    centred = neighbourhoods - neighbourhoods.mean(axis=1, keepdims=True)
    covariances = np.einsum("pni,pnj->pij", centred, centred)
    _, directions = np.linalg.eigh(covariances)
    normals = directions[:, :, 0]
    facing_away_from_the_sensor = np.einsum("pi,pi->p", normals, points) > 0
    normals[facing_away_from_the_sensor] *= -1
    return normals.astype(np.float32)
