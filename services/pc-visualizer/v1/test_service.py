import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent


def test_view_is_a_square_whose_side_follows_the_distance_knob():
    points = np.array([[1.0, 2.0, 0.0, 0.5], [100.0, 0.0, 0.0, 0.5]], dtype=np.float32)
    view = service.birds_eye_view(points, max_distance_meters=30)
    assert view.shape == (600, 600, 3)


def test_only_points_inside_the_distance_are_drawn_at_their_place():
    points = np.array([[1.0, 2.0, 0.0, 0.5], [100.0, 0.0, 0.0, 0.5]], dtype=np.float32)
    view = service.birds_eye_view(points, max_distance_meters=30)
    assert view[320, 310].tolist() == [255, 255, 255]
    assert int((view > 0).any(axis=2).sum()) == 1


def test_proof():
    cfg = SimpleNamespace(data_quality=30, service_directory=SERVICE_DIRECTORY, native_threads_per_worker=1)
    scans = service.init_worker(cfg)
    assert len(scans) == service.SAMPLE_SCAN_COUNT
    assert scans[0].shape[1] == 4
    view = service.process(WorkItem(sample_index=0, payload=None), cfg, scans)
    assert (view > 0).any()
