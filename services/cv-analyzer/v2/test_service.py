import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import service
from coco_classes import CLASS_NAMES
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_QUALITY = 320
DEFAULT_MODEL = 2


def configured(data_quality=DEFAULT_QUALITY, model_size=DEFAULT_MODEL):
    return SimpleNamespace(
        data_quality=data_quality,
        model_size=model_size,
        service_directory=SERVICE_DIRECTORY,
        native_threads_per_worker=1,
    )


def detections_per_frame(cfg, frame_count=None):
    state = service.init_worker(cfg)
    frame_count = frame_count or len(state.frames)
    return [service.process(WorkItem(sample_index=index, payload=None), cfg, state) for index in range(frame_count)], state


def people_in(detections):
    return sum(1 for detection in detections if detection["class"] == "person")


def test_proof():
    per_frame, state = detections_per_frame(configured())
    assert len(per_frame) == service.SAMPLE_FRAME_COUNT
    height, width = state.frames[0].shape[:2]
    for detections in per_frame:
        assert people_in(detections) >= 5
        for detection in detections:
            left, top, right, bottom = detection["box"]
            assert -8 <= left < right <= width + 8
            assert -8 <= top < bottom <= height + 8
            assert service.CONFIDENCE_THRESHOLD < detection["score"] <= 1.0


def test_quality_knob_sets_the_frame_height_to_the_nearest_multiple_of_32():
    for asked, used in ((160, 160), (300, 288), (310, 320), (640, 640)):
        frame = service.init_worker(configured(data_quality=asked, model_size=1)).frames[0]
        assert frame.shape[0] == used
        assert frame.shape[1] % 32 == 0


def test_a_higher_quality_finds_more_people():
    people_at = {}
    for quality in (160, 320, 640):
        per_frame, _ = detections_per_frame(configured(data_quality=quality, model_size=1), frame_count=10)
        people_at[quality] = sum(people_in(detections) for detections in per_frame)
    assert people_at[160] < people_at[320] < people_at[640]


def test_model_size_knob_loads_another_model_that_sees_the_frames_differently():
    small, small_state = detections_per_frame(configured(model_size=1), frame_count=5)
    large, large_state = detections_per_frame(configured(model_size=3), frame_count=5)
    assert small_state.detector.model_path.endswith("yolov10n.onnx")
    assert large_state.detector.model_path.endswith("yolov10m.onnx")
    assert small != large


def test_process_returns_one_record_per_object_with_class_box_and_score():
    per_frame, _ = detections_per_frame(configured(), frame_count=1)
    detections = per_frame[0]
    assert isinstance(detections, list) and detections
    for detection in detections:
        assert set(detection) == {"class", "box", "score"}
        assert detection["class"] in CLASS_NAMES
        assert len(detection["box"]) == 4 and all(isinstance(edge, int) for edge in detection["box"])
        assert isinstance(detection["score"], float)
