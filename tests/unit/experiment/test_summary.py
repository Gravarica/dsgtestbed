import json

import pandas as pd
import yaml

from dsg.experiment.summary import write_summary

EXPERIMENT = {
    "nodes": {
        "qr": {"service": "qr-detector v1", "cores": [2, 3], "knobs": {"data_quality": [300, 552]}},
        "face": {"service": "face-detector v1", "cores": 2, "knobs": {"model_size": 1}},
    },
    "edges": ["qr -> face"],
    "link": "requests",
    "load": {"rps": [10, 20]},
    "run": {"warmup_seconds": 5, "measure_seconds": 20, "runs": 2},
}


def results_folder(tmp_path):
    folder = tmp_path / "results" / "qr-then-face" / "20260924-092357"
    folder.mkdir(parents=True)
    (folder / "experiment.yaml").write_text(yaml.safe_dump(EXPERIMENT))
    (folder / "provenance.json").write_text(json.dumps({
        "experiment": "qr-then-face", "started_at": "20260924-092357", "git_commit": "abc123",
        "hardware": {"hostname": "ai2", "cpu_model": "Ryzen", "cpu_count": 32, "ram_gb": 134.2},
    }))
    rows = []
    for run_id, cores, quality, rps, valid, flags, e2e in (
        ("run-0000", 2, 300, 10, True, "", 900.0),
        ("run-0001", 3, 552, 20, False, "qr:overloaded", 4000.0),
    ):
        for node, service, processing, waiting in (("qr", "qr-detector:v1", 8.0, 500.0), ("face", "face-detector:v1", 4.0, 600.0)):
            rows.append({
                "run_id": run_id, "repetition": 0, "node": node, "service": service, "pipeline": "qr->face", "link": "requests",
                "rps_on_first_service": rps, "load_pattern": "constant",
                "qr.service": "qr-detector:v1", "qr.cores": cores, "qr.memory": "8g", "qr.parallelism": 1, "qr.data_quality": quality,
                "face.service": "face-detector:v1", "face.cores": 2, "face.memory": "8g", "face.parallelism": 1, "face.model_size": 1,
                "valid": valid, "flags": flags or float("nan"), "throttled_fraction": 0.2 if cores == 2 else 0.0, "cpu_seconds_used": 5.0,
                "memory_mb_under_load": 500.0, "config_id": "c", "measured_items": 600, "rate_received": rps, "arrival_lateness_p99_ms": 0.1,
                "processing_mean_ms": processing, "processing_p99_ms": processing * 1.5, "waiting_mean_ms": waiting, "waiting_p99_ms": 990.0,
                "sojourn_mean_ms": processing + waiting, "requests_entered": 600, "requests_completed": 600,
                "end_to_end_mean_ms": e2e, "end_to_end_p50_ms": e2e, "end_to_end_p95_ms": e2e * 1.2, "end_to_end_p99_ms": e2e * 1.3,
            })
        run_folder = folder / "runs" / run_id
        run_folder.mkdir(parents=True)
        (run_folder / "run.json").write_text(json.dumps({
            "workload_cpuset": "2-15", "nodes": {"qr": {"service": "qr-detector:v1", "image_id": "sha256:qr"}, "face": {"service": "face-detector:v1", "image_id": "sha256:face"}},
        }))
    pd.DataFrame(rows).to_csv(folder / "dataset.csv", index=False)
    return folder


