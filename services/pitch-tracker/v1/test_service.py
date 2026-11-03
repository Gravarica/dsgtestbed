import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_SECONDS = 6
DEFAULT_HOP_MS = 10
TONES_HZ = (90.0, 140.0, 220.0, 330.0)
LARGEST_ERROR_ON_A_TONE = 0.02
LARGEST_ERROR_ON_A_GLIDE = 0.04
GLIDE_FROM_HZ, GLIDE_TO_HZ = 100.0, 300.0
NOISE_LEVEL = 0.02
LEAST_VOICED_SHARE_OF_SPEECH = 0.15
MOST_VOICED_SHARE_OF_SPEECH = 0.95
LOWEST_MEDIAN_OF_A_VOICE_HZ = 75.0
HIGHEST_MEDIAN_OF_A_VOICE_HZ = 300.0


def configured(data_quality=DEFAULT_SECONDS, hop_length=DEFAULT_HOP_MS):
    return SimpleNamespace(data_quality=data_quality, hop_length=hop_length, service_directory=SERVICE_DIRECTORY)


def pitch_of(setup, sample_index, cfg):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, setup)


def expected_frame_count(seconds, hop_ms):
    frame_samples = service.FRAME_MS * service.SAMPLE_RATE // 1000
    return 1 + (seconds * service.SAMPLE_RATE - frame_samples) // (hop_ms * service.SAMPLE_RATE // 1000)


def voice_like(frequency_per_sample, randomness):
    phase = 2 * np.pi * np.cumsum(frequency_per_sample) / service.SAMPLE_RATE
    harmonics = np.sin(phase) + 0.5 * np.sin(2 * phase) + 0.25 * np.sin(3 * phase)
    return (0.3 * harmonics + NOISE_LEVEL * randomness.standard_normal(len(phase))).astype(np.float32)


def frame_centres(setup, frame_count):
    return np.arange(frame_count) * setup.hop_samples + setup.frame_samples // 2


def test_proof():
    cfg = configured()
    setup = service.init_worker(cfg)
    assert len(setup.clip_ids) == 60
    randomness = np.random.default_rng(7)
    sample_count = DEFAULT_SECONDS * service.SAMPLE_RATE
    for tone_hz in TONES_HZ:
        pitch = service.pitch_per_frame(voice_like(np.full(sample_count, tone_hz), randomness), setup)
        assert (pitch > 0).all(), tone_hz
        assert np.abs(pitch / tone_hz - 1).max() < LARGEST_ERROR_ON_A_TONE, tone_hz
    glide = np.linspace(GLIDE_FROM_HZ, GLIDE_TO_HZ, sample_count)
    pitch = service.pitch_per_frame(voice_like(glide, randomness), setup)
    true_pitch = glide[frame_centres(setup, len(pitch))]
    assert (pitch > 0).all()
    assert np.abs(pitch / true_pitch - 1).max() < LARGEST_ERROR_ON_A_GLIDE
    for sample_index, clip_id in enumerate(setup.clip_ids):
        pitch = pitch_of(setup, sample_index, cfg)
        assert pitch.shape == (expected_frame_count(DEFAULT_SECONDS, DEFAULT_HOP_MS),), clip_id
        voiced = pitch[pitch > 0]
        assert LEAST_VOICED_SHARE_OF_SPEECH < len(voiced) / len(pitch) < MOST_VOICED_SHARE_OF_SPEECH, clip_id
        assert voiced.min() >= service.LOWEST_PITCH_HZ * 0.98 and voiced.max() <= service.HIGHEST_PITCH_HZ * 1.02, clip_id
        assert LOWEST_MEDIAN_OF_A_VOICE_HZ < np.median(voiced) < HIGHEST_MEDIAN_OF_A_VOICE_HZ, clip_id


def test_data_quality_knob_sets_the_seconds_of_audio_and_the_number_of_frames():
    for seconds in (2, 12):
        cfg = configured(data_quality=seconds)
        setup = service.init_worker(cfg)
        assert len(setup.audio[0]) == seconds * service.SAMPLE_RATE
        assert pitch_of(setup, 0, cfg).shape == (expected_frame_count(seconds, DEFAULT_HOP_MS),)


def test_hop_length_knob_sets_the_step_between_estimates():
    for hop_ms in (5, 40):
        cfg = configured(hop_length=hop_ms)
        setup = service.init_worker(cfg)
        assert setup.hop_samples == hop_ms * service.SAMPLE_RATE // 1000
        assert pitch_of(setup, 0, cfg).shape == (expected_frame_count(DEFAULT_SECONDS, hop_ms),)


def test_process_returns_one_frequency_per_frame_and_silence_has_no_pitch():
    cfg = configured()
    setup = service.init_worker(cfg)
    pitch = pitch_of(setup, 0, cfg)
    assert isinstance(pitch, np.ndarray) and pitch.dtype == np.float32 and pitch.ndim == 1
    before = setup.audio[0].copy()
    pitch_of(setup, 0, cfg)
    assert np.array_equal(setup.audio[0], before)
    noise = (NOISE_LEVEL * np.random.default_rng(3).standard_normal(DEFAULT_SECONDS * service.SAMPLE_RATE)).astype(np.float32)
    assert (service.pitch_per_frame(noise, setup) > 0).mean() < 0.05
