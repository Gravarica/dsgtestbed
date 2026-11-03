from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np

SAMPLE_SCAN_COUNT = 60
SCAN_DIRECTORY = Path("fetched") / "scans"
GROUND_THICKNESS_METERS = 0.2
STEEPEST_GROUND_TILT_DEGREES = 30.0
CANDIDATES_SCORED_TOGETHER = 8
SMALLEST_TRIANGLE_AREA = 1e-6

Plane = Tuple[np.ndarray, float]


def init_worker(cfg) -> List[np.ndarray]:
    scans = read_lidar_scans(cfg.service_directory / SCAN_DIRECTORY, SAMPLE_SCAN_COUNT)
    return [points_within(scan, cfg.data_quality) for scan in scans]


def process(item, cfg, scans: List[np.ndarray]) -> np.ndarray:
    points = scans[item.sample_index]
    plane = ground_plane(points, int(cfg.attempts), seed=item.sample_index)
    return points_above(points, plane)


def read_lidar_scans(scan_directory: Path, scan_count: int) -> List[np.ndarray]:
    scan_files = sorted(scan_directory.glob("*.bin"))[:scan_count]
    if len(scan_files) < scan_count:
        raise FileNotFoundError(f"{scan_directory} holds {len(scan_files)} scans, {scan_count} are needed. Run just prepare")
    return [np.fromfile(scan_file, dtype=np.float32).reshape(-1, 4) for scan_file in scan_files]


def points_within(scan: np.ndarray, max_distance_meters: float) -> np.ndarray:
    within_distance = np.hypot(scan[:, 0], scan[:, 1]) < max_distance_meters
    return np.ascontiguousarray(scan[within_distance, :3])


def candidate_planes(points: np.ndarray, attempts: int, seed: int) -> Tuple[np.ndarray, np.ndarray]:
    corners = points[np.random.default_rng(seed).integers(0, len(points), size=(attempts, 3))]
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    normals = normals / np.maximum(lengths, SMALLEST_TRIANGLE_AREA)[:, None]
    normals = np.where(normals[:, 2:3] < 0, -normals, normals).astype(np.float32)
    offsets = -np.einsum("ij,ij->i", normals, corners[:, 0]).astype(np.float32)
    return normals, offsets


def points_near_each_plane(points: np.ndarray, normals: np.ndarray, offsets: np.ndarray) -> np.ndarray:
    counts = np.zeros(len(normals), dtype=np.int64)
    for start in range(0, len(normals), CANDIDATES_SCORED_TOGETHER):
        together = slice(start, start + CANDIDATES_SCORED_TOGETHER)
        distances = points @ normals[together].T + offsets[together]
        counts[together] = np.count_nonzero(np.abs(distances) < GROUND_THICKNESS_METERS, axis=0)
    return counts


def ground_plane(points: np.ndarray, attempts: int, seed: int) -> Plane:
    normals, offsets = candidate_planes(points, attempts, seed)
    counts = points_near_each_plane(points, normals, offsets)
    flat_enough = normals[:, 2] >= np.cos(np.radians(STEEPEST_GROUND_TILT_DEGREES))
    best = int(np.argmax(np.where(flat_enough, counts, -1)))
    near_best = np.abs(points @ normals[best] + offsets[best]) < GROUND_THICKNESS_METERS
    return plane_through(points[near_best]) if np.count_nonzero(near_best) >= 3 else (normals[best], float(offsets[best]))


def plane_through(points: np.ndarray) -> Plane:
    centre = points.mean(axis=0, dtype=np.float64)
    spread = np.cov((points - centre).T.astype(np.float64))
    _, directions = np.linalg.eigh(spread)
    normal = directions[:, 0]
    normal = -normal if normal[2] < 0 else normal
    return normal.astype(np.float32), float(-normal @ centre)


def heights_above(points: np.ndarray, plane: Plane) -> np.ndarray:
    normal, offset = plane
    return points @ normal + np.float32(offset)


def points_above(points: np.ndarray, plane: Plane) -> np.ndarray:
    return points[heights_above(points, plane) > GROUND_THICKNESS_METERS]
