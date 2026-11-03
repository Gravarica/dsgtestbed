from pathlib import Path

import pytest

from dsg.experiment.plan import load_experiment, run_plans

BENCHMARK = Path(__file__).parents[3] / "experiments" / "benchmark"
GRID_FILES = sorted(BENCHMARK.glob("grid-*.yaml"))
EVERY_FRAME_SIZE = list(range(160, 641, 32))


def frame_and_model_sizes(experiment_file):
    settings = [plan.settings_by_node() for plan in run_plans(load_experiment(experiment_file), 28)]
    return sorted((run["service.data_quality"], run.get("service.model_size", 0)) for run in settings)


def test_the_three_services_of_the_trees_have_a_grid_at_five_loads():
    assert len(GRID_FILES) == 15


@pytest.mark.parametrize("experiment_file", GRID_FILES, ids=lambda path: path.stem)
def test_a_grid_runs_every_frame_size_with_every_model_size_once(experiment_file):
    model_sizes = [0] if "image-transformer" in experiment_file.stem else [1, 2]
    assert frame_and_model_sizes(experiment_file) == [(size, model) for size in EVERY_FRAME_SIZE for model in model_sizes]


@pytest.mark.parametrize("experiment_file", GRID_FILES, ids=lambda path: path.stem)
def test_a_grid_is_measured_like_the_benchmark(experiment_file):
    grid = load_experiment(experiment_file)
    benchmark = load_experiment(BENCHMARK / experiment_file.name.replace("grid-", "bench-"))
    del benchmark["run"]["runs"]
    assert grid == benchmark
