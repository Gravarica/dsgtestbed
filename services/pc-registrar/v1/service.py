from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from scipy.spatial import cKDTree

SAMPLE_PAIR_COUNT = 60
SCAN_DIRECTORY = Path("fetched") / "scans"
GROUND_CUT_HEIGHT_METERS = -1.4
VOXEL_SIZE_METERS = 0.3
FARTHEST_MATCH_METERS = 1.5
FEWEST_MATCHES_FOR_A_MOTION = 3


def init_worker(cfg) -> List[Tuple[np.ndarray, cKDTree]]:
    scans = read_lidar_scans(cfg.service_directory / SCAN_DIRECTORY, SAMPLE_PAIR_COUNT + 1)
    thinned = [thinned_obstacle_points(scan, cfg.data_quality) for scan in scans]
    return [(thinned[index + 1], cKDTree(thinned[index])) for index in range(SAMPLE_PAIR_COUNT)]


def process(item, cfg, scan_pairs: List[Tuple[np.ndarray, cKDTree]]) -> Dict[str, Any]:
    scan, scan_before = scan_pairs[item.sample_index]
    rotation, translation, matched_points, mean_distance = motion_between(scan, scan_before, int(cfg.iterations))
    return {
        "rotation": rotation.tolist(),
        "translation": translation.tolist(),
        "matched_points": matched_points,
        "mean_distance": mean_distance,
    }


def read_lidar_scans(scan_directory: Path, scan_count: int) -> List[np.ndarray]:
    scan_files = sorted(scan_directory.glob("*.bin"))[:scan_count]
    if len(scan_files) < scan_count:
        raise FileNotFoundError(f"{scan_directory} holds {len(scan_files)} scans, {scan_count} are needed. Run just prepare")
    return [np.fromfile(scan_file, dtype=np.float32).reshape(-1, 4) for scan_file in scan_files]


def thinned_obstacle_points(scan: np.ndarray, max_distance_meters: float) -> np.ndarray:
    within_distance = np.hypot(scan[:, 0], scan[:, 1]) < max_distance_meters
    above_ground = scan[:, 2] > GROUND_CUT_HEIGHT_METERS
    points = scan[within_distance & above_ground, :3].astype(np.float64)
    voxel_of_point = np.floor(points / VOXEL_SIZE_METERS).astype(np.int64)
    _, first_point_in_voxel = np.unique(voxel_of_point, axis=0, return_index=True)
    return np.ascontiguousarray(points[np.sort(first_point_in_voxel)])


def motion_between(scan: np.ndarray, scan_before: cKDTree, iterations: int) -> Tuple[np.ndarray, np.ndarray, int, float]:
    rotation, translation = np.eye(3), np.zeros(3)
    matched_points, mean_distance = 0, 0.0
    for _ in range(iterations):
        moved = scan @ rotation.T + translation
        distances, nearest = scan_before.query(moved, k=1, distance_upper_bound=FARTHEST_MATCH_METERS, workers=1)
        matched = np.isfinite(distances)
        matched_points = int(matched.sum())
        if matched_points < FEWEST_MATCHES_FOR_A_MOTION:
            break
        mean_distance = float(distances[matched].mean())
        step_rotation, step_translation = rigid_motion(moved[matched], scan_before.data[nearest[matched]])
        rotation = step_rotation @ rotation
        translation = step_rotation @ translation + step_translation
    return rotation, translation, matched_points, mean_distance


def rigid_motion(points: np.ndarray, targets: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    point_centre, target_centre = points.mean(axis=0), targets.mean(axis=0)
    covariance = (points - point_centre).T @ (targets - target_centre)
    left, _, right_transposed = np.linalg.svd(covariance)
    mirror_fix = np.diag([1.0, 1.0, np.sign(np.linalg.det(right_transposed.T @ left.T))])
    rotation = right_transposed.T @ mirror_fix @ left.T
    return rotation, target_centre - rotation @ point_centre
