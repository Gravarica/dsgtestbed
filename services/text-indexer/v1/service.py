from __future__ import annotations

import json
import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

TOKEN_PATTERN = re.compile(r"[a-z0-9']+")


@dataclass
class Documents:
    names: List[str]
    texts: List[str]


def init_worker(cfg) -> Documents:
    documents_directory = Path(cfg.service_directory) / "fetched" / "documents"
    kept = int(cfg.data_quality) / 100
    names, texts = [], []
    for document_file in sorted(documents_directory.glob("*.txt")):
        text = document_file.read_text(encoding="utf-8")
        names.append(document_file.stem)
        texts.append(text[: max(1, round(len(text) * kept))])
    return Documents(names=names, texts=texts)


def process(item, cfg, documents: Documents) -> bytes:
    record = {
        "document": documents.names[item.sample_index],
        "text": documents.texts[item.sample_index],
        "index": term_index(documents.texts[item.sample_index], int(cfg.ngram_size)),
    }
    return zlib.compress(json.dumps(record).encode("utf-8"), int(cfg.compression_level))


def term_index(text: str, ngram_size: int) -> Dict[str, List[int]]:
    words = TOKEN_PATTERN.findall(text.lower())
    index: Dict[str, List[int]] = {}
    for term_length in range(1, ngram_size + 1):
        for position in range(len(words) - term_length + 1):
            index.setdefault(" ".join(words[position : position + term_length]), []).append(position)
    return index


def record_of(compressed: bytes) -> dict:
    return json.loads(zlib.decompress(compressed).decode("utf-8"))
