from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import List

from payloads import mixed_payloads

SIGNING_KEY = b"dsg-testbed hash-signer shared key"
SAMPLE_COUNT = 30


@dataclass
class Payloads:
    contents: List[bytes]


def init_worker(cfg) -> Payloads:
    return Payloads(contents=mixed_payloads(SAMPLE_COUNT, int(cfg.data_quality)))


def process(item, cfg, payloads: Payloads) -> bytes:
    digest = hashlib.new(cfg.algorithm, payloads.contents[item.sample_index]).digest()
    signature = hashlib.pbkdf2_hmac(cfg.algorithm, SIGNING_KEY, digest, int(cfg.rounds))
    return digest + signature


def digest_and_signature(signed: bytes) -> tuple:
    half = len(signed) // 2
    return signed[:half], signed[half:]
