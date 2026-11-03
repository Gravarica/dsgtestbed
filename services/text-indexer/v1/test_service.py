import json
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DOCUMENT_COUNT = 200
DEFAULT_DATA_QUALITY = 50
DEFAULT_COMPRESSION_LEVEL = 6
DEFAULT_NGRAM_SIZE = 2
LEAST_COMPRESSION_RATIO = 2.5


def configured(
    data_quality=DEFAULT_DATA_QUALITY,
    compression_level=DEFAULT_COMPRESSION_LEVEL,
    ngram_size=DEFAULT_NGRAM_SIZE,
):
    return SimpleNamespace(
        data_quality=data_quality,
        compression_level=compression_level,
        ngram_size=ngram_size,
        service_directory=SERVICE_DIRECTORY,
    )


def record_for(documents, sample_index, cfg):
    return service.record_of(service.process(WorkItem(sample_index=sample_index, payload=None), cfg, documents))


def test_proof():
    cfg = configured()
    documents = service.init_worker(cfg)
    assert len(documents.names) == DOCUMENT_COUNT
    for sample_index, name in enumerate(documents.names):
        text = documents.texts[sample_index]
        compressed = service.process(WorkItem(sample_index=sample_index, payload=None), cfg, documents)
        record = service.record_of(compressed)
        assert record["document"] == name
        assert record["text"] == text
        words = service.TOKEN_PATTERN.findall(text.lower())
        assert len(words) > 100, name
        assert set(record["index"]) == set(words) | {
            f"{words[position]} {words[position + 1]}" for position in range(len(words) - 1)
        }
        for word in words[:50]:
            assert all(words[position] == word for position in record["index"][word])
            assert record["index"][word] == [
                position for position, other in enumerate(words) if other == word
            ]
        assert len(json.dumps(record).encode("utf-8")) / len(compressed) > LEAST_COMPRESSION_RATIO


def test_data_quality_knob_sets_how_much_of_each_document_is_processed():
    little = service.init_worker(configured(data_quality=10))
    whole = service.init_worker(configured(data_quality=100))
    assert len(little.texts[0]) == round(len(whole.texts[0]) * 0.1)
    assert whole.texts[0].startswith(little.texts[0])
    assert len(record_for(little, 0, configured(data_quality=10))["index"]) < len(
        record_for(whole, 0, configured(data_quality=100))["index"]
    )


def test_compression_level_knob_changes_how_hard_the_record_is_packed():
    documents = service.init_worker(configured())
    item = WorkItem(sample_index=0, payload=None)
    fastest = service.process(item, configured(compression_level=1), documents)
    strongest = service.process(item, configured(compression_level=9), documents)
    assert len(strongest) < len(fastest)
    assert zlib.decompress(strongest) == zlib.decompress(fastest)


def test_ngram_size_knob_sets_how_long_the_indexed_terms_are():
    documents = service.init_worker(configured())
    words = service.TOKEN_PATTERN.findall(documents.texts[0].lower())
    unigrams = record_for(documents, 0, configured(ngram_size=1))["index"]
    trigrams = record_for(documents, 0, configured(ngram_size=3))["index"]
    assert all(" " not in term for term in unigrams)
    assert set(unigrams) < set(trigrams)
    assert f"{words[0]} {words[1]} {words[2]}" in trigrams


def test_process_returns_the_compressed_record_as_bytes():
    documents = service.init_worker(configured())
    compressed = service.process(WorkItem(sample_index=0, payload=None), configured(), documents)
    assert isinstance(compressed, bytes)
    assert service.record_of(compressed)["document"] == documents.names[0]


def test_term_index_holds_every_position_of_every_term():
    assert service.term_index("A cat and a cat.", 2) == {
        "a": [0, 3],
        "cat": [1, 4],
        "and": [2],
        "a cat": [0, 3],
        "cat and": [1],
        "and a": [2],
    }
