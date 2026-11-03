import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy import signal

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_SECONDS = 6
DEFAULT_TARGET_RATE = "22050"
LARGEST_OFFSET = 1e-4
LOUDNESS_TOLERANCE_DB = 0.1
PEAK_TOLERANCE = 1e-3
LEAST_CORRELATION_WITH_THE_CLIP = 0.99
LARGEST_SHARE_OF_POWER_ABOVE_THE_SOURCE_BAND = 1e-3
FILTER_TRANSITION_SHARE = 0.1
EDGE_SECONDS_LEFT_OUT = 0.05
TONE_HZ = 1000


def configured(data_quality=DEFAULT_SECONDS, target_rate=DEFAULT_TARGET_RATE):
    return SimpleNamespace(data_quality=data_quality, target_rate=target_rate, service_directory=SERVICE_DIRECTORY)


def prepared(setup, sample_index, cfg):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, setup)


def loudness_db_of_loud_blocks(audio, rate):
    block, step = int(0.4 * rate), int(0.1 * rate)
    powers = np.array([np.mean(audio[start : start + block].astype(np.float64) ** 2) for start in range(0, len(audio) - block + 1, step)])
    powers = powers[powers > 10.0 ** (-70.0 / 10.0)]
    powers = powers[powers > powers.mean() * 10.0 ** (-10.0 / 10.0)]
    return 10.0 * np.log10(powers.mean())


def share_of_power_above(audio, rate, frequency_hz):
    spectrum = np.abs(np.fft.rfft(audio.astype(np.float64) * np.hanning(len(audio)))) ** 2
    frequencies = np.fft.rfftfreq(len(audio), 1.0 / rate)
    return spectrum[frequencies > frequency_hz].sum() / spectrum.sum()


def test_proof():
    cfg = configured()
    setup = service.init_worker(cfg)
    target_rate = int(DEFAULT_TARGET_RATE)
    assert len(setup.clip_ids) == 60
    edge_at_source = int(EDGE_SECONDS_LEFT_OUT * service.SOURCE_RATE)
    for sample_index, clip_id in enumerate(setup.clip_ids):
        clip = setup.audio[sample_index].astype(np.float64)
        output = prepared(setup, sample_index, cfg)
        assert output.shape == (DEFAULT_SECONDS * target_rate,), clip_id
        assert np.isfinite(output).all(), clip_id
        assert abs(float(output.mean())) < LARGEST_OFFSET, clip_id
        peak = float(np.abs(output).max())
        at_target = abs(loudness_db_of_loud_blocks(output, target_rate) - service.TARGET_LOUDNESS_DB) < LOUDNESS_TOLERANCE_DB
        held_at_the_peak = abs(peak - service.HIGHEST_PEAK) < PEAK_TOLERANCE
        assert peak <= service.HIGHEST_PEAK + PEAK_TOLERANCE and (at_target or held_at_the_peak), clip_id
        end_of_transition_hz = (1 + FILTER_TRANSITION_SHARE) * service.SOURCE_RATE / 2
        assert share_of_power_above(output, target_rate, end_of_transition_hz) < LARGEST_SHARE_OF_POWER_ABOVE_THE_SOURCE_BAND, clip_id
        back_at_source_rate = signal.resample(output.astype(np.float64), len(clip))
        inner = slice(edge_at_source, len(clip) - edge_at_source)
        correlation = np.corrcoef(back_at_source_rate[inner], (clip - clip.mean())[inner])[0, 1]
        assert correlation > LEAST_CORRELATION_WITH_THE_CLIP, clip_id


def test_data_quality_knob_sets_the_seconds_of_audio_that_are_prepared():
    for seconds in (2, 12):
        cfg = configured(data_quality=seconds)
        setup = service.init_worker(cfg)
        assert len(setup.audio[0]) == seconds * service.SOURCE_RATE
        assert prepared(setup, 0, cfg).shape == (seconds * int(DEFAULT_TARGET_RATE),)


def test_target_rate_knob_sets_the_number_of_samples_per_second():
    for target_rate in ("8000", "22050", "44100"):
        cfg = configured(target_rate=target_rate)
        setup = service.init_worker(cfg)
        assert setup.target_rate == int(target_rate)
        assert prepared(setup, 0, cfg).shape == (DEFAULT_SECONDS * int(target_rate),)


def test_the_lowest_rate_removes_what_it_cannot_carry():
    cfg = configured(target_rate="8000")
    setup = service.init_worker(cfg)
    seconds = np.arange(DEFAULT_SECONDS * service.SOURCE_RATE) / service.SOURCE_RATE
    setup.audio[0] = (0.3 * np.sin(2 * np.pi * TONE_HZ * seconds) + 0.3 * np.sin(2 * np.pi * 6000 * seconds)).astype(np.float32)
    output = prepared(setup, 0, cfg)
    spectrum = np.abs(np.fft.rfft(output.astype(np.float64)))
    frequencies = np.fft.rfftfreq(len(output), 1.0 / 8000)
    assert abs(frequencies[int(np.argmax(spectrum))] - TONE_HZ) < 1.0
    aliased_at_hz = 8000 - 6000
    assert spectrum[np.abs(frequencies - aliased_at_hz) < 5.0].max() < 0.01 * spectrum.max()


def test_process_returns_audio_samples_that_keep_a_pure_tone_at_its_frequency():
    cfg = configured()
    setup = service.init_worker(cfg)
    output = prepared(setup, 0, cfg)
    assert isinstance(output, np.ndarray) and output.dtype == np.float32 and output.ndim == 1
    seconds = np.arange(DEFAULT_SECONDS * service.SOURCE_RATE) / service.SOURCE_RATE
    setup.audio[0] = (0.5 + 0.2 * np.sin(2 * np.pi * TONE_HZ * seconds)).astype(np.float32)
    tone = prepared(setup, 0, cfg)
    spectrum = np.abs(np.fft.rfft(tone.astype(np.float64)))
    frequencies = np.fft.rfftfreq(len(tone), 1.0 / int(DEFAULT_TARGET_RATE))
    assert abs(frequencies[int(np.argmax(spectrum))] - TONE_HZ) < 1.0
    assert abs(float(tone.mean())) < LARGEST_OFFSET
