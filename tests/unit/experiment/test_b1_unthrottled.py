from pathlib import Path

import pytest

from dsg.experiment.plan import load_experiment, run_plans

APPLICATIONS = Path(__file__).parents[3] / "experiments" / "applications"
FILES = sorted(APPLICATIONS.glob("b1u-*.yaml")) + sorted(APPLICATIONS.glob("b1u2-*.yaml"))


def test_there_are_two_unthrottled_batches_for_each_of_the_fifteen_chains():
    assert len(FILES) == 30


def test_the_second_batch_draws_other_runs_than_the_first():
    first = run_plans(load_experiment(APPLICATIONS / "b1u-vision-5.yaml"), 28)
    second = run_plans(load_experiment(APPLICATIONS / "b1u2-vision-5.yaml"), 28)
    assert [plan.settings_by_node() for plan in first] != [plan.settings_by_node() for plan in second]


@pytest.mark.parametrize("experiment_file", FILES, ids=lambda path: path.stem)
def test_every_unthrottled_run_gives_each_service_its_workers_plus_half_a_core(experiment_file):
    plans = run_plans(load_experiment(experiment_file), 28)
    assert len(plans) == 50
    for plan in plans:
        assert plan.cpu_slack == 0
        for node in plan.nodes:
            assert node.knobs["parallelism"] in (1, 2, 3, 4)
            assert node.cores == node.knobs["parallelism"] + 0.5
    assert {node.knobs["parallelism"] for plan in plans for node in plan.nodes} == {1, 2, 3, 4}
