import hashlib
import hmac
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem

SERVICE_DIRECTORY = Path(__file__).parent
DEFAULT_DATA_QUALITY = 64
DEFAULT_ALGORITHM = "sha256"
DEFAULT_ROUNDS = 20000


def configured(data_quality=DEFAULT_DATA_QUALITY, algorithm=DEFAULT_ALGORITHM, rounds=DEFAULT_ROUNDS):
    return SimpleNamespace(
        data_quality=data_quality,
        algorithm=algorithm,
        rounds=rounds,
        service_directory=SERVICE_DIRECTORY,
    )


def signed_sample(payloads, sample_index, cfg):
    return service.process(WorkItem(sample_index=sample_index, payload=None), cfg, payloads)


def reference_pbkdf2_first_block(algorithm, key, salt, rounds):
    block = hmac.new(key, salt + (1).to_bytes(4, "big"), algorithm).digest()
    combined = bytearray(block)
    for _ in range(rounds - 1):
        block = hmac.new(key, block, algorithm).digest()
        combined = bytearray(left ^ right for left, right in zip(combined, block))
    return bytes(combined)


def test_proof():
    cfg = configured()
    payloads = service.init_worker(cfg)
    assert len(payloads.contents) == service.SAMPLE_COUNT
    signatures = set()
    for sample_index, content in enumerate(payloads.contents):
        assert len(content) == DEFAULT_DATA_QUALITY * 1024
        digest, signature = service.digest_and_signature(signed_sample(payloads, sample_index, cfg))
        assert digest == hashlib.sha256(content).digest()
        assert signature == reference_pbkdf2_first_block("sha256", service.SIGNING_KEY, digest, DEFAULT_ROUNDS)
        wrong_key_signature = reference_pbkdf2_first_block("sha256", b"another key", digest, DEFAULT_ROUNDS)
        assert signature != wrong_key_signature
        signatures.add(signature)
    assert len(signatures) == service.SAMPLE_COUNT


def test_data_quality_knob_sets_the_payload_size():
    small = service.init_worker(configured(data_quality=1))
    large = service.init_worker(configured(data_quality=1024))
    assert len(small.contents[0]) == 1024
    assert len(large.contents[0]) == 1024 * 1024
    assert signed_sample(small, 0, configured(data_quality=1)) != signed_sample(large, 0, configured(data_quality=1024))


def test_algorithm_knob_sets_the_hash_function():
    payloads = service.init_worker(configured())
    for algorithm, digest_size in (("sha256", 32), ("sha512", 64), ("blake2b", 64), ("sha3_256", 32)):
        signed = signed_sample(payloads, 0, configured(algorithm=algorithm))
        digest, _ = service.digest_and_signature(signed)
        assert len(signed) == 2 * digest_size
        assert digest == hashlib.new(algorithm, payloads.contents[0]).digest()


def test_rounds_knob_sets_how_often_the_key_is_stretched():
    payloads = service.init_worker(configured())
    few = service.digest_and_signature(signed_sample(payloads, 0, configured(rounds=1000)))[1]
    many = service.digest_and_signature(signed_sample(payloads, 0, configured(rounds=2000)))[1]
    digest = hashlib.sha256(payloads.contents[0]).digest()
    assert few == reference_pbkdf2_first_block("sha256", service.SIGNING_KEY, digest, 1000)
    assert many == reference_pbkdf2_first_block("sha256", service.SIGNING_KEY, digest, 2000)
    assert few != many


def test_payloads_are_the_same_in_every_worker():
    assert service.init_worker(configured()).contents == service.init_worker(configured()).contents


def test_process_returns_bytes():
    payloads = service.init_worker(configured())
    assert isinstance(signed_sample(payloads, 0, configured()), bytes)
