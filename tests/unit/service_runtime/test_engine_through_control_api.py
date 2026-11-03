import csv
import json
import time

import pytest

from dsg.monitor.exporter import PrometheusExporter
from dsg.service_runtime.contract import service_spec_from_mapping
from dsg.service_runtime.control_api import create_control_app
from dsg.service_runtime.engine import ServiceEngine
from dsg.service_runtime.settings import runtime_settings_from_environment
from dsg.service_runtime.timing import SystemClock

DUMMY_SERVICE = """
import time


def process(item, cfg, state):
    time.sleep(cfg.work_ms / 1000)
    return b"done"
"""

DUMMY_SPEC = {
    "name": "dummy",
    "version": "v1",
    "service_type": "dummy-service",
    "input": "any",
    "output": "bytes",
    "sample_count": 5,
    "knobs": {"work_ms": {"type": "int", "min": 1, "max": 100, "default": 2}},
}


@pytest.fixture
def control(tmp_path):
    service_directory = tmp_path / "service"
    service_directory.mkdir()
    (service_directory / "service.py").write_text(DUMMY_SERVICE)
    settings = runtime_settings_from_environment(
        {
            "SERVICE_DIRECTORY": str(service_directory),
            "RECORDS_DIRECTORY": str(tmp_path / "records"),
            "ARRIVAL_PROCESS": "deterministic",
            "QUEUE_CAPACITY": "50",
            "DRAIN_TIMEOUT_SECONDS": "20",
        }
    )
    engine = ServiceEngine(
        settings, service_spec_from_mapping(DUMMY_SPEC), SystemClock(), PrometheusExporter("dummy-service", "dummy-1")
    )
    client = create_control_app(engine).test_client()
    client.records_directory = tmp_path / "records"
    return client


def wait_until_finished(control, seconds=30):
    give_up_at = time.monotonic() + seconds
    while time.monotonic() < give_up_at:
        if control.get("/status").get_json()["state"] == "finished":
            return
        time.sleep(0.05)
    raise AssertionError("service did not finish draining")


def test_out_of_range_knob_is_refused_with_the_elastic_workbench_endpoint(control):
    assert control.put("/parallelism_scaling?parallelism=2").status_code == 200
    assert control.put("/parallelism_scaling?parallelism=500").status_code == 400
    assert control.put("/model_scaling?model_size=2").status_code == 404
    assert control.get("/knobs").get_json()["parallelism"] == 2


def test_one_run_admits_processes_drains_and_reconciles_every_item(control):
    control.put("/knob?name=window_ms&value=100")
    control.put("/parallelism_scaling?parallelism=2")
    control.put("/change_rps?client_id=C_1&rps=100")
    assert control.put("/start_processing").status_code == 200
    assert control.put("/knob?name=work_ms&value=5").status_code == 409
    time.sleep(0.5)
    control.put("/start_measurement")
    time.sleep(1.0)
    control.put("/stop_processing")
    wait_until_finished(control)

    status = control.get("/status").get_json()
    assert status["unresolved"] == 0
    assert status["admitted"] == status["completed"]

    records = list(csv.DictReader((control.records_directory / "records.csv").open()))
    measured = [row for row in records if row["admission_phase"] == "measure"]
    assert 80 <= len(measured) <= 120
    assert all(int(row["started_at_ns"]) >= int(row["released_at_ns"]) >= int(row["arrived_at_ns"]) for row in records)
    assert {row["window_index"] for row in records} != {""}

    summary = json.loads((control.records_directory / "run_summary.json").read_text())
    assert summary["flags"] == []
    assert summary["achieved_rate_per_second"] == pytest.approx(100, rel=0.1)
    assert len(summary["workers"]) == 2
    assert summary["rate_changes"][0]["rate_per_second"] == 100

    metrics_header = (control.records_directory / "metrics.csv").read_text().splitlines()[0]
    assert metrics_header.startswith("timestamp,service_type,container_id,avg_p_latency")


def test_the_rate_can_be_updated_while_the_service_is_processing(control):
    control.put("/knob?name=discipline&value=fifo")
    control.put("/change_rps?rps=50")
    control.put("/start_processing")
    control.put("/start_measurement")
    time.sleep(0.6)
    assert control.put("/change_rps?rps=200").status_code == 200
    time.sleep(0.6)
    control.put("/stop_processing")
    wait_until_finished(control)
    summary = json.loads((control.records_directory / "run_summary.json").read_text())
    assert [change["rate_per_second"] for change in summary["rate_changes"]] == [50, 200]
    assert 100 <= summary["counts"]["admitted"] <= 200


def test_overload_stops_the_source_flags_the_run_and_still_resolves_admitted_items(control):
    control.put("/knob?name=work_ms&value=50")
    control.put("/knob?name=discipline&value=fifo")
    control.put("/change_rps?rps=400")
    control.put("/start_processing")
    wait_until_finished(control)
    summary = json.loads((control.records_directory / "run_summary.json").read_text())
    assert "saturated_queue" in summary["flags"]
    assert summary["counts"]["unresolved"] == 0
    assert summary["counts"]["admitted"] == summary["counts"]["completed"]


def test_a_handed_over_request_is_processed_like_any_other_and_keeps_its_identity(control):
    assert control.put("/handover?request_id=qr-5&request_entered_at_ns=123&admission_phase=measure&handed_over_by=qr").status_code == 409
    control.put("/knob?name=discipline&value=fifo")
    control.put("/start_processing")
    for number in range(5):
        answer = control.put(f"/handover?request_id=qr-{number}&request_entered_at_ns={100 + number}&admission_phase=measure&handed_over_by=qr")
        assert answer.status_code == 200
    control.put("/stop_processing")
    wait_until_finished(control)
    assert control.put("/handover?request_id=qr-9&request_entered_at_ns=1&admission_phase=measure&handed_over_by=qr").status_code == 409
    records = list(csv.DictReader((control.records_directory / "records.csv").open()))
    assert sorted(row["request_id"] for row in records) == [f"qr-{number}" for number in range(5)]
    assert {row["handed_over_by"] for row in records} == {"qr"}
    assert {row["admission_phase"] for row in records} == {"measure"}
    assert sorted(int(row["request_entered_at_ns"]) for row in records) == [100, 101, 102, 103, 104]
    summary = json.loads((control.records_directory / "run_summary.json").read_text())
    assert summary["link"] == "rates" and summary["counts"]["unresolved"] == 0
