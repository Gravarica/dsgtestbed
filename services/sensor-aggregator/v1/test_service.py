import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
WINDOW_COUNT = 40
DEFAULT_WINDOW_LENGTH = 1024
DEFAULT_CHANNELS = 16
DEFAULT_FEATURE_SET = "basic"
RELATIVE_TOLERANCE = 1e-6


def configured(window_length=DEFAULT_WINDOW_LENGTH, channels=DEFAULT_CHANNELS, feature_set=DEFAULT_FEATURE_SET):
    return SimpleNamespace(
        window_length=window_length,
        channels=channels,
        feature_set=feature_set,
        service_directory=SERVICE_DIRECTORY,
    )


def generation_parameters():
    return json.loads((SERVICE_DIRECTORY / "fetched" / "readings" / "windows.json").read_text())["parameters"]


def record_for(cfg, sample_index=0, windows=None):
    windows = windows or service.init_worker(cfg)
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, windows)


def test_proof():
    cfg = configured()
    windows = service.init_worker(cfg)
    parameters = generation_parameters()
    assert windows.readings.shape == (WINDOW_COUNT, DEFAULT_CHANNELS, DEFAULT_WINDOW_LENGTH)
    for sample_index in range(WINDOW_COUNT):
        record = record_for(cfg, sample_index, windows)
        raw = windows.readings[sample_index]
        assert record["readings_per_channel"] == DEFAULT_WINDOW_LENGTH
        assert len(record["channels"]) == DEFAULT_CHANNELS
        for channel, summary in enumerate(record["channels"]):
            readings = raw[channel]
            assert math.isclose(summary["mean"], readings.mean(), rel_tol=RELATIVE_TOLERANCE, abs_tol=1e-9)
            assert math.isclose(summary["std"], readings.std(), rel_tol=RELATIVE_TOLERANCE)
            assert summary["min"] == readings.min() and summary["max"] == readings.max()
            assert math.isclose(summary["p50"], float(np.median(readings)), rel_tol=RELATIVE_TOLERANCE, abs_tol=1e-9)
            assert summary["min"] <= summary["p05"] <= summary["p50"] <= summary["p95"] <= summary["max"]
            median = np.median(readings)
            assert math.isclose(
                summary["median_absolute_deviation"], float(np.median(np.abs(readings - median))), rel_tol=RELATIVE_TOLERANCE
            )
            segment_means = [segment[0] for segment in summary["per_segment"]]
            assert len(segment_means) == DEFAULT_WINDOW_LENGTH // service.READINGS_PER_SEGMENT
            assert math.isclose(segment_means[0], readings[: service.READINGS_PER_SEGMENT].mean(), rel_tol=RELATIVE_TOLERANCE, abs_tol=1e-9)
            fitted_slope = np.polyfit(np.arange(DEFAULT_WINDOW_LENGTH), readings, 1)[0]
            assert math.isclose(summary["slope_per_reading"], fitted_slope, rel_tol=1e-4, abs_tol=1e-9)
            known = parameters[sample_index][channel]
            expected_level = known["level"] + known["slope"] * (DEFAULT_WINDOW_LENGTH - 1) / 2
            allowed_offset = known["amplitude"] + 5 * known["noise"] / math.sqrt(DEFAULT_WINDOW_LENGTH) + 1e-3
            assert abs(summary["mean"] - expected_level) <= allowed_offset
            if known["kind"] == "vibration":
                expected_std = math.sqrt(known["amplitude"] ** 2 / 2 + known["noise"] ** 2)
                assert math.isclose(summary["std"], expected_std, rel_tol=0.1)


def test_window_length_knob_sets_how_many_readings_are_summarised():
    short = record_for(configured(window_length=64))
    long = record_for(configured(window_length=8192))
    assert short["readings_per_channel"] == 64
    assert long["readings_per_channel"] == 8192
    assert short["channels"][0]["mean"] != long["channels"][0]["mean"]


def test_channels_knob_sets_how_many_channels_are_summarised():
    assert len(record_for(configured(channels=1))["channels"]) == 1
    assert len(record_for(configured(channels=64))["channels"]) == 64


def test_feature_set_knob_adds_band_energies_and_correlations():
    basic = record_for(configured(feature_set="basic"))
    spectral = record_for(configured(feature_set="spectral"))
    full = record_for(configured(feature_set="full"))
    assert "band_energies" not in basic["channels"][0] and "correlations" not in basic
    assert len(spectral["channels"][0]["band_energies"]) == len(service.BAND_EDGES_HZ) - 1
    assert "correlations" not in spectral
    assert len(full["correlations"]) == DEFAULT_CHANNELS
    assert len(full["channels"][0]["autocorrelation"]) == service.AUTOCORRELATION_LAGS


def test_spectral_features_find_the_frequency_of_fast_channels():
    cfg = configured(window_length=8192, channels=64, feature_set="spectral")
    windows = service.init_worker(cfg)
    parameters = generation_parameters()
    frequency_step_hz = windows.readings_per_second / 8192
    for sample_index in range(3):
        record = record_for(cfg, sample_index, windows)
        for channel, summary in enumerate(record["channels"]):
            known = parameters[sample_index][channel]
            if known["kind"] == "vibration":
                assert abs(summary["dominant_frequency_hz"] - known["frequency_hz"]) <= 2 * frequency_step_hz


def test_process_returns_a_json_record():
    record = record_for(configured(feature_set="full"))
    assert isinstance(record, dict)
    assert json.loads(json.dumps(record))["channel_count"] == DEFAULT_CHANNELS
