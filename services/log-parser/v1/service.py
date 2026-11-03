from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from log_formats import LOG_FORMATS, header_pattern_of, template_pattern_of

SYSTEMS = tuple(LOG_FORMATS)
SAMPLE_COUNT = 60
LINES_PER_LOG = 2000
BLOCK_STEP = 263


@dataclass(frozen=True)
class Template:
    event_id: str
    text: str
    pattern: re.Pattern


@dataclass
class Samples:
    systems: List[str]
    first_line_numbers: List[int]
    blocks: List[List[str]]
    header_patterns: Dict[str, re.Pattern]
    templates: List[Template]


def init_worker(cfg) -> Samples:
    loghub_directory = Path(cfg.service_directory) / "fetched" / "loghub"
    lines_per_item = int(cfg.data_quality)
    logs = {system: raw_lines_of(loghub_directory, system) for system in SYSTEMS}
    systems, first_line_numbers, blocks = [], [], []
    for sample_index in range(SAMPLE_COUNT):
        system = system_of(sample_index)
        start = block_start(sample_index, lines_per_item)
        systems.append(system)
        first_line_numbers.append(start)
        blocks.append(logs[system][start : start + lines_per_item])
    return Samples(
        systems=systems,
        first_line_numbers=first_line_numbers,
        blocks=blocks,
        header_patterns={system: header_pattern_of(LOG_FORMATS[system]) for system in SYSTEMS},
        templates=templates_in_matching_order(loghub_directory)[: int(cfg.pattern_count)],
    )


def process(item, cfg, samples: Samples) -> bytes:
    system = samples.systems[item.sample_index]
    header_pattern = samples.header_patterns[system]
    first_line_number = samples.first_line_numbers[item.sample_index]
    events = []
    events_per_template: Counter = Counter()
    unparsed_lines = 0
    for offset, line in enumerate(samples.blocks[item.sample_index]):
        header = header_pattern.match(line)
        if header is None:
            unparsed_lines += 1
            continue
        fields = header.groupdict()
        content = fields.pop("Content").strip()
        template, parameters = matching_template(content, samples.templates)
        event_id = template.event_id if template else None
        events_per_template[event_id] += 1
        events.append(
            {"line": first_line_number + offset, "fields": fields, "content": content, "event": event_id, "parameters": parameters}
        )
    parsed = {
        "system": system,
        "events": events,
        "events_per_template": {str(event_id): count for event_id, count in events_per_template.items()},
        "unparsed_lines": unparsed_lines,
    }
    return json.dumps(parsed).encode("utf-8")


def matching_template(content: str, templates: List[Template]) -> Tuple[Optional[Template], List[str]]:
    for template in templates:
        matched = template.pattern.fullmatch(content)
        if matched:
            return template, list(matched.groups())
    return None, []


def system_of(sample_index: int) -> str:
    return SYSTEMS[sample_index % len(SYSTEMS)]


def block_start(sample_index: int, lines_per_item: int) -> int:
    return (sample_index // len(SYSTEMS)) * BLOCK_STEP % (LINES_PER_LOG - lines_per_item + 1)


def raw_lines_of(loghub_directory: Path, system: str) -> List[str]:
    text = (loghub_directory / system / f"{system}_2k.log").read_text(encoding="utf-8", errors="replace")
    return text.splitlines()[:LINES_PER_LOG]


def templates_in_matching_order(loghub_directory: Path) -> List[Template]:
    per_system = [templates_by_frequency(loghub_directory, system) for system in SYSTEMS]
    interleaved = [template for round_of_templates in zip_longest(*per_system) for template in round_of_templates]
    return [template for template in interleaved if template is not None]


def templates_by_frequency(loghub_directory: Path, system: str) -> List[Template]:
    folder = loghub_directory / system
    with open(folder / f"{system}_2k.log_structured.csv", encoding="utf-8", newline="") as structured:
        occurrences = Counter(row["EventId"] for row in csv.DictReader(structured))
    with open(folder / f"{system}_2k.log_templates.csv", encoding="utf-8", newline="") as listed:
        rows = list(csv.DictReader(listed))
    rows.sort(key=lambda row: (-occurrences[row["EventId"]], int(row["EventId"].lstrip("E"))))
    return [
        Template(event_id=f"{system}:{row['EventId']}", text=row["EventTemplate"], pattern=template_pattern_of(row["EventTemplate"]))
        for row in rows
    ]


def parsed_of(output: bytes) -> dict:
    return json.loads(output.decode("utf-8"))
