import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import cv2

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_FRAME_HEIGHT = 320
DEFAULT_MODEL_SIZE = 1
PICTURE_HEIGHT = 1439
KNOWN_FACES_IN_THE_PICTURE = [
    (317, 547, 47, 58),
    (475, 623, 54, 67),
    (531, 537, 49, 62),
    (667, 570, 55, 68),
    (750, 542, 46, 56),
    (788, 645, 47, 57),
    (934, 546, 43, 57),
    (1027, 626, 51, 64),
    (1159, 591, 43, 55),
    (1299, 665, 47, 61),
    (1358, 629, 43, 55),
    (1618, 608, 53, 61),
]
OVERLAP_THAT_COUNTS_AS_THE_SAME_FACE = 0.4
FEWEST_KNOWN_FACES_FOUND = 10
MOST_BOXES_THAT_ARE_NO_KNOWN_FACE = 3
PICTURE_SAMPLE = WorkItem(sample_index=0, payload=None)


def configured(data_quality=DEFAULT_FRAME_HEIGHT, model_size=DEFAULT_MODEL_SIZE):
    return SimpleNamespace(
        data_quality=data_quality, model_size=model_size, service_directory=SERVICE_DIRECTORY, native_threads_per_worker=1
    )


def overlap(first, second):
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right = min(first[0] + first[2], second[0] + second[2])
    bottom = min(first[1] + first[3], second[1] + second[3])
    shared = max(0.0, right - left) * max(0.0, bottom - top)
    return shared / (first[2] * first[3] + second[2] * second[3] - shared)


def boxes_in_picture_pixels(faces, frame_height):
    return [[value * PICTURE_HEIGHT / frame_height for value in face["box"]] for face in faces]


def known_faces_found(boxes):
    return sum(
        any(overlap(known, box) >= OVERLAP_THAT_COUNTS_AS_THE_SAME_FACE for box in boxes) for known in KNOWN_FACES_IN_THE_PICTURE
    )


def boxes_that_are_no_known_face(boxes):
    return sum(
        all(overlap(known, box) < OVERLAP_THAT_COUNTS_AS_THE_SAME_FACE for known in KNOWN_FACES_IN_THE_PICTURE) for box in boxes
    )


def faces_found_in_the_picture(cfg):
    faces = service.process(PICTURE_SAMPLE, cfg, service.init_worker(cfg))
    return boxes_in_picture_pixels(faces, cfg.data_quality)


def test_proof():
    cfg = configured()
    state = service.init_worker(cfg)
    assert state.frames[0].shape[0] == DEFAULT_FRAME_HEIGHT
    boxes = boxes_in_picture_pixels(service.process(PICTURE_SAMPLE, cfg, state), DEFAULT_FRAME_HEIGHT)
    assert known_faces_found(boxes) >= FEWEST_KNOWN_FACES_FOUND
    assert boxes_that_are_no_known_face(boxes) <= MOST_BOXES_THAT_ARE_NO_KNOWN_FACE


def test_data_quality_knob_sets_the_frame_height_the_detector_runs_at():
    low, high = service.init_worker(configured(data_quality=160)), service.init_worker(configured(data_quality=640))
    assert {frame.shape[0] for frame in low.frames} == {160}
    assert {frame.shape[0] for frame in high.frames} == {640}
    assert high.frames[0].shape[1] > low.frames[0].shape[1]
    assert known_faces_found(faces_found_in_the_picture(configured(data_quality=640))) > known_faces_found(
        faces_found_in_the_picture(configured(data_quality=160))
    )


def test_model_size_knob_finds_small_faces_the_single_pass_misses():
    single_pass = known_faces_found(faces_found_in_the_picture(configured(data_quality=160, model_size=1)))
    two_passes = known_faces_found(faces_found_in_the_picture(configured(data_quality=160, model_size=2)))
    assert two_passes > single_pass


def test_process_returns_boxes_and_scores_as_json_for_every_sample():
    cfg = configured()
    state = service.init_worker(cfg)
    assert len(state.frames) == service.SAMPLE_COUNT
    for sample_index, frame in enumerate(state.frames):
        faces = service.process(WorkItem(sample_index=sample_index, payload=None), cfg, state)
        assert json.loads(json.dumps(faces)) == faces
        for face in faces:
            left, top, width, height = face["box"]
            assert width > 0 and height > 0
            assert left + width > 0 and top + height > 0 and left < frame.shape[1] and top < frame.shape[0]
            assert service.SCORE_THRESHOLD <= face["score"] <= 1.0


def test_samples_are_not_changed_by_processing():
    cfg = configured(model_size=2)
    state = service.init_worker(cfg)
    before = state.frames[0].copy()
    service.process(PICTURE_SAMPLE, cfg, state)
    assert (state.frames[0] == before).all()
