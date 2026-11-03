import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent


def settings(data_quality=30, voxel_size=0.2):
    return SimpleNamespace(
        data_quality=data_quality,
        voxel_size=voxel_size,
        service_directory=SERVICE_DIRECTORY,
        native_threads_per_worker=1,
    )


def first_real_scan():
    return service.read_lidar_scans(SERVICE_DIRECTORY / service.SCAN_DIRECTORY, 1)[0]


def occupied_voxels(points, voxel_size):
    return {tuple(voxel) for voxel in service.voxel_of_each_point(points, voxel_size).tolist()}


def test_proof():
    cfg = settings()
    scans = service.init_worker(cfg)
    assert len(scans) == service.SAMPLE_SCAN_COUNT
    for sample_index, points in enumerate(scans):
        thinned = service.process(WorkItem(sample_index=sample_index, payload=None), cfg, scans)
        voxels_of_the_scan = occupied_voxels(points, cfg.voxel_size)
        voxels_of_the_result = service.voxel_of_each_point(thinned.astype(np.float64), cfg.voxel_size)
        assert len(thinned) == len(voxels_of_the_scan)
        assert len(thinned) < len(points) / 2
        assert len(np.unique(voxels_of_the_result, axis=0)) > 0.98 * len(thinned)
    points = scans[0]
    thinned = service.process(WorkItem(sample_index=0, payload=None), cfg, scans)
    voxels = service.voxel_of_each_point(points, cfg.voxel_size)
    for voxel in voxels[:: len(voxels) // 200]:
        members = points[np.all(voxels == voxel, axis=1)]
        nearest = np.abs(thinned - members.mean(axis=0)).sum(axis=1).min()
        assert nearest < 1e-3


def test_distance_knob_keeps_more_points_when_higher():
    scan = first_real_scan()
    assert len(service.points_within_distance(scan, 60)) > len(service.points_within_distance(scan, 6))
    assert np.hypot(*service.points_within_distance(scan, 6)[:, :2].T).max() < 6


def test_voxel_size_knob_keeps_fewer_points_when_higher():
    points = service.points_within_distance(first_real_scan(), 30)
    fine = service.voxel_centroids(points, 0.05)
    coarse = service.voxel_centroids(points, 1.0)
    assert len(coarse) < len(fine) <= len(points)


def test_points_of_one_voxel_become_their_centroid():
    points = np.array([[0.01, 0.01, 0.01], [0.09, 0.09, 0.09], [5.0, 5.0, 5.0]], dtype=np.float32)
    thinned = service.voxel_centroids(points, 0.2)
    assert len(thinned) == 2
    assert np.allclose(sorted(thinned[:, 0]), [0.05, 5.0], atol=1e-5)


def test_output_is_an_array_of_points():
    cfg = settings()
    scans = service.init_worker(cfg)
    thinned = service.process(WorkItem(sample_index=1, payload=None), cfg, scans)
    assert isinstance(thinned, np.ndarray)
    assert thinned.dtype == np.float32
    assert thinned.shape[1] == 3
