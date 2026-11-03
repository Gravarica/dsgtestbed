import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_SECONDS = 6
DEFAULT_RESOLUTION = 1024
LEAST_GAIN_DB = 3.0
LEAST_NOISE_REDUCTION_DB = 10.0


def configured(data_quality=DEFAULT_SECONDS, resolution=DEFAULT_RESOLUTION):
    return SimpleNamespace(data_quality=data_quality, resolution=resolution, service_directory=SERVICE_DIRECTORY)


def cleaned_of(setup, sample_index, cfg):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, setup)


def signal_to_noise_db(clean, heard):
    clean, heard = clean.astype(np.float64), heard.astype(np.float64)
    return 10.0 * np.log10(np.sum(clean**2) / np.sum((heard - clean) ** 2))


def test_proof():
    cfg = configured()
    setup = service.init_worker(cfg)
    assert len(setup.clip_ids) == 60
    for sample_index, clip_id in enumerate(setup.clip_ids):
        clean, noisy = setup.clean[sample_index], setup.noisy[sample_index]
        cleaned = cleaned_of(setup, sample_index, cfg)
        assert cleaned.shape == clean.shape and np.isfinite(cleaned).all(), clip_id
        before = signal_to_noise_db(clean, noisy)
        after = signal_to_noise_db(clean, cleaned)
        assert abs(before - service.NOISE_BELOW_CLIP_DB) < 0.2, clip_id
        assert after - before > LEAST_GAIN_DB, (clip_id, before, after)


def test_data_quality_knob_sets_the_seconds_of_audio_that_are_cleaned():
    for seconds in (2, 12):
        cfg = configured(data_quality=seconds)
        setup = service.init_worker(cfg)
        assert len(setup.noisy[0]) == seconds * service.SAMPLE_RATE
        assert len(cleaned_of(setup, 0, cfg)) == seconds * service.SAMPLE_RATE


def test_resolution_knob_sets_the_size_of_the_spectrum_and_changes_the_result():
    results = {}
    for resolution in (512, 2048):
        cfg = configured(resolution=resolution)
        setup = service.init_worker(cfg)
        assert setup.fft_size == resolution and len(setup.window) == resolution
        results[resolution] = cleaned_of(setup, 0, cfg)
    assert not np.allclose(results[512], results[2048])


def test_process_returns_audio_and_leaves_the_samples_untouched():
    cfg = configured()
    setup = service.init_worker(cfg)
    noisy_before = setup.noisy[0].copy()
    cleaned = cleaned_of(setup, 0, cfg)
    assert isinstance(cleaned, np.ndarray) and cleaned.dtype == np.float32 and cleaned.ndim == 1
    assert np.array_equal(setup.noisy[0], noisy_before)
    assert np.array_equal(cleaned, cleaned_of(setup, 0, cfg))


def test_a_clip_of_noise_alone_comes_out_far_quieter():
    cfg = configured()
    setup = service.init_worker(cfg)
    noise_alone = (0.1 * np.random.default_rng(1).standard_normal(DEFAULT_SECONDS * service.SAMPLE_RATE)).astype(np.float32)
    setup.noisy[0] = noise_alone
    cleaned = cleaned_of(setup, 0, cfg).astype(np.float64)
    quieter_by_db = 10.0 * np.log10(np.mean(noise_alone.astype(np.float64) ** 2) / np.mean(cleaned**2))
    assert quieter_by_db > LEAST_NOISE_REDUCTION_DB
