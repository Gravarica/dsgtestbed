import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import cv2

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
FACES_IN_PEDESTRIAN_PICTURE = {1: 9, 2: 12}


def configured(model_size):
    return SimpleNamespace(model_size=model_size, service_directory=SERVICE_DIRECTORY, native_threads_per_worker=1)


def test_proof():
    picture = cv2.imread(str(SERVICE_DIRECTORY / "data" / "pedestrian.jpg"))
    for model_size, expected_faces in FACES_IN_PEDESTRIAN_PICTURE.items():
        state = service.init_worker(configured(model_size))
        assert len(service.detected_faces(state.session, picture)) == expected_faces


def test_detected_faces_are_drawn_on_a_copy_of_the_frame():
    picture = cv2.imread(str(SERVICE_DIRECTORY / "data" / "pedestrian.jpg"))
    state = service.init_worker(configured(1))
    drawn = service.with_drawn_boxes(picture, service.detected_faces(state.session, picture))
    assert drawn.shape == picture.shape
    assert (drawn != picture).any()


def test_process_handles_every_sample_frame_of_the_video():
    cfg = configured(1)
    state = service.init_worker(cfg)
    assert len(state.frames) == service.SAMPLE_FRAME_COUNT
    output = service.process(WorkItem(sample_index=0, payload=None), cfg, state)
    assert output.shape == state.frames[0].shape
