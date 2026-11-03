import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_SECONDS = 6
DEFAULT_FRAME_LENGTH = 20
INSERTED_SILENCES = ((1.5, 2.5), (4.0, 5.0))
INSERTED_SILENCE_LEVEL = 0.001
SECONDS_AROUND_A_SILENCE_NOT_JUDGED = 0.25
BLOCK_SECONDS = 0.05
DECIBELS_BELOW_LOUD_SURELY_SPEECH = 20.0
LEAST_SHARE_OF_SURE_SPEECH_FOUND = 0.95


def configured(data_quality=DEFAULT_SECONDS, frame_length=DEFAULT_FRAME_LENGTH):
    return SimpleNamespace(data_quality=data_quality, frame_length=frame_length, service_directory=SERVICE_DIRECTORY)


def segments_of(setup, sample_index, cfg):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, setup)


def with_inserted_silences(audio, seed):
    silenced = audio.copy()
    randomness = np.random.default_rng(seed)
    for start_second, end_second in INSERTED_SILENCES:
        start, end = int(start_second * service.SAMPLE_RATE), int(end_second * service.SAMPLE_RATE)
        silenced[start:end] = randomness.normal(0.0, INSERTED_SILENCE_LEVEL, end - start)
    return silenced


def in_an_inserted_silence(second):
    return any(start <= second < end for start, end in INSERTED_SILENCES)


def middles_of_sure_speech(audio):
    block = int(BLOCK_SECONDS * service.SAMPLE_RATE)
    without_hum = np.diff(audio.astype(np.float64), prepend=0.0)
    blocks = without_hum[: len(audio) // block * block].reshape(-1, block)
    decibels = 10.0 * np.log10(np.maximum((blocks**2).mean(axis=1), 1e-12))
    middles = (np.arange(len(blocks)) + 0.5) * BLOCK_SECONDS
    loud = decibels > np.percentile(decibels, 95) - DECIBELS_BELOW_LOUD_SURELY_SPEECH
    return [middle for middle, is_loud in zip(middles, loud) if is_loud and not in_an_inserted_silence(middle)]


def is_inside(second, segments):
    return any(start <= second <= end for start, end in segments)


def seconds_found_inside(first_second, last_second, segments):
    return sum(max(0.0, min(end, last_second) - max(start, first_second)) for start, end in segments)


def test_proof():
    cfg = configured()
    setup = service.init_worker(cfg)
    assert len(setup.clip_ids) == 60
    for sample_index, clip_id in enumerate(setup.clip_ids):
        setup.audio[sample_index] = with_inserted_silences(setup.audio[sample_index], seed=sample_index)
        segments = segments_of(setup, sample_index, cfg)
        sure_speech = middles_of_sure_speech(setup.audio[sample_index])
        found = [middle for middle in sure_speech if is_inside(middle, segments)]
        assert len(sure_speech) > 10, clip_id
        assert len(found) / len(sure_speech) >= LEAST_SHARE_OF_SURE_SPEECH_FOUND, clip_id
        for start, end in INSERTED_SILENCES:
            judged_from, judged_to = start + SECONDS_AROUND_A_SILENCE_NOT_JUDGED, end - SECONDS_AROUND_A_SILENCE_NOT_JUDGED
            assert seconds_found_inside(judged_from, judged_to, segments) == 0.0, clip_id


def test_data_quality_knob_sets_the_seconds_of_audio_that_are_searched():
    short_cfg, long_cfg = configured(data_quality=2), configured(data_quality=12)
    short, long = service.init_worker(short_cfg), service.init_worker(long_cfg)
    assert len(short.audio[0]) == 2 * service.SAMPLE_RATE
    assert len(long.audio[0]) == 12 * service.SAMPLE_RATE
    assert max(end for _, end in segments_of(short, 0, short_cfg)) <= 2.0
    assert max(end for _, end in segments_of(long, 0, long_cfg)) > 6.0


def test_frame_length_knob_sets_the_frame_and_the_step_between_boundaries():
    for frame_length, frame_samples in ((10, 160), (30, 480)):
        cfg = configured(frame_length=frame_length)
        setup = service.init_worker(cfg)
        assert setup.frame_samples == frame_samples and setup.hop_samples == frame_samples // 2
        steps = np.array([start for start, _ in segments_of(setup, 0, cfg)]) * service.SAMPLE_RATE / setup.hop_samples
        assert np.allclose(steps, np.round(steps))


def test_process_returns_ordered_stretches_that_json_can_carry():
    cfg = configured()
    setup = service.init_worker(cfg)
    segments = segments_of(setup, 0, cfg)
    assert json.loads(json.dumps(segments)) == segments
    assert all(0.0 <= start < end <= DEFAULT_SECONDS for start, end in segments)
    assert all(earlier[1] < later[0] for earlier, later in zip(segments, segments[1:]))


def test_a_clip_without_a_voice_has_no_stretches():
    cfg = configured()
    setup = service.init_worker(cfg)
    setup.audio[0] = np.random.default_rng(0).normal(0.0, INSERTED_SILENCE_LEVEL, DEFAULT_SECONDS * service.SAMPLE_RATE).astype(np.float32)
    assert segments_of(setup, 0, cfg) == []
