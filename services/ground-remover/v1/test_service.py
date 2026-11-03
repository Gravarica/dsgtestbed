import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
SENSOR_HEIGHT_RANGE_METERS = (1.4, 2.0)
STEEPEST_ROAD_TILT_DEGREES = 8.0


def settings(data_quality=30, attempts=100):
    return SimpleNamespace(
        data_quality=data_quality,
        attempts=attempts,
        service_directory=SERVICE_DIRECTORY,
        native_threads_per_worker=1,
    )


def first_real_scan():
    return service.read_lidar_scans(SERVICE_DIRECTORY / service.SCAN_DIRECTORY, 1)[0]


def test_proof():
    cfg = settings()
    scans = service.init_worker(cfg)
    assert len(scans) == service.SAMPLE_SCAN_COUNT
    for sample_index, points in enumerate(scans):
        normal, offset = service.ground_plane(points, cfg.attempts, seed=sample_index)
        tilt_degrees = np.degrees(np.arccos(min(1.0, float(normal[2]))))
        assert tilt_degrees < STEEPEST_ROAD_TILT_DEGREES
        assert SENSOR_HEIGHT_RANGE_METERS[0] < offset < SENSOR_HEIGHT_RANGE_METERS[1]
        kept = service.process(WorkItem(sample_index=sample_index, payload=None), cfg, scans)
        removed_share = 1 - len(kept) / len(points)
        assert 0.15 < removed_share < 0.9
        assert np.all(kept @ normal + offset > service.GROUND_THICKNESS_METERS)
        assert np.median(kept[:, 2]) > np.median(points[:, 2])


def test_distance_knob_keeps_more_points_when_higher():
    scan = first_real_scan()
    assert len(service.points_within(scan, 60)) > len(service.points_within(scan, 6))


def test_attempts_knob_sets_the_number_of_planes_that_are_tried():
    points = service.points_within(first_real_scan(), 30)
    few_normals, _ = service.candidate_planes(points, 20, seed=0)
    many_normals, _ = service.candidate_planes(points, 400, seed=0)
    assert (len(few_normals), len(many_normals)) == (20, 400)
    assert len(service.points_near_each_plane(points, many_normals, np.zeros(400, dtype=np.float32))) == 400


def test_the_same_scan_gives_the_same_plane_again():
    points = service.points_within(first_real_scan(), 30)
    first_normal, first_offset = service.ground_plane(points, 100, seed=3)
    second_normal, second_offset = service.ground_plane(points, 100, seed=3)
    assert np.array_equal(first_normal, second_normal) and first_offset == second_offset


def test_a_box_on_a_flat_floor_is_kept_and_the_floor_is_removed():
    randomness = np.random.default_rng(1)
    floor = np.column_stack([randomness.uniform(-20, 20, 4000), randomness.uniform(-20, 20, 4000), np.full(4000, -1.7)])
    box = np.column_stack([randomness.uniform(4, 5, 300), randomness.uniform(1, 2, 300), randomness.uniform(-1.2, 0.0, 300)])
    points = np.vstack([floor, box]).astype(np.float32)
    kept = service.points_above(points, service.ground_plane(points, 50, seed=0))
    assert len(kept) == len(box)
    assert kept[:, 2].min() > -1.5


def test_output_is_an_array_of_points():
    cfg = settings()
    scans = service.init_worker(cfg)
    kept = service.process(WorkItem(sample_index=1, payload=None), cfg, scans)
    assert isinstance(kept, np.ndarray)
    assert kept.ndim == 2 and kept.shape[1] == 3 and len(kept) > 0
