import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_CHECKSUM = "crc32"


def configured(checksum=DEFAULT_CHECKSUM):
    return SimpleNamespace(checksum=checksum, service_directory=SERVICE_DIRECTORY)


def stamped(frames, sample_index, cfg):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, frames)


def test_proof():
    cfg = configured()
    frames = service.init_worker(cfg)
    assert len(frames) == service.SAMPLE_FRAME_COUNT
    checksums = set()
    for sample_index, frame in enumerate(frames):
        stamp = stamped(frames, sample_index, cfg)
        assert stamp["frame"] == sample_index
        assert (stamp["height"], stamp["width"]) == frame.shape[:2] and stamp["height"] == service.FRAME_HEIGHT
        assert stamp["checksum"] == zlib.crc32(frame.tobytes())
        checksums.add(stamp["checksum"])
    assert len(checksums) == service.SAMPLE_FRAME_COUNT
    changed = frames[0].copy()
    changed[0, 0, 0] ^= 1
    assert zlib.crc32(changed.tobytes()) != stamped(frames, 0, cfg)["checksum"]


def test_checksum_knob_sets_the_checksum_function():
    frames = service.init_worker(configured())
    crc = stamped(frames, 0, configured("crc32"))["checksum"]
    adler = stamped(frames, 0, configured("adler32"))["checksum"]
    assert crc == zlib.crc32(frames[0].tobytes())
    assert adler == zlib.adler32(frames[0].tobytes())
    assert crc != adler


def test_frames_are_the_same_in_every_worker():
    first, second = service.init_worker(configured()), service.init_worker(configured())
    assert all((a == b).all() for a, b in zip(first, second))


def test_process_returns_json_ready_numbers():
    stamp = stamped(service.init_worker(configured()), 0, configured())
    assert set(stamp) == {"frame", "height", "width", "checksum"}
    assert all(isinstance(value, int) for value in stamp.values())
