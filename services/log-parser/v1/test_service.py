import csv
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import service
from dsg.service_runtime.contract import WorkItem
from log_formats import WILDCARD, header_pattern_of, template_pattern_of

SERVICE_DIRECTORY = Path(__file__).parent
LOGHUB_DIRECTORY = SERVICE_DIRECTORY / "fetched" / "loghub"
DEFAULT_DATA_QUALITY = 500
DEFAULT_PATTERN_COUNT = 50
LEAST_SHARE_OF_LINES_WITH_AN_EVENT = 0.75
LEAST_AGREEMENT_WITH_LOGHUB_LABELS = 0.97


def configured(data_quality=DEFAULT_DATA_QUALITY, pattern_count=DEFAULT_PATTERN_COUNT):
    return SimpleNamespace(data_quality=data_quality, pattern_count=pattern_count, service_directory=SERVICE_DIRECTORY)


def parsed_sample(samples, sample_index, cfg):
    return service.parsed_of(service.process(WorkItem(sample_index=sample_index, payload=None), cfg, samples))


def loghub_labels(system):
    with open(LOGHUB_DIRECTORY / system / f"{system}_2k.log_structured.csv", encoding="utf-8", newline="") as structured:
        return list(csv.DictReader(structured))


def without_extra_whitespace(text):
    return re.sub(r"\s+", " ", text).strip()


def filled_in(template_text, parameters):
    pieces = template_text.split(WILDCARD)
    return pieces[0] + "".join(parameter + piece for parameter, piece in zip(parameters, pieces[1:]))


def test_proof():
    cfg = configured()
    samples = service.init_worker(cfg)
    templates = {template.event_id: template for template in samples.templates}
    labels = {system: loghub_labels(system) for system in service.SYSTEMS}
    lines = lines_with_an_event = lines_with_a_loaded_label = agreeing = 0
    for sample_index in range(service.SAMPLE_COUNT):
        parsed = parsed_sample(samples, sample_index, cfg)
        system = service.system_of(sample_index)
        assert parsed["system"] == system
        assert parsed["unparsed_lines"] == 0
        assert len(parsed["events"]) == DEFAULT_DATA_QUALITY
        assert sum(parsed["events_per_template"].values()) == DEFAULT_DATA_QUALITY
        for event in parsed["events"]:
            label = labels[system][event["line"]]
            assert event["content"] == label["Content"].strip()
            lines += 1
            if event["event"] is not None:
                lines_with_an_event += 1
                assert without_extra_whitespace(filled_in(templates[event["event"]].text, event["parameters"])) == (
                    without_extra_whitespace(event["content"])
                )
            true_event = f"{system}:{label['EventId']}"
            if true_event in templates:
                lines_with_a_loaded_label += 1
                agreeing += event["event"] == true_event
    assert lines == service.SAMPLE_COUNT * DEFAULT_DATA_QUALITY
    assert lines_with_an_event / lines >= LEAST_SHARE_OF_LINES_WITH_AN_EVENT
    assert agreeing / lines_with_a_loaded_label >= LEAST_AGREEMENT_WITH_LOGHUB_LABELS


def test_data_quality_knob_sets_how_many_lines_an_item_holds():
    few = configured(data_quality=100)
    many = configured(data_quality=2000)
    assert len(parsed_sample(service.init_worker(few), 3, few)["events"]) == 100
    assert len(parsed_sample(service.init_worker(many), 3, many)["events"]) == 2000


def test_pattern_count_knob_sets_how_many_templates_are_tried():
    few = configured(pattern_count=5)
    many = configured(pattern_count=200)
    few_samples = service.init_worker(few)
    many_samples = service.init_worker(many)
    assert len(few_samples.templates) == 5
    assert len(many_samples.templates) == 200
    without_event_few = sum(parsed_sample(few_samples, index, few)["events_per_template"].get("None", 0) for index in range(8))
    without_event_many = sum(parsed_sample(many_samples, index, many)["events_per_template"].get("None", 0) for index in range(8))
    assert without_event_many < without_event_few


def test_process_returns_the_parsed_block_as_json_bytes():
    cfg = configured()
    output = service.process(WorkItem(sample_index=0, payload=None), cfg, service.init_worker(cfg))
    assert isinstance(output, bytes)
    assert set(service.parsed_of(output)) == {"system", "events", "events_per_template", "unparsed_lines"}


def test_every_sample_comes_from_a_block_inside_its_log():
    for lines_per_item in (100, 500, 2000):
        for sample_index in range(service.SAMPLE_COUNT):
            start = service.block_start(sample_index, lines_per_item)
            assert 0 <= start and start + lines_per_item <= service.LINES_PER_LOG


def test_templates_are_interleaved_across_systems_most_frequent_first():
    templates = service.templates_in_matching_order(LOGHUB_DIRECTORY)
    assert [template.event_id.split(":")[0] for template in templates[: len(service.SYSTEMS)]] == list(service.SYSTEMS)
    assert len({template.event_id for template in templates}) == len(templates)


def test_template_pattern_captures_the_wildcards():
    pattern = template_pattern_of("Accepted password for <*> from <*> port <*> ssh2")
    assert pattern.fullmatch("Accepted password for root from 10.0.0.1 port 22 ssh2").groups() == ("root", "10.0.0.1", "22")
    assert pattern.fullmatch("Accepted publickey for root from 10.0.0.1 port 22 ssh2") is None


def test_header_pattern_splits_the_content_from_the_header():
    pattern = header_pattern_of(r"<Date> <Day> <Time> <Component> sshd\[<Pid>\]: <Content>")
    header = pattern.match("Dec 10 06:55:46 LabSZ sshd[24200]: Connection closed by 1.2.3.4 [preauth]")
    assert header.group("Pid") == "24200"
    assert header.group("Content") == "Connection closed by 1.2.3.4 [preauth]"
