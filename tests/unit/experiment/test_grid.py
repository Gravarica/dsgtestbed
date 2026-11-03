from dsg.experiment import grid
from dsg.node import NodeSettings

EXPERIMENT = """
nodes:
  qr: {service: qr-detector v1, knobs: {data_quality: [320, 552]}}
load: {rps: 10}
run: {warmup_seconds: 1, measure_seconds: 1}
"""


class CrashingRun:
    projects = []

    def __init__(self, project, **_):
        CrashingRun.projects.append(project)

    def execute(self):
        raise RuntimeError("port is already allocated")


def test_a_run_that_crashes_is_reported_and_the_next_run_still_happens(tmp_path, monkeypatch, capsys):
    experiment_file = tmp_path / "two-qualities.yaml"
    experiment_file.write_text(EXPERIMENT)
    monkeypatch.setattr(grid, "RESULTS_DIRECTORY", tmp_path / "results")
    monkeypatch.setattr(grid, "load_node_settings", lambda _: NodeSettings("2-15,18-31", "0-1,16-17", 18080, 18000))
    monkeypatch.setattr(grid.os, "sched_setaffinity", lambda *_: None)
    monkeypatch.setattr(grid, "PipelineRun", CrashingRun)
    monkeypatch.setattr(grid, "write_summary", lambda directory: directory / "summary.json")
    grid.run_experiment(experiment_file)
    printed = capsys.readouterr().out
    assert printed.count("-> INVALID (crashed: RuntimeError: port is already allocated)") == 2
    assert all(project.startswith("dsg-two-qualities-") for project in CrashingRun.projects)