def test_summary_describes_workflow_hardware_outcome_services_and_runs(tmp_path):
    folder = results_folder(tmp_path)
    summary = json.loads(write_summary(folder).read_text())
    assert summary["experiment"] == "qr-then-face"
    assert summary["started_at"] == "2026-09-24 09:23:57 UTC"
    workflow = summary["workflow"]
    assert workflow["pipeline"] == "qr->face" and workflow["link"] == "requests" and workflow["edges"] == ["qr -> face"]
    assert workflow["space"] == {"qr.cores": [2, 3], "qr.data_quality": [300, 552]}
    assert workflow["combinations_in_space"] == 8 and workflow["runs"] == 2
    assert summary["hardware"]["images"] == {"qr-detector v1": "sha256:qr", "face-detector v1": "sha256:face"}
    assert summary["hardware"]["workload_cpuset"] == "2-15" and summary["hardware"]["git_commit"] == "abc123"
    assert summary["outcome"] == {"runs": 2, "valid": 1, "invalid": 1, "flags": {"qr:overloaded": 1}}
    qr = summary["per_service"]["qr"]
    assert qr["valid_runs"] == 1 and qr["processing_ms"]["median"] == 8.0
    assert qr["marginal_means"]["data_quality"] == {"300": {"processing_mean_ms": 8.0, "waiting_mean_ms": 500.0}}
    assert qr["runs_with_throttling_over_10_percent"] == 1
    assert "model_size" not in summary["per_service"]["face"]["marginal_means"]
    assert summary["end_to_end"] == {"valid_runs": 1, "requests_completed_total": 600, "mean_ms": {"min": 900.0, "median": 900.0, "max": 900.0}, "p99_ms": {"min": 1170.0, "median": 1170.0, "max": 1170.0}}
    run = summary["runs"][1]
    assert run["run_id"] == "run-0001" and run["valid"] is False and run["flags"] == ["qr:overloaded"]
    assert run["settings"]["qr.data_quality"] == 552 and run["services"]["face"]["processing_mean_ms"] == 4.0
    assert run["end_to_end"]["end_to_end_mean_ms"] == 4000.0


def test_without_request_links_end_to_end_is_honestly_absent(tmp_path):
    folder = results_folder(tmp_path)
    dataset = pd.read_csv(folder / "dataset.csv")
    dataset["link"] = "rates"
    dataset.to_csv(folder / "dataset.csv", index=False)
    (folder / "experiment.yaml").write_text(yaml.safe_dump({**EXPERIMENT, "link": "rates"}))
    summary = json.loads(write_summary(folder).read_text())
    assert summary["end_to_end"] is None
    assert "end_to_end" not in summary["runs"][0] or summary["runs"][0].get("end_to_end") is None


def test_a_campaign_folder_gets_one_entry_per_experiment_found_through_status(tmp_path):
    results_folder(tmp_path)
    campaign = tmp_path / "results" / "campaigns" / "night"
    campaign.mkdir(parents=True)
    (campaign / "status.txt").write_text(
        "campaign night started 2026-09-24 09:23:56, 2 experiments\n"
        "[1/2] experiments/night/qr-then-face.yaml started 2026-09-24 09:23:56\n"
        "[1/2] experiments/night/qr-then-face.yaml finished 2026-09-24 09:58:12, 1 valid and 1 invalid runs so far\n"
        "[2/2] experiments/night/missing.yaml started 2026-09-24 09:58:12\n"
        "campaign night done 2026-09-24 10:30:00\n"
    )
    summary = json.loads(write_summary(campaign).read_text())
    assert summary["campaign"] == "night"
    assert summary["started"] == "2026-09-24 09:23:56" and summary["done"] == "2026-09-24 10:30:00"
    assert [item["experiment"] for item in summary["experiments"]] == ["qr-then-face"]
    assert summary["experiments"][0]["results"] == "results/qr-then-face/20260924-092357"
    assert (summary["runs"], summary["valid"], summary["invalid"]) == (2, 1, 1)
    assert summary["hardware"]["hostname"] == "ai2"


def test_summary_counts_the_rows_of_every_csv_so_a_cut_off_copy_is_noticed(tmp_path):
    folder = results_folder(tmp_path)
    (folder / "runs" / "run-0000" / "qr").mkdir(parents=True)
    (folder / "runs" / "run-0000" / "qr" / "records.csv").write_text("a,b\n1,2\n3,4\n")
    rows = json.loads(write_summary(folder).read_text())["csv_rows"]
    assert rows["dataset.csv"] == 4
    assert rows["runs/run-0000/qr/records.csv"] == 2


def test_an_experiment_whose_every_run_had_no_records_still_gets_a_summary(tmp_path):
    folder = results_folder(tmp_path)
    dataset = pd.read_csv(folder / "dataset.csv")
    dataset.drop(columns=[c for c in dataset.columns if c.startswith(("processing_", "waiting_"))]).assign(valid=False).to_csv(folder / "dataset.csv", index=False)
    summary = json.loads(write_summary(folder).read_text())
    assert summary["per_service"]["qr"]["processing_ms"] == {"min": None, "median": None, "max": None}
    assert summary["outcome"]["valid"] == 0
