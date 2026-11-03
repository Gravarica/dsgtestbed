from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import List

import numpy as np

SAMPLE_SCAN_COUNT = 60
SCAN_DIRECTORY = Path("fetched") / "scans"
CELL_SIZE_METERS_BY_PRECISION = {1: 0.08, 2: 0.04, 3: 0.02, 4: 0.01}
BITS_PER_AXIS = 21
HEADER = struct.Struct("<Id3q")
BYTES_PER_CODE = 8
ZLIB_LEVEL = 6


def init_worker(cfg) -> List[np.ndarray]:
    scans = read_lidar_scans(cfg.service_directory / SCAN_DIRECTORY, SAMPLE_SCAN_COUNT)
    return [points_within_distance(scan, cfg.data_quality) for scan in scans]


def process(item, cfg, scans: List[np.ndarray]) -> bytes:
    return encoded_scan(scans[item.sample_index], cell_size_of(cfg.precision))


def cell_size_of(precision: int) -> float:
    return CELL_SIZE_METERS_BY_PRECISION[int(precision)]


def read_lidar_scans(scan_directory: Path, scan_count: int) -> List[np.ndarray]:
    scan_files = sorted(scan_directory.glob("*.bin"))[:scan_count]
    if len(scan_files) < scan_count:
        raise FileNotFoundError(f"{scan_directory} holds {len(scan_files)} scans, {scan_count} are needed. Run just prepare")
    return [np.fromfile(scan_file, dtype=np.float32).reshape(-1, 4) for scan_file in scan_files]


def points_within_distance(scan: np.ndarray, max_distance_meters: float) -> np.ndarray:
    within_distance = np.hypot(scan[:, 0], scan[:, 1]) < max_distance_meters
    return np.ascontiguousarray(scan[within_distance, :3])


def cells_of(points: np.ndarray, cell_size_meters: float) -> np.ndarray:
    return np.rint(points.astype(np.float64) / cell_size_meters).astype(np.int64)


def spread_bits(values: np.ndarray) -> np.ndarray:
    spread = values.astype(np.uint64) & np.uint64(0x1FFFFF)
    spread = (spread | (spread << np.uint64(32))) & np.uint64(0x1F00000000FFFF)
    spread = (spread | (spread << np.uint64(16))) & np.uint64(0x1F0000FF0000FF)
    spread = (spread | (spread << np.uint64(8))) & np.uint64(0x100F00F00F00F00F)
    spread = (spread | (spread << np.uint64(4))) & np.uint64(0x10C30C30C30C30C3)
    spread = (spread | (spread << np.uint64(2))) & np.uint64(0x1249249249249249)
    return spread


def gathered_bits(spread: np.ndarray) -> np.ndarray:
    values = spread & np.uint64(0x1249249249249249)
    values = (values | (values >> np.uint64(2))) & np.uint64(0x10C30C30C30C30C3)
    values = (values | (values >> np.uint64(4))) & np.uint64(0x100F00F00F00F00F)
    values = (values | (values >> np.uint64(8))) & np.uint64(0x1F0000FF0000FF)
    values = (values | (values >> np.uint64(16))) & np.uint64(0x1F00000000FFFF)
    values = (values | (values >> np.uint64(32))) & np.uint64(0x1FFFFF)
    return values


def morton_codes(cells_from_lowest: np.ndarray) -> np.ndarray:
    return (
        spread_bits(cells_from_lowest[:, 0])
        | (spread_bits(cells_from_lowest[:, 1]) << np.uint64(1))
        | (spread_bits(cells_from_lowest[:, 2]) << np.uint64(2))
    )


def sorted_codes_and_lowest_cell(points: np.ndarray, cell_size_meters: float):
    cells = cells_of(points, cell_size_meters)
    lowest_cell = cells.min(axis=0) if len(cells) else np.zeros(3, dtype=np.int64)
    return np.sort(morton_codes(cells - lowest_cell)), lowest_cell


def encoded_scan(points: np.ndarray, cell_size_meters: float) -> bytes:
    codes, lowest_cell = sorted_codes_and_lowest_cell(points, cell_size_meters)
    steps = np.diff(codes, prepend=np.uint64(0))
    bytes_by_significance = steps.view(np.uint8).reshape(-1, BYTES_PER_CODE).T
    header = HEADER.pack(len(codes), cell_size_meters, *(int(cell) for cell in lowest_cell))
    return header + zlib.compress(np.ascontiguousarray(bytes_by_significance).tobytes(), ZLIB_LEVEL)


def decoded_points(encoded: bytes) -> np.ndarray:
    point_count, cell_size_meters, *lowest_cell = HEADER.unpack_from(encoded)
    packed = np.frombuffer(zlib.decompress(encoded[HEADER.size :]), dtype=np.uint8)
    steps = np.ascontiguousarray(packed.reshape(BYTES_PER_CODE, point_count).T).view(np.uint64).reshape(-1)
    codes = np.cumsum(steps, dtype=np.uint64)
    cells = np.stack(
        [gathered_bits(codes), gathered_bits(codes >> np.uint64(1)), gathered_bits(codes >> np.uint64(2))], axis=1
    ).astype(np.int64) + np.array(lowest_cell, dtype=np.int64)
    return cells * cell_size_meters
