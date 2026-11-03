from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

SAMPLE_SCAN_COUNT = 60
SCAN_DIRECTORY = Path("fetched") / "scans"
GROUND_CUT_HEIGHT_METERS = -1.4
MIN_POINTS_PER_OBJECT = 3


def init_worker(cfg) -> List[np.ndarray]:
    scans = read_lidar_scans(cfg.service_directory / SCAN_DIRECTORY, SAMPLE_SCAN_COUNT)
    return [downsampled_obstacle_points(scan, cfg.data_quality, cfg.voxel_size) for scan in scans]


def process(item, cfg, downsampled_scans: List[np.ndarray]) -> List[Dict[str, List[float]]]:
    points = downsampled_scans[item.sample_index]
    return object_boxes(points, object_labels(points, cfg.cluster_distance))


def read_lidar_scans(scan_directory: Path, scan_count: int) -> List[np.ndarray]:
    scan_files = sorted(scan_directory.glob("*.bin"))[:scan_count]
    if len(scan_files) < scan_count:
        raise FileNotFoundError(f"{scan_directory} holds {len(scan_files)} scans, {scan_count} are needed. Run just prepare")
    return [np.fromfile(scan_file, dtype=np.float32).reshape(-1, 4) for scan_file in scan_files]


def downsampled_obstacle_points(scan: np.ndarray, max_distance_meters: float, voxel_size_meters: float) -> np.ndarray:
    within_distance = np.hypot(scan[:, 0], scan[:, 1]) < max_distance_meters
    above_ground = scan[:, 2] > GROUND_CUT_HEIGHT_METERS
    points = scan[within_distance & above_ground, :3]
    voxel_of_point = np.floor(points / voxel_size_meters).astype(np.int64)
    _, first_point_in_voxel = np.unique(voxel_of_point, axis=0, return_index=True)
    return np.ascontiguousarray(points[np.sort(first_point_in_voxel)])


def object_labels(points: np.ndarray, cluster_distance_meters: float) -> np.ndarray:
    point_count = len(points)
    if point_count == 0:
        return np.zeros(0, dtype=np.int32)
    close_pairs = cKDTree(points).query_pairs(cluster_distance_meters, output_type="ndarray")
    neighbours = coo_matrix(
        (np.ones(len(close_pairs), dtype=np.int8), (close_pairs[:, 0], close_pairs[:, 1])),
        shape=(point_count, point_count),
    )
    _, labels = connected_components(neighbours, directed=False)
    return labels


def object_boxes(points: np.ndarray, labels: np.ndarray) -> List[Dict[str, List[float]]]:
    if len(points) == 0:
        return []
    order = np.argsort(labels, kind="stable")
    sorted_labels = labels[order]
    sorted_points = points[order]
    group_starts = np.flatnonzero(np.r_[True, sorted_labels[1:] != sorted_labels[:-1]])
    group_sizes = np.diff(np.r_[group_starts, len(sorted_labels)])
    lowest_corners = np.minimum.reduceat(sorted_points, group_starts, axis=0)
    highest_corners = np.maximum.reduceat(sorted_points, group_starts, axis=0)
    large_enough = group_sizes >= MIN_POINTS_PER_OBJECT
    return [
        {"low": low.tolist(), "high": high.tolist(), "points": int(size)}
        for low, high, size in zip(lowest_corners[large_enough], highest_corners[large_enough], group_sizes[large_enough])
    ]
