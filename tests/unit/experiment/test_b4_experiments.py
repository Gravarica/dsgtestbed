from pathlib import Path

import pytest

from dsg.experiment.plan import load_experiment, run_plans

APPLICATIONS = Path(__file__).parents[3] / "experiments" / "applications"
B4_FILES = sorted(APPLICATIONS.glob("b4a*.yaml")) + sorted(APPLICATIONS.glob("b4b*.yaml"))


def configurations(experiment_file):
    return [(plan.repetition, plan.settings_by_node()) for plan in run_plans(load_experiment(experiment_file), 28)]


def test_there_are_six_loads_and_eight_variabilities_in_each_of_two_batches():
    assert len(B4_FILES) == 28


@pytest.mark.parametrize("experiment_file", B4_FILES, ids=lambda path: path.stem)
def test_every_b4_run_has_the_configuration_of_the_same_run_of_b1_vision_1(experiment_file):
    b1 = APPLICATIONS / ("b1u2-vision-1.yaml" if experiment_file.stem.startswith(("b4a2", "b4b2")) else "b1u-vision-1.yaml")
    assert configurations(experiment_file) == configurations(b1)


@pytest.mark.parametrize("experiment_file", sorted(APPLICATIONS.glob("b4b*.yaml")), ids=lambda path: path.stem)
def test_b4b_keeps_the_load_of_b1_and_changes_only_the_variability_of_the_gaps(experiment_file):
    variability = float(experiment_file.stem.split("-")[-1])
    for plan in run_plans(load_experiment(experiment_file), 28):
        assert plan.utilization == 0.5 and plan.arrival_process == "renewal" and plan.arrival_variability == variability


@pytest.mark.parametrize("experiment_file", sorted(APPLICATIONS.glob("b4a*.yaml")), ids=lambda path: path.stem)
def test_b4a_changes_only_the_load(experiment_file):
    utilization = float(experiment_file.stem.split("-")[-1])
    for plan in run_plans(load_experiment(experiment_file), 28):
        assert plan.utilization == utilization and plan.arrival_process == "poisson"
