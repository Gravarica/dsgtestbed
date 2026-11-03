import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy.ndimage import binary_dilation

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
STREAM_COUNT = 60
DEFAULT_WINDOW_LENGTH = 2048
DEFAULT_MODEL_SIZE = 2
DEFAULT_THRESHOLD = 3.5
TOLERATED_OFFSET = 2
LEAST_SHARE_OF_ANOMALIES_FOUND = 0.95
LEAST_SHARE_OF_FLAGS_NEAR_AN_ANOMALY = 0.35
MOST_SHARE_OF_READINGS_FLAGGED = 0.15


def configured(window_length=DEFAULT_WINDOW_LENGTH, model_size=DEFAULT_MODEL_SIZE, threshold=DEFAULT_THRESHOLD):
    return SimpleNamespace(
        window_length=window_length,
        model_size=model_size,
        threshold=threshold,
        service_directory=SERVICE_DIRECTORY,
    )


def output_for(sample_index, cfg, streams=None):
    streams = streams if streams is not None else service.init_worker(cfg)
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, streams)


def stored_truth():
    with np.load(SERVICE_DIRECTORY / service.STREAMS_FILE) as stored:
        return stored["anomalous"], stored["events"]


def test_proof():
    cfg = configured()
    streams = service.init_worker(cfg)
    anomalous, events = stored_truth()
    assert streams.windows.shape == (STREAM_COUNT, DEFAULT_WINDOW_LENGTH)
    anomalies_in_windows = anomalies_found = flags = flags_near_an_anomaly = 0
    for sample_index in range(STREAM_COUNT):
        positions = np.array(output_for(sample_index, cfg, streams)["anomalies"], dtype=int)
        flagged = np.zeros(DEFAULT_WINDOW_LENGTH, dtype=bool)
        flagged[positions] = True
        own_events = [event for event in events if event[0] == sample_index and event[2] <= DEFAULT_WINDOW_LENGTH]
        assert own_events, sample_index
        for _, start, end, _ in own_events:
            anomalies_in_windows += 1
            anomalies_found += flagged[max(0, start - TOLERATED_OFFSET) : end + TOLERATED_OFFSET].any()
        near_an_anomaly = binary_dilation(anomalous[sample_index, :DEFAULT_WINDOW_LENGTH], iterations=TOLERATED_OFFSET + 1)
        flags += len(positions)
        flags_near_an_anomaly += near_an_anomaly[positions].sum()
    assert anomalies_found / anomalies_in_windows >= LEAST_SHARE_OF_ANOMALIES_FOUND
    assert flags_near_an_anomaly / flags >= LEAST_SHARE_OF_FLAGS_NEAR_AN_ANOMALY
    assert flags / (STREAM_COUNT * DEFAULT_WINDOW_LENGTH) <= MOST_SHARE_OF_READINGS_FLAGGED


def test_window_length_knob_sets_how_many_readings_are_analysed():
    short = output_for(0, configured(window_length=256))
    long = output_for(0, configured(window_length=16384))
    assert short["readings"] == 256
    assert long["readings"] == 16384
    assert max(long["anomalies"]) > 256


def test_model_size_knob_chooses_the_detector():
    outputs = [output_for(0, configured(model_size=model_size)) for model_size in (1, 2, 3)]
    assert [output["detector"] for output in outputs] == [
        "robust_z_score",
        "isolation_forest_small",
        "isolation_forest_large",
    ]
    assert outputs[0]["anomalies"] != outputs[1]["anomalies"]
    assert outputs[1]["anomalies"] != outputs[2]["anomalies"]


def test_threshold_knob_keeps_only_stronger_anomalies_when_raised():
    streams = service.init_worker(configured())
    loose = set(output_for(0, configured(threshold=2.0), streams)["anomalies"])
    strict = set(output_for(0, configured(threshold=6.0), streams)["anomalies"])
    assert strict < loose


def test_process_returns_a_json_ready_record():
    output = output_for(0, configured())
    assert isinstance(output, dict)
    assert output["sample"] == 0
    assert all(isinstance(position, int) for position in output["anomalies"])


def test_same_input_gives_the_same_anomalies():
    streams = service.init_worker(configured())
    assert output_for(3, configured(), streams) == output_for(3, configured(), streams)
