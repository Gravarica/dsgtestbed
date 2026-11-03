import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_MODEL_SIZE = 1
DEFAULT_SECONDS = 6
LEAST_WORDS_PER_CLIP = 5
HIGHEST_WORD_ERROR_RATE = 0.25


def configured(model_size=DEFAULT_MODEL_SIZE, data_quality=DEFAULT_SECONDS):
    return SimpleNamespace(model_size=model_size, data_quality=data_quality, service_directory=SERVICE_DIRECTORY)


def spoken_words(samples, sample_index, cfg):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, samples).split()


def test_proof():
    cfg = configured()
    samples = service.init_worker(cfg)
    assert len(samples.clip_ids) == 60
    error_rates = []
    for sample_index, clip_id in enumerate(samples.clip_ids):
        words = spoken_words(samples, sample_index, cfg)
        assert len(words) >= LEAST_WORDS_PER_CLIP, f"{clip_id} yielded {words}"
        reference = samples.references[clip_id].split()[: len(words)]
        error_rates.append(service.word_error_rate(reference, words))
    assert sum(error_rates) / len(error_rates) < HIGHEST_WORD_ERROR_RATE


def test_model_size_knob_chooses_another_model():
    small = service.init_worker(configured(model_size=1))
    large = service.init_worker(configured(model_size=2))
    assert small.model_directory != large.model_directory
    assert len(spoken_words(large, 0, configured(model_size=2))) >= LEAST_WORDS_PER_CLIP


def test_quality_knob_sets_the_seconds_of_audio_that_are_transcribed():
    short = service.init_worker(configured(data_quality=2))
    long = service.init_worker(configured(data_quality=12))
    assert len(short.audio[0]) == 2 * service.SAMPLE_RATE * 2
    assert len(long.audio[0]) == 12 * service.SAMPLE_RATE * 2
    assert len(spoken_words(short, 0, configured(data_quality=2))) < len(
        spoken_words(long, 0, configured(data_quality=12))
    )


def test_process_returns_the_text_that_is_spoken_in_the_clip():
    cfg = configured()
    samples = service.init_worker(cfg)
    text = service.process(WorkItem(sample_index=0, payload=None), cfg, samples)
    assert isinstance(text, str)
    reference = samples.references[samples.clip_ids[0]].split()
    assert [word for word in text.split() if word in reference]


def test_word_error_rate_counts_substitutions_insertions_and_deletions():
    assert service.word_error_rate(["a", "b", "c"], ["a", "b", "c"]) == 0.0
    assert service.word_error_rate(["a", "b", "c"], ["a", "x", "c"]) == 1 / 3
    assert service.word_error_rate(["a", "b", "c"], ["a", "c"]) == 1 / 3
    assert service.word_error_rate(["a", "b", "c"], ["a", "b", "x", "c"]) == 1 / 3
    assert service.word_error_rate(["a", "b", "c"], []) == 1.0
