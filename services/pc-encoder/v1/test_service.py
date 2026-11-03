import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
RAW_BYTES_PER_POINT = 12
SMALLEST_SHRINK_AT_DEFAULT = 3.0


def settings(data_quality=30, precision=2):
    return SimpleNamespace(
        data_quality=data_quality,
        precision=precision,
        service_directory=SERVICE_DIRECTORY,
        native_threads_per_worker=1,
    )


def first_real_scan():
    return service.read_lidar_scans(SERVICE_DIRECTORY / service.SCAN_DIRECTORY, 1)[0]


def originals_in_encoded_order(points, cell_size_meters):
    cells = service.cells_of(points, cell_size_meters)
    codes = service.morton_codes(cells - cells.min(axis=0))
    return points[np.argsort(codes, kind="stable")]


def test_proof():
    cfg = settings()
    scans = service.init_worker(cfg)
    assert len(scans) == service.SAMPLE_SCAN_COUNT
    cell_size = service.cell_size_of(cfg.precision)
    for sample_index, points in enumerate(scans):
        encoded = service.process(WorkItem(sample_index=sample_index, payload=None), cfg, scans)
        decoded = service.decoded_points(encoded)
        assert len(points) > 10000
        assert decoded.shape == points.shape
        distance_per_axis = np.abs(decoded - originals_in_encoded_order(points, cell_size))
        assert distance_per_axis.max() <= cell_size / 2 + 1e-6
        assert len(encoded) * SMALLEST_SHRINK_AT_DEFAULT < len(points) * RAW_BYTES_PER_POINT


def test_distance_knob_keeps_more_points_and_gives_more_bytes_when_higher():
    scan = first_real_scan()
    near = service.points_within_distance(scan, 6)
    far = service.points_within_distance(scan, 60)
    assert len(far) > len(near)
    assert len(service.encoded_scan(far, 0.04)) > len(service.encoded_scan(near, 0.04))


def test_precision_knob_gives_smaller_cells_and_more_bytes_when_higher():
    points = service.points_within_distance(first_real_scan(), 30)
    coarse = service.encoded_scan(points, service.cell_size_of(1))
    fine = service.encoded_scan(points, service.cell_size_of(4))
    assert service.cell_size_of(4) < service.cell_size_of(1)
    assert len(fine) > len(coarse)
    coarse_error = np.abs(service.decoded_points(coarse) - originals_in_encoded_order(points, service.cell_size_of(1))).max()
    fine_error = np.abs(service.decoded_points(fine) - originals_in_encoded_order(points, service.cell_size_of(4))).max()
    assert fine_error < coarse_error


def test_bits_spread_for_the_space_filling_order_are_gathered_back():
    values = np.array([0, 1, 2, 1000, 2**21 - 1], dtype=np.int64)
    assert np.array_equal(service.gathered_bits(service.spread_bits(values)).astype(np.int64), values)


def test_output_is_bytes():
    cfg = settings()
    scans = service.init_worker(cfg)
    encoded = service.process(WorkItem(sample_index=1, payload=None), cfg, scans)
    assert isinstance(encoded, bytes)
    assert len(encoded) > service.HEADER.size
