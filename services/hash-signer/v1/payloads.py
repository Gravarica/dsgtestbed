from __future__ import annotations

import random
from typing import List

PAYLOAD_SEED = 20260926
BYTES_PER_KILOBYTE = 1024
BLOCK_SIZE = 4096
TEXT_BLOCK = (
    b"sensor=vibration-07 site=hall-b reading=0.0431 unit=g status=ok "
    b"sensor=temperature-12 site=roof reading=21.7 unit=C status=ok "
)


def mixed_payloads(count: int, kilobytes: int) -> List[bytes]:
    generator = random.Random(PAYLOAD_SEED)
    return [mixed_payload(generator, sample_index, kilobytes * BYTES_PER_KILOBYTE) for sample_index in range(count)]


def mixed_payload(generator: random.Random, sample_index: int, size: int) -> bytes:
    blocks = []
    written = 0
    while written < size:
        block = next_block(generator, sample_index)
        blocks.append(block)
        written += len(block)
    return b"".join(blocks)[:size]


def next_block(generator: random.Random, sample_index: int) -> bytes:
    kind = generator.choice(("random", "text", "sparse"))
    if kind == "random":
        return generator.randbytes(BLOCK_SIZE)
    if kind == "text":
        return (TEXT_BLOCK + f"sample={sample_index} ".encode()) * (BLOCK_SIZE // len(TEXT_BLOCK) + 1)
    sparse = bytearray(BLOCK_SIZE)
    for position in generator.sample(range(BLOCK_SIZE), 64):
        sparse[position] = generator.randrange(1, 256)
    return bytes(sparse)
