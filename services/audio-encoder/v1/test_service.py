import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_SECONDS = 6
BYTES_PER_SAMPLE = 2
FLAC_MARKER = b"fLaC"
OGG_MARKER = b"OggS"
LEAST_OGG_CORRELATION = 0.9


def configured(data_quality=DEFAULT_SECONDS, format="flac"):
    return SimpleNamespace(data_quality=data_quality, format=format, service_directory=SERVICE_DIRECTORY)


def encoded_by(setup, sample_index, cfg):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, setup)


def test_proof():
    cfg = configured()
    setup = service.init_worker(cfg)
    assert len(setup.clip_ids) == 60
    for sample_index, clip_id in enumerate(setup.clip_ids):
        original = setup.audio[sample_index]
        assert len(original) == DEFAULT_SECONDS * service.SAMPLE_RATE and np.abs(original).max() > 0, clip_id
        encoded_bytes = encoded_by(setup, sample_index, cfg)
        assert encoded_bytes[:4] == FLAC_MARKER, clip_id
        assert len(encoded_bytes) < len(original) * BYTES_PER_SAMPLE, clip_id
        assert np.array_equal(service.decoded(encoded_bytes), original), clip_id


def test_data_quality_knob_sets_the_seconds_of_audio_that_are_encoded():
    short_cfg, long_cfg = configured(data_quality=2), configured(data_quality=12)
    short, long = service.init_worker(short_cfg), service.init_worker(long_cfg)
    short_bytes, long_bytes = encoded_by(short, 0, short_cfg), encoded_by(long, 0, long_cfg)
    assert len(service.decoded(short_bytes)) == 2 * service.SAMPLE_RATE
    assert len(service.decoded(long_bytes)) == 12 * service.SAMPLE_RATE
    assert len(long_bytes) > 3 * len(short_bytes)


def test_format_knob_chooses_lossless_flac_or_smaller_lossy_ogg():
    flac_cfg, ogg_cfg = configured(format="flac"), configured(format="ogg")
    flac_setup, ogg_setup = service.init_worker(flac_cfg), service.init_worker(ogg_cfg)
    for sample_index in range(5):
        original = ogg_setup.audio[sample_index]
        flac_bytes = encoded_by(flac_setup, sample_index, flac_cfg)
        ogg_bytes = encoded_by(ogg_setup, sample_index, ogg_cfg)
        assert ogg_bytes[:4] == OGG_MARKER
        assert len(ogg_bytes) < len(flac_bytes)
        heard = service.decoded(ogg_bytes)
        assert len(heard) == len(original)
        assert not np.array_equal(heard, original)
        assert np.corrcoef(heard.astype(np.float64), original.astype(np.float64))[0, 1] > LEAST_OGG_CORRELATION


def test_process_returns_the_bytes_of_an_audio_file_and_leaves_the_sample_unchanged():
    cfg = configured()
    setup = service.init_worker(cfg)
    before = setup.audio[0].copy()
    encoded_bytes = encoded_by(setup, 0, cfg)
    assert isinstance(encoded_bytes, bytes) and len(encoded_bytes) > 1000
    assert np.array_equal(setup.audio[0], before)
    assert encoded_by(setup, 0, cfg) == encoded_bytes
