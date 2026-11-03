import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
from scipy.spatial import cKDTree

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent


def settings(data_quality=30, iterations=15):
    return SimpleNamespace(
        data_quality=data_quality,
        iterations=iterations,
        service_directory=SERVICE_DIRECTORY,
        native_threads_per_worker=1,
    )


def first_real_scan():
    return service.read_lidar_scans(SERVICE_DIRECTORY / service.SCAN_DIRECTORY, 1)[0]


def turn_about_the_vertical(degrees):
    angle = np.radians(degrees)
    return np.array([[np.cos(angle), -np.sin(angle), 0.0], [np.sin(angle), np.cos(angle), 0.0], [0.0, 0.0, 1.0]])


def moved_copy(points, rotation, translation):
    return (points - translation) @ rotation


def angle_between_degrees(rotation, other):
    cosine = (np.trace(rotation @ other.T) - 1.0) / 2.0
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))


def test_proof():
    cfg = settings()
    scan_pairs = service.init_worker(cfg)
    assert len(scan_pairs) == service.SAMPLE_PAIR_COUNT
    points = service.thinned_obstacle_points(first_real_scan(), cfg.data_quality)
    known_rotation, known_translation = turn_about_the_vertical(1.0), np.array([0.25, 0.10, 0.02])
    rotation, translation, matched_points, mean_distance = service.motion_between(
        moved_copy(points, known_rotation, known_translation), cKDTree(points), 40
    )
    assert angle_between_degrees(rotation, known_rotation) < 0.05
    assert np.linalg.norm(translation - known_translation) < 0.01
    assert matched_points == len(points)
    assert mean_distance < 0.01
    forward_motions = []
    for sample_index in range(0, service.SAMPLE_PAIR_COUNT, 6):
        found = service.process(WorkItem(sample_index=sample_index, payload=None), cfg, scan_pairs)
        found_rotation, found_translation = np.array(found["rotation"]), np.array(found["translation"])
        assert np.allclose(found_rotation @ found_rotation.T, np.eye(3), atol=1e-9)
        assert np.isclose(np.linalg.det(found_rotation), 1.0)
        assert angle_between_degrees(found_rotation, np.eye(3)) < 3.0
        assert np.linalg.norm(found_translation) < 2.5
        assert abs(found_translation[1]) < 0.5 and abs(found_translation[2]) < 0.3
        forward_motions.append(found_translation[0])
    assert 0.2 < np.median(forward_motions) < 2.0


def test_distance_knob_keeps_more_points_when_higher():
    scan = first_real_scan()
    assert len(service.thinned_obstacle_points(scan, 60)) > len(service.thinned_obstacle_points(scan, 6))


def test_iterations_knob_brings_the_scans_closer_when_higher():
    points = service.thinned_obstacle_points(first_real_scan(), 30)
    known_rotation, known_translation = turn_about_the_vertical(3.0), np.array([0.8, 0.3, 0.0])
    moved = moved_copy(points, known_rotation, known_translation)
    _, few_translation, _, few_distance = service.motion_between(moved, cKDTree(points), 5)
    _, many_translation, _, many_distance = service.motion_between(moved, cKDTree(points), 40)
    assert many_distance < few_distance
    assert np.linalg.norm(many_translation - known_translation) < np.linalg.norm(few_translation - known_translation)


def test_identical_scans_need_no_motion():
    points = service.thinned_obstacle_points(first_real_scan(), 20)
    rotation, translation, _, mean_distance = service.motion_between(points, cKDTree(points), 5)
    assert np.allclose(rotation, np.eye(3), atol=1e-9)
    assert np.allclose(translation, 0.0, atol=1e-9)
    assert mean_distance < 1e-9


def test_the_samples_are_not_changed():
    cfg = settings()
    scan_pairs = service.init_worker(cfg)
    before = scan_pairs[2][0].copy()
    service.process(WorkItem(sample_index=2, payload=None), cfg, scan_pairs)
    assert np.array_equal(scan_pairs[2][0], before)


def test_output_is_a_rotation_and_a_translation():
    cfg = settings()
    found = service.process(WorkItem(sample_index=1, payload=None), cfg, service.init_worker(cfg))
    assert set(found) == {"rotation", "translation", "matched_points", "mean_distance"}
    assert np.array(found["rotation"]).shape == (3, 3)
    assert len(found["translation"]) == 3
    assert isinstance(found["matched_points"], int) and isinstance(found["mean_distance"], float)
