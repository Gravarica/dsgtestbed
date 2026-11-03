import pytest

from dsg.experiment.estimate import estimate_of, estimate_table, expected_seconds
from dsg.experiment.plan import run_plans


def test_a_run_costs_its_load_plus_a_fixed_part_plus_a_part_per_service():
    chain = {
        "nodes": {"qr": {"service": "qr-detector v1"}, "face": {"service": "face-detector v1"}},
        "edges": ["qr -> face"],
        "load": {"rps": 10},
        "run": {"warmup_seconds": 5, "measure_seconds": 25},
    }
    assert expected_seconds(run_plans(chain, 28)[0]) == 5 + 25 + 15 + 2 * 3


def test_an_experiment_file_is_estimated_without_running_it(tmp_path):
    experiment_file = tmp_path / "tiny.yaml"
    experiment_file.write_text("nodes: {qr: {service: qr-detector v1, cores: [2, 3]}}\nload: {rps: [10, 20]}\nrun: {warmup_seconds: 5, measure_seconds: 25}\n")
    estimate = estimate_of(experiment_file, 28)
    assert (estimate["runs"], estimate["nodes"], estimate["largest_core_sum"]) == (4, 1, 3.0)
    assert estimate["hours"] == pytest.approx(4 * (5 + 25 + 15 + 3) / 3600)
    assert "tiny" in estimate_table([estimate]) and "total" in estimate_table([estimate])
