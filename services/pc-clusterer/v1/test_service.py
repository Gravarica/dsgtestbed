import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
from scipy.spatial import cKDTree

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent


def settings(data_quality=30, voxel_size=0.2, cluster_distance=0.7):
    return SimpleNamespace(
        data_quality=data_quality,
        voxel_size=voxel_size,
        cluster_distance=cluster_distance,
        service_directory=SERVICE_DIRECTORY,
        native_threads_per_worker=1,
    )


def first_real_scan():
    return service.read_lidar_scans(SERVICE_DIRECTORY / service.SCAN_DIRECTORY, 1)[0]


def test_proof():
    cfg = settings()
    scans = service.init_worker(cfg)
    assert len(scans) == service.SAMPLE_SCAN_COUNT
    points = scans[0]
    labels = service.object_labels(points, cfg.cluster_distance)
    close_pairs = cKDTree(points).query_pairs(cfg.cluster_distance, output_type="ndarray")
    assert np.all(labels[close_pairs[:, 0]] == labels[close_pairs[:, 1]])
    boxes = service.process(WorkItem(sample_index=0, payload=None), cfg, scans)
    assert 5 <= len(boxes) <= 2000
    for label in np.unique(labels)[:50]:
        members = points[labels == label]
        if len(members) < service.MIN_POINTS_PER_OBJECT:
            continue
        others = points[labels != label]
        if len(others):
            nearest_other, _ = cKDTree(others).query(members, k=1)
            assert nearest_other.min() > cfg.cluster_distance
    assert sum(box["points"] for box in boxes) <= len(points)
    for box in boxes:
        assert all(low <= high for low, high in zip(box["low"], box["high"]))


def test_distance_knob_keeps_more_points_when_higher():
    scan = first_real_scan()
    near = service.downsampled_obstacle_points(scan, 6, 0.2)
    far = service.downsampled_obstacle_points(scan, 60, 0.2)
    assert len(far) > len(near)


def test_voxel_size_knob_keeps_fewer_points_when_higher():
    scan = first_real_scan()
    fine = service.downsampled_obstacle_points(scan, 30, 0.05)
    coarse = service.downsampled_obstacle_points(scan, 30, 1.0)
    assert len(coarse) < len(fine)


def test_cluster_distance_knob_merges_objects_when_higher():
    points = service.downsampled_obstacle_points(first_real_scan(), 30, 0.2)
    tight = len(np.unique(service.object_labels(points, 0.3)))
    loose = len(np.unique(service.object_labels(points, 2.0)))
    assert loose < tight


def test_two_separate_groups_become_two_boxes():
    group_a = np.array([[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.2, 0.0, 0.0]], dtype=np.float32)
    group_b = group_a + np.float32(10.0)
    points = np.vstack([group_a, group_b])
    boxes = service.object_boxes(points, service.object_labels(points, 0.5))
    assert len(boxes) == 2
    assert sorted(box["points"] for box in boxes) == [3, 3]


def test_output_is_a_list_of_boxes():
    cfg = settings()
    scans = service.init_worker(cfg)
    boxes = service.process(WorkItem(sample_index=1, payload=None), cfg, scans)
    assert isinstance(boxes, list)
    assert set(boxes[0]) == {"low", "high", "points"}
    assert len(boxes[0]["low"]) == 3
