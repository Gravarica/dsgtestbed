import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
GROUND_BELOW_HEIGHT_METERS = -1.5
GROUND_WITHIN_DISTANCE_METERS = 10.0
UP = np.array([0.0, 0.0, 1.0])


def settings(data_quality=30, neighbours=10):
    return SimpleNamespace(
        data_quality=data_quality,
        neighbours=neighbours,
        service_directory=SERVICE_DIRECTORY,
        native_threads_per_worker=1,
    )


def first_real_scan():
    return service.read_lidar_scans(SERVICE_DIRECTORY / service.SCAN_DIRECTORY, 1)[0]


def tilted_plane(point_count=2000, seed=3):
    randomness = np.random.default_rng(seed)
    along, across = randomness.uniform(-5, 5, size=(2, point_count))
    first_direction = np.array([1.0, 0.0, 0.5]) / np.linalg.norm([1.0, 0.0, 0.5])
    second_direction = np.array([0.0, 1.0, 0.0])
    points = np.outer(along, first_direction) + np.outer(across, second_direction) + np.array([0.0, 0.0, 20.0])
    return points, np.cross(first_direction, second_direction)


def test_proof():
    cfg = settings()
    scans = service.init_worker(cfg)
    assert len(scans) == service.SAMPLE_SCAN_COUNT
    plane_points, plane_normal = tilted_plane()
    plane_normals = service.surface_normals(plane_points, cfg.neighbours)
    assert np.abs(plane_normals @ plane_normal).min() > 0.999
    for sample_index in (0, 29, 59):
        points = scans[sample_index]
        normals = service.process(WorkItem(sample_index=sample_index, payload=None), cfg, scans)
        assert normals.shape == points.shape
        assert len(normals) > 1000
        assert np.allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-4)
        on_the_ground = (points[:, 2] < GROUND_BELOW_HEIGHT_METERS) & (
            np.hypot(points[:, 0], points[:, 1]) < GROUND_WITHIN_DISTANCE_METERS
        )
        assert on_the_ground.sum() > 200
        upward_share_of_ground_normals = np.abs(normals[on_the_ground] @ UP)
        assert np.median(upward_share_of_ground_normals) > 0.95
        assert np.all(np.einsum("pi,pi->p", normals, points) <= 1e-6)


def test_distance_knob_keeps_more_points_when_higher():
    scan = first_real_scan()
    near = service.thinned_points_within(scan, 6)
    far = service.thinned_points_within(scan, 60)
    assert len(far) > 2 * len(near)
    assert np.hypot(near[:, 0], near[:, 1]).max() < 6


def test_neighbours_knob_smooths_the_normals_of_a_noisy_plane():
    randomness = np.random.default_rng(11)
    flat = np.column_stack([randomness.uniform(-5, 5, size=(2, 3000)).T, randomness.normal(0, 0.03, size=3000)])
    flat[:, 2] += 20.0
    error_with_few = 1 - np.abs(service.surface_normals(flat, 5) @ UP)
    error_with_many = 1 - np.abs(service.surface_normals(flat, 40) @ UP)
    assert error_with_many.mean() < error_with_few.mean() / 2


def test_fewer_points_than_neighbours_still_gives_one_normal_per_point():
    points = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0], [2.0, 1.0, 0.0]])
    normals = service.surface_normals(points, 10)
    assert normals.shape == (4, 3)
    assert np.allclose(np.abs(normals @ UP), 1.0, atol=1e-5)


def test_output_is_one_unit_vector_per_point():
    cfg = settings()
    scans = service.init_worker(cfg)
    normals = service.process(WorkItem(sample_index=1, payload=None), cfg, scans)
    assert isinstance(normals, np.ndarray)
    assert normals.dtype == np.float32
    assert normals.shape == (len(scans[1]), 3)
