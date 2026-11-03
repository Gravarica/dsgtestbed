import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_DATA_QUALITY = 320
DEFAULT_STRENGTH = 2
LEAST_PSNR_GAIN_DB = 3.0
STRONG_EDGE_GRADIENT = 150.0
LEAST_SHARE_OF_EDGE_CONTRAST_KEPT = 0.8


def configured(data_quality=DEFAULT_DATA_QUALITY, strength=DEFAULT_STRENGTH):
    return SimpleNamespace(data_quality=data_quality, strength=strength, service_directory=SERVICE_DIRECTORY)


def cleaned_sample(cfg, frames, sample_index=0):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, frames)


def psnr_db(reference: np.ndarray, other: np.ndarray) -> float:
    mean_squared_error = np.mean((reference.astype(np.float64) - other.astype(np.float64)) ** 2)
    return float(10 * np.log10(255.0**2 / mean_squared_error))


def gradient_strength(frame: np.ndarray) -> np.ndarray:
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float64)
    return np.hypot(cv2.Sobel(grey, cv2.CV_64F, 1, 0), cv2.Sobel(grey, cv2.CV_64F, 0, 1))


def share_of_edge_contrast_kept(reference: np.ndarray, cleaned: np.ndarray) -> float:
    reference_gradient = gradient_strength(reference)
    strong_edges = reference_gradient > STRONG_EDGE_GRADIENT
    return float(gradient_strength(cleaned)[strong_edges].mean() / reference_gradient[strong_edges].mean())


def residual_noise(reference: np.ndarray, other: np.ndarray) -> float:
    return float(np.std(other.astype(np.float64) - reference.astype(np.float64)))


def test_proof():
    cfg = configured()
    references = service.clean_frames(cfg)
    frames = service.init_worker(cfg)
    assert len(frames) == service.SAMPLE_FRAME_COUNT
    for sample_index, (reference, noisy) in enumerate(zip(references, frames)):
        cleaned = cleaned_sample(cfg, frames, sample_index)
        assert cleaned.shape == reference.shape
        assert psnr_db(reference, cleaned) - psnr_db(reference, noisy) > LEAST_PSNR_GAIN_DB
        assert share_of_edge_contrast_kept(reference, cleaned) > LEAST_SHARE_OF_EDGE_CONTRAST_KEPT


def test_data_quality_knob_sets_the_height_of_the_cleaned_frame():
    for height in (160, 640):
        cfg = configured(data_quality=height)
        frames = service.init_worker(cfg)
        assert cleaned_sample(cfg, frames).shape[0] == height


def test_strength_knob_widens_the_neighbourhood_and_removes_more_noise():
    cfg = configured()
    reference = service.clean_frames(cfg)[0]
    frames = service.init_worker(cfg)
    assert service.neighbourhood_pixels_for(1) < service.neighbourhood_pixels_for(5)
    gentle = cleaned_sample(configured(strength=1), frames)
    strong = cleaned_sample(configured(strength=5), frames)
    assert not np.array_equal(gentle, strong)
    assert residual_noise(reference, strong) < residual_noise(reference, gentle) < residual_noise(reference, frames[0])


def test_the_noise_is_the_same_in_every_worker():
    cfg = configured(data_quality=160)
    assert all(np.array_equal(one, other) for one, other in zip(service.init_worker(cfg), service.init_worker(cfg)))


def test_process_returns_an_image_and_leaves_the_sample_unchanged():
    cfg = configured()
    frames = service.init_worker(cfg)
    before = frames[0].copy()
    output = cleaned_sample(cfg, frames)
    assert isinstance(output, np.ndarray) and output.dtype == np.uint8 and output.ndim == 3
    assert np.array_equal(frames[0], before)
