import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_DATA_QUALITY = 320
DEFAULT_METHOD = "difference"
SHIFT_SHARE_OF_WIDTH = 0.05
LEAST_SHARE_OF_CHANGE_INSIDE_REGIONS = 0.9
CLEAR_BRIGHTNESS_CHANGE = 60


def configured(data_quality=DEFAULT_DATA_QUALITY, method=DEFAULT_METHOD):
    return SimpleNamespace(data_quality=data_quality, method=method, service_directory=SERVICE_DIRECTORY)


def regions_of_sample(cfg, frames, sample_index=0):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, frames)


def shifted_sideways(frame: np.ndarray) -> np.ndarray:
    return np.roll(frame, int(SHIFT_SHARE_OF_WIDTH * frame.shape[1]), axis=1)


def covered_by(regions, shape) -> np.ndarray:
    covered = np.zeros(shape, dtype=bool)
    for region in regions:
        covered[region["top"] : region["top"] + region["height"], region["left"] : region["left"] + region["width"]] = True
    return covered


def clearly_changed(frame: np.ndarray, other: np.ndarray) -> np.ndarray:
    return np.abs(service.as_grey(frame).astype(int) - service.as_grey(other).astype(int)) > CLEAR_BRIGHTNESS_CHANGE


def test_proof():
    cfg = configured()
    frames = service.init_worker(cfg)
    assert len(frames) == service.SAMPLE_PAIR_COUNT + 1
    for frame in frames[1:]:
        assert service.moved_regions(frame, frame, cfg.method) == []
        shifted = shifted_sideways(frame)
        regions = service.moved_regions(shifted, frame, cfg.method)
        changed = clearly_changed(shifted, frame)
        assert regions and changed.any()
        assert (changed & covered_by(regions, changed.shape)).sum() / changed.sum() > LEAST_SHARE_OF_CHANGE_INSIDE_REGIONS


def test_data_quality_knob_sets_the_height_of_the_compared_frames():
    small, large = service.init_worker(configured(data_quality=160)), service.init_worker(configured(data_quality=640))
    assert small[0].shape[0] == 160 and large[0].shape[0] == 640
    region_bottoms = [
        region["top"] + region["height"]
        for region in service.moved_regions(shifted_sideways(large[1]), large[1], DEFAULT_METHOD)
    ]
    assert max(region_bottoms) > 160


def test_method_knob_chooses_how_motion_is_found():
    frames = service.init_worker(configured())
    frame = frames[1]
    shifted = shifted_sideways(frame)
    by_difference = service.moved_regions(shifted, frame, "difference")
    by_flow = service.moved_regions(shifted, frame, "optical_flow")
    assert by_flow and by_difference
    assert by_flow != by_difference
    assert service.moved_regions(frame, frame, "optical_flow") == []


def test_process_compares_a_frame_with_the_frame_before_it():
    cfg = configured()
    frames = service.init_worker(cfg)
    for sample_index in (0, 29, 59):
        expected = service.moved_regions(frames[sample_index + 1], frames[sample_index], cfg.method)
        assert regions_of_sample(cfg, frames, sample_index) == expected


def test_process_returns_a_list_of_boxes_and_leaves_the_samples_unchanged():
    cfg = configured(method="optical_flow")
    frames = service.init_worker(cfg)
    before = [frame.copy() for frame in frames[:2]]
    output = regions_of_sample(cfg, frames)
    assert isinstance(output, list)
    assert all(set(region) == {"left", "top", "width", "height"} for region in output)
    assert all(np.array_equal(frame, kept) for frame, kept in zip(frames[:2], before))
