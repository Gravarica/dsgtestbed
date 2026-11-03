import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_DATA_QUALITY = 552
DEFAULT_ENCODING_QUALITY = 75
DEFAULT_FORMAT = "jpeg"
LEAST_SIZE_REDUCTION = 5
LEAST_PSNR_DB = 30.0
JPEG_START = b"\xff\xd8\xff"
PNG_START = b"\x89PNG\r\n\x1a\n"


def configured(data_quality=DEFAULT_DATA_QUALITY, encoding_quality=DEFAULT_ENCODING_QUALITY, image_format=DEFAULT_FORMAT):
    return SimpleNamespace(
        data_quality=data_quality,
        encoding_quality=encoding_quality,
        format=image_format,
        service_directory=SERVICE_DIRECTORY,
    )


def encoded_sample(cfg, images, sample_index=0):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, images)


def psnr_db(original: np.ndarray, restored: np.ndarray) -> float:
    mean_squared_error = np.mean((original.astype(np.float64) - restored.astype(np.float64)) ** 2)
    return float(10 * np.log10(255.0**2 / mean_squared_error))


def test_proof():
    cfg = configured()
    images = service.init_worker(cfg)
    assert len(images) == service.SAMPLE_FRAME_COUNT
    for sample_index, image in enumerate(images):
        original = np.asarray(image)
        encoded = encoded_sample(cfg, images, sample_index)
        assert encoded.startswith(JPEG_START)
        restored = service.decoded(encoded)
        assert restored.shape == original.shape
        assert original.nbytes / len(encoded) > LEAST_SIZE_REDUCTION
        assert psnr_db(original, restored) > LEAST_PSNR_DB


def test_data_quality_knob_sets_the_height_of_the_encoded_frame():
    cfg = configured(data_quality=300)
    images = service.init_worker(cfg)
    assert service.decoded(encoded_sample(cfg, images)).shape[0] == 300


def test_encoding_quality_knob_changes_size_and_fidelity():
    images = service.init_worker(configured())
    low = encoded_sample(configured(encoding_quality=10), images)
    high = encoded_sample(configured(encoding_quality=95), images)
    original = np.asarray(images[0])
    assert len(low) < len(high)
    assert psnr_db(original, service.decoded(low)) < psnr_db(original, service.decoded(high))


def test_format_knob_chooses_the_encoding():
    images = service.init_worker(configured(data_quality=200))
    assert encoded_sample(configured(data_quality=200, image_format="jpeg"), images).startswith(JPEG_START)
    assert encoded_sample(configured(data_quality=200, image_format="png"), images).startswith(PNG_START)
    webp = encoded_sample(configured(data_quality=200, image_format="webp"), images)
    assert webp[:4] == b"RIFF" and webp[8:12] == b"WEBP"


def test_png_is_lossless():
    cfg = configured(data_quality=200, image_format="png")
    images = service.init_worker(cfg)
    assert np.array_equal(service.decoded(encoded_sample(cfg, images)), np.asarray(images[0]))


def test_process_returns_bytes_and_leaves_the_sample_unchanged():
    cfg = configured()
    images = service.init_worker(cfg)
    before = np.asarray(images[0]).copy()
    output = encoded_sample(cfg, images)
    assert isinstance(output, bytes)
    assert np.array_equal(np.asarray(images[0]), before)
