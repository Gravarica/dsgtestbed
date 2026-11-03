import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_DATA_QUALITY = 320
DEFAULT_CORRECTION = "colour"
SOURCE_ASPECT_RATIO = 1920 / 1080
MOST_CHANNEL_IMBALANCE = 2.0
LEAST_CORRELATION_WITH_THE_SOURCE = 0.85


def configured(data_quality=DEFAULT_DATA_QUALITY, correction=DEFAULT_CORRECTION):
    return SimpleNamespace(data_quality=data_quality, correction=correction, service_directory=SERVICE_DIRECTORY)


def transformed_sample(cfg, transformation, sample_index=0):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, transformation)


def grey(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float64)


def correlation(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.corrcoef(first.ravel(), second.ravel())[0, 1])


def channel_imbalance(frame: np.ndarray) -> float:
    channel_means = frame.reshape(-1, 3).mean(axis=0)
    return float(channel_means.max() - channel_means.min())


def test_proof():
    cfg = configured()
    transformation = service.init_worker(cfg)
    assert len(transformation.source_frames) == service.SAMPLE_FRAME_COUNT
    expected_width = round(DEFAULT_DATA_QUALITY * SOURCE_ASPECT_RATIO)
    for sample_index, source in enumerate(transformation.source_frames):
        output = transformed_sample(cfg, transformation, sample_index)
        assert output.shape == (DEFAULT_DATA_QUALITY, expected_width, 3) and output.dtype == np.uint8
        plainly_resized = cv2.resize(source, (expected_width, DEFAULT_DATA_QUALITY), interpolation=cv2.INTER_AREA)
        assert correlation(grey(output), grey(plainly_resized)) > LEAST_CORRELATION_WITH_THE_SOURCE
        assert channel_imbalance(plainly_resized) > MOST_CHANNEL_IMBALANCE
        assert channel_imbalance(output) < MOST_CHANNEL_IMBALANCE


def test_data_quality_knob_sets_the_height_of_the_transformed_frame():
    for height in (160, 640):
        cfg = configured(data_quality=height)
        output = transformed_sample(cfg, service.init_worker(cfg))
        assert output.shape[:2] == (height, round(height * SOURCE_ASPECT_RATIO))


def test_correction_knob_adds_colour_and_then_geometry():
    transformation = service.init_worker(configured())
    resized = transformed_sample(configured(correction="resize"), transformation)
    coloured = transformed_sample(configured(correction="colour"), transformation)
    geometric = transformed_sample(configured(correction="geometric"), transformation)
    assert resized.shape == coloured.shape == geometric.shape
    assert channel_imbalance(resized) > MOST_CHANNEL_IMBALANCE > channel_imbalance(coloured)
    assert not np.array_equal(coloured, geometric)


def test_geometric_correction_moves_the_seen_corners_to_the_frame_corners():
    transformation = service.init_worker(configured(correction="geometric"))
    seen, corrected = service.keystone_corners(transformation.target_size)
    moved = cv2.perspectiveTransform(seen.reshape(1, -1, 2), transformation.keystone_matrix).reshape(-1, 2)
    assert np.allclose(moved, corrected, atol=1e-3)
    centre_x, centre_y = transformation.target_size[0] // 2, transformation.target_size[1] // 2
    assert abs(transformation.undistortion_map_x[centre_y, centre_x] - centre_x) < 1
    assert abs(transformation.undistortion_map_x[centre_y, 0] - 0) > 1


def test_process_returns_an_image_and_leaves_the_sample_unchanged():
    cfg = configured(correction="geometric")
    transformation = service.init_worker(cfg)
    before = transformation.source_frames[0].copy()
    output = transformed_sample(cfg, transformation)
    assert isinstance(output, np.ndarray) and output.ndim == 3 and output.shape[2] == 3
    assert np.array_equal(transformation.source_frames[0], before)
    assert np.array_equal(output, transformed_sample(cfg, transformation))
