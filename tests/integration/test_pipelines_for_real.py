import csv
import json
import time

import pytest

from dsg.docker_host import DockerHost
from dsg.experiment.dataset import dataset_rows
from dsg.experiment.plan import run_plans
from dsg.experiment.run import PipelineRun
from dsg.node import load_node_settings
from dsg.repository import NODE_FILE
from dsg.service_runtime.control_client import ControlClient

pytestmark = pytest.mark.integration

QR_ALONE = {
    "nodes": {"qr": {"service": "qr-detector v1", "cores": 3, "parallelism": 2, "window_ms": 500, "knobs": {"data_quality": 552}}},
    "load": {"rps": 30},
    "run": {"warmup_seconds": 2, "measure_seconds": 5},
}
QR_THEN_FACE = {
    "nodes": {
        "qr": {"service": "qr-detector v1", "cores": 2, "knobs": {"data_quality": 552}},
        "face": {"service": "face-detector v1", "cores": 2, "knobs": {"model_size": 1}},
    },
    "edges": ["qr -> face"],
    "load": {"rps": 30, "arrival_process": "deterministic"},
    "run": {"warmup_seconds": 4, "measure_seconds": 10},
}


def run_for_real(experiment, run_directory):
    node_settings = load_node_settings(NODE_FILE)
    plan = run_plans(experiment, node_settings.workload_cpu_count())[0]
    return PipelineRun(
        plan=plan,
        node_settings=node_settings,
        project=f"dsg-integration-{int(time.time())}",
        run_directory=run_directory,
        docker=DockerHost(),
        service_at=ControlClient,
        wait=time.sleep,
    ).execute()


def test_one_real_service_runs_measures_drains_and_reconciles(tmp_path):
    described = run_for_real(QR_ALONE, tmp_path)
    assert described["valid"], described
    summary = json.loads((tmp_path / "qr" / "run_summary.json").read_text())
    assert summary["counts"]["unresolved"] == 0
    assert summary["counts"]["admitted"] == summary["counts"]["completed"]
    assert summary["workers"][0]["native_threads"]["opencv"] == 1
    records = list(csv.DictReader((tmp_path / "qr" / "records.csv").open()))
    measured = [row for row in records if row["admission_phase"] == "measure"]
    assert 100 <= len(measured) <= 200


def test_in_a_real_chain_the_second_service_receives_the_rate_the_first_one_achieves(tmp_path):
    described = run_for_real(QR_THEN_FACE, tmp_path)
    assert described["valid"], described
    rows = {row["node"]: row for row in dataset_rows(tmp_path)}
    assert rows["qr"]["rate_received"] == pytest.approx(30, rel=0.1)
    assert rows["face"]["rate_received"] == pytest.approx(rows["qr"]["rate_received"], rel=0.2)
    face_summary = json.loads((tmp_path / "face" / "run_summary.json").read_text())
    assert face_summary["counts"]["unresolved"] == 0
    assert {change["rate_per_second"] for change in face_summary["rate_changes"]} - {0.0}
    face_metrics = list(csv.DictReader((tmp_path / "face" / "metrics.csv").open()))
    assert max(float(row["rps"]) for row in face_metrics) > 20


def test_with_request_links_every_request_is_followed_from_the_first_service_to_the_last(tmp_path):
    import pandas as pd

    from dsg.experiment.traces import write_traces

    three_services = {
        "nodes": {
            "qr": {"service": "qr-detector v1", "cores": 2, "window_ms": 500, "knobs": {"data_quality": 552}},
            "face": {"service": "face-detector v1", "cores": 2, "window_ms": 500, "knobs": {"model_size": 1}},
            "pc": {"service": "pc-visualizer v1", "cores": 2, "window_ms": 500, "knobs": {"data_quality": 30}},
        },
        "edges": ["qr -> face", "face -> pc"],
        "link": "requests",
        "load": {"rps": 25},
        "run": {"warmup_seconds": 3, "measure_seconds": 10},
    }
    described = run_for_real(three_services, tmp_path)
    assert described["valid"], described
    end_to_end = write_traces(tmp_path)
    traces = pd.read_csv(tmp_path / "traces.csv")
    steps = pd.read_csv(tmp_path / "trace_steps.csv")

    assert end_to_end["requests_entered"] == end_to_end["requests_completed"] == len(traces)
    assert 200 <= len(traces) <= 300
    assert (traces["services_passed"] == 3).all()
    assert steps.groupby("request_id")["node"].apply(list).map(lambda path: path == ["qr", "face", "pc"]).all()

    parts = steps[["handover_ms", "waiting_ms", "processing_ms"]].fillna(0).sum(axis=1).groupby(steps["request_id"]).sum()
    totals = traces.set_index("request_id")["total_ms"]
    assert (parts - totals).abs().max() < 0.001
    assert steps["handover_ms"].dropna().between(0, 50).all()

    for node in ("qr", "face", "pc"):
        summary = json.loads((tmp_path / node / "run_summary.json").read_text())
        assert summary["counts"]["unresolved"] == 0 and summary["link"] == "requests"
