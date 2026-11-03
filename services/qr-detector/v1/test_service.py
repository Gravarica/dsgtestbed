import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
EXPECTED_TEXT = "https://qrco.de/beCES7"


def configured(data_quality):
    return SimpleNamespace(data_quality=data_quality, service_directory=SERVICE_DIRECTORY)


def test_proof():
    frames = service.init_worker(configured(552))
    assert len(frames) == service.SAMPLE_FRAME_COUNT
    assert all(service.decoded_texts(frame) == [EXPECTED_TEXT] for frame in frames)


def test_quality_knob_sets_the_height_of_the_processed_frame():
    frames = service.init_worker(configured(300))
    assert frames[0].shape[0] == 300


def test_process_returns_the_frame_with_the_code_highlighted():
    cfg = configured(552)
    frames = service.init_worker(cfg)
    output = service.process(WorkItem(sample_index=0, payload=None), cfg, frames)
    assert output.shape == frames[0].shape
    assert (output != frames[0]).any()


def test_very_low_quality_loses_codes():
    frames = service.init_worker(configured(100))
    decoded = sum(1 for frame in frames if service.decoded_texts(frame) == [EXPECTED_TEXT])
    assert 0 < decoded < len(frames)
