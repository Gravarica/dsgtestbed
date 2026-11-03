import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_DATA_QUALITY = 320
DEFAULT_SMOOTHING = 5
FEWEST_CONTOURS_PER_FRAME = 5
HOW_MUCH_STEEPER_THAN_THE_FRAME = 3.0
BGR_TO_GRAY = np.array([0.114, 0.587, 0.299])


def configured(data_quality=DEFAULT_DATA_QUALITY, smoothing=DEFAULT_SMOOTHING):
    return SimpleNamespace(data_quality=data_quality, smoothing=smoothing, service_directory=SERVICE_DIRECTORY)


def contours_of_sample(cfg, frames, sample_index=0):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, frames)


def brightness_change_per_pixel(frame: np.ndarray) -> np.ndarray:
    gray = frame.astype(np.float64) @ BGR_TO_GRAY
    down, across = np.gradient(gray)
    return np.hypot(down, across)


def steepest_nearby(change: np.ndarray, x: int, y: int) -> float:
    return float(change[max(0, y - 2) : y + 3, max(0, x - 2) : x + 3].max())


def test_proof():
    cfg = configured()
    frames = service.init_worker(cfg)
    assert len(frames) == service.SAMPLE_FRAME_COUNT
    for sample_index, frame in enumerate(frames):
        contours = contours_of_sample(cfg, frames, sample_index)
        assert len(contours) >= FEWEST_CONTOURS_PER_FRAME
        change = brightness_change_per_pixel(frame)
        height, width = change.shape
        at_corners = []
        for contour in contours:
            left, top, box_width, box_height = contour["box"]
            assert 0 <= left and 0 <= top and left + box_width <= width and top + box_height <= height
            assert contour["length"] >= service.SHORTEST_CONTOUR_IN_PIXELS
            for x, y in contour["polygon"]:
                assert left <= x < left + box_width and top <= y < top + box_height
                at_corners.append(steepest_nearby(change, x, y))
        assert np.mean(at_corners) > HOW_MUCH_STEEPER_THAN_THE_FRAME * change.mean()


def test_data_quality_knob_sets_the_height_of_the_frames_and_the_reach_of_the_contours():
    small_cfg, large_cfg = configured(data_quality=160), configured(data_quality=640)
    small_frames, large_frames = service.init_worker(small_cfg), service.init_worker(large_cfg)
    assert small_frames[0].shape[0] == 160 and large_frames[0].shape[0] == 640
    lowest_point = lambda contours: max(top + height for _, top, _, height in (contour["box"] for contour in contours))
    assert lowest_point(contours_of_sample(small_cfg, small_frames)) <= 160
    assert lowest_point(contours_of_sample(large_cfg, large_frames)) > 160


def test_smoothing_knob_sets_the_kernel_and_changes_the_edges():
    assert [service.odd_kernel_size(value) for value in (3, 4, 5, 14, 15)] == [3, 5, 5, 15, 15]
    frames = service.init_worker(configured())
    light = service.edge_map(frames[0], 3)
    heavy = service.edge_map(frames[0], 15)
    assert not np.array_equal(light, heavy)
    assert np.array_equal(service.edge_map(frames[0], 4), service.edge_map(frames[0], 5))


def test_process_returns_a_list_of_contours_and_leaves_the_sample_unchanged():
    cfg = configured()
    frames = service.init_worker(cfg)
    before = frames[0].copy()
    contours = contours_of_sample(cfg, frames)
    assert isinstance(contours, list) and isinstance(contours[0], dict)
    assert set(contours[0]) == {"polygon", "box", "length", "area", "solidity", "points"}
    assert np.array_equal(frames[0], before)


def test_same_frame_gives_the_same_contours():
    cfg = configured()
    frames = service.init_worker(cfg)
    assert contours_of_sample(cfg, frames, 7) == contours_of_sample(cfg, frames, 7)
