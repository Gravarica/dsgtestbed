import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import service
from drawing import CLASS_NAMES
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
PERSON = CLASS_NAMES.index("person")


def configured(model_size, data_quality):
    return SimpleNamespace(
        model_size=model_size,
        data_quality=data_quality,
        service_directory=SERVICE_DIRECTORY,
        native_threads_per_worker=1,
    )


def people_per_frame(model_size, data_quality):
    state = service.init_worker(configured(model_size, data_quality))
    counts = []
    for frame in state.frames:
        class_ids, _, _ = state.detector.detect_objects(frame)
        counts.append(int((class_ids == PERSON).sum()))
    return counts


def test_proof():
    counts = people_per_frame(model_size=3, data_quality=224)
    assert len(counts) == service.SAMPLE_FRAME_COUNT
    assert min(counts) >= 1


def test_higher_quality_finds_more_people_and_the_lowest_quality_loses_them():
    assert sum(people_per_frame(1, 320)) > sum(people_per_frame(1, 224)) > sum(people_per_frame(1, 128)) == 0


def test_quality_knob_sets_the_height_of_the_processed_frame():
    state = service.init_worker(configured(1, 224))
    assert state.frames[0].shape[0] == 224


def test_process_returns_the_frame_with_the_detections_drawn():
    cfg = configured(1, 224)
    state = service.init_worker(cfg)
    output = service.process(WorkItem(sample_index=0, payload=None), cfg, state)
    assert output.shape == state.frames[0].shape
    assert (output != state.frames[0]).any()
