import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_SECONDS = 6
DEFAULT_MEL_BANDS = 64
DEFAULT_FRAME_MS = 25
LEAST_ENERGY_CORRELATION = 0.95
SPEECH_BAND_HZ = 4000
LEAST_SHARE_OF_ENERGY_IN_SPEECH_BAND = 0.8
TONE_HZ = 1000


def configured(data_quality=DEFAULT_SECONDS, mel_bands=DEFAULT_MEL_BANDS, frame_ms=DEFAULT_FRAME_MS):
    return SimpleNamespace(
        data_quality=data_quality, mel_bands=mel_bands, frame_ms=frame_ms, service_directory=SERVICE_DIRECTORY
    )


def features_of(setup, sample_index, cfg):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, setup)


def expected_frame_count(seconds, frame_ms):
    return 1 + (seconds * service.SAMPLE_RATE - frame_ms * service.SAMPLE_RATE // 1000) // (
        service.HOP_MS * service.SAMPLE_RATE // 1000
    )


def frame_energies(audio, setup):
    frames = service.framed(audio, setup.window_frames, setup.hop_frames) * setup.window
    return (frames.astype(np.float64) ** 2).sum(axis=1)


def band_centres_hz(mel_bands):
    edges = service.mel_to_hz(
        np.linspace(service.hz_to_mel(service.LOWEST_MEL_HZ), service.hz_to_mel(service.HIGHEST_MEL_HZ), mel_bands + 2)
    )
    return edges[1:-1]


def test_proof():
    cfg = configured()
    setup = service.init_worker(cfg)
    assert len(setup.clip_ids) == 60
    in_speech_band = band_centres_hz(DEFAULT_MEL_BANDS) < SPEECH_BAND_HZ
    for sample_index, clip_id in enumerate(setup.clip_ids):
        features = features_of(setup, sample_index, cfg)
        assert features.shape == (expected_frame_count(DEFAULT_SECONDS, DEFAULT_FRAME_MS), DEFAULT_MEL_BANDS + service.MFCC_COUNT)
        assert np.isfinite(features).all(), clip_id
        mel_energy = np.exp(features[:, :DEFAULT_MEL_BANDS].astype(np.float64))
        spoken = np.log(mel_energy.sum(axis=1))
        independent = np.log(np.maximum(frame_energies(setup.audio[sample_index], setup), service.SMALLEST_ENERGY))
        assert np.corrcoef(spoken, independent)[0, 1] > LEAST_ENERGY_CORRELATION, clip_id
        assert mel_energy[:, in_speech_band].sum() / mel_energy.sum() > LEAST_SHARE_OF_ENERGY_IN_SPEECH_BAND, clip_id


def test_data_quality_knob_sets_the_seconds_of_audio_and_the_number_of_frames():
    short = service.init_worker(configured(data_quality=1))
    long = service.init_worker(configured(data_quality=12))
    assert len(short.audio[0]) == service.SAMPLE_RATE
    assert len(long.audio[0]) == 12 * service.SAMPLE_RATE
    assert features_of(short, 0, configured(data_quality=1)).shape[0] == expected_frame_count(1, DEFAULT_FRAME_MS)
    assert features_of(long, 0, configured(data_quality=12)).shape[0] == expected_frame_count(12, DEFAULT_FRAME_MS)


def test_mel_bands_knob_sets_the_number_of_mel_columns():
    for mel_bands in (20, 256):
        cfg = configured(mel_bands=mel_bands)
        assert features_of(service.init_worker(cfg), 0, cfg).shape[1] == mel_bands + service.MFCC_COUNT


def test_frame_ms_knob_sets_the_window_and_the_fft_size():
    narrow_cfg = configured(frame_ms=10)
    wide_cfg = configured(frame_ms=100)
    narrow = service.init_worker(narrow_cfg)
    wide = service.init_worker(wide_cfg)
    assert narrow.window_frames == 160 and narrow.fft_size == 256
    assert wide.window_frames == 1600 and wide.fft_size == 2048
    assert features_of(narrow, 0, narrow_cfg).shape[0] == expected_frame_count(DEFAULT_SECONDS, 10)
    assert features_of(wide, 0, wide_cfg).shape[0] == expected_frame_count(DEFAULT_SECONDS, 100)


def test_process_returns_a_feature_matrix_whose_strongest_band_holds_a_pure_tone():
    cfg = configured()
    setup = service.init_worker(cfg)
    features = features_of(setup, 0, cfg)
    assert isinstance(features, np.ndarray) and features.dtype == np.float32 and features.ndim == 2
    seconds = np.arange(DEFAULT_SECONDS * service.SAMPLE_RATE) / service.SAMPLE_RATE
    setup.audio[0] = np.sin(2 * np.pi * TONE_HZ * seconds).astype(np.float32)
    tone = features_of(setup, 0, cfg)
    strongest_band = int(np.argmax(tone[:, :DEFAULT_MEL_BANDS].mean(axis=0)))
    centres = band_centres_hz(DEFAULT_MEL_BANDS)
    assert abs(centres[strongest_band] - TONE_HZ) < (centres[strongest_band + 1] - centres[strongest_band - 1])
