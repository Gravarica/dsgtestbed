from pathlib import Path

import pytest

from dsg.experiment.plan import load_experiment, run_plans

B3 = Path(__file__).parents[3] / "experiments" / "b3"
FILES = sorted(B3.glob("b3-*.yaml"))
SHAPES = {
    "b3-balanced-1": (1, 0, 1),
    "b3-balanced-2": (2, 1, 2),
    "b3-balanced-3": (4, 3, 3),
    "b3-balanced-4": (8, 7, 4),
    "b3-narrow-4": (4, 3, 4),
    "b3-narrow-6": (6, 5, 6),
    "b3-narrow-8": (8, 7, 8),
    "b3-star-4": (4, 1, 2),
    "b3-star-8": (8, 1, 2),
    "b3-star-16": (16, 1, 2),
}


def longest_path(plan) -> int:
    topology = plan.topology()
    depth = {}
    for name in topology.from_first_to_last():
        feeders = [feeder for feeder in topology.feeders_of(name) if feeder != "camera"]
        depth[name] = 0 if name == "camera" else 1 + max((depth[feeder] for feeder in feeders), default=0)
    return max(depth.values())


def test_every_tree_of_the_spec_has_a_file():
    assert sorted(path.stem for path in FILES) == sorted(SHAPES)


@pytest.mark.parametrize("experiment_file", FILES, ids=lambda path: path.stem)
def test_every_b3_run_has_one_worker_per_service_joins_and_the_shape_of_its_tree(experiment_file):
    plans = run_plans(load_experiment(experiment_file), 28)
    leaves, merges, depth = SHAPES[experiment_file.stem]
    for plan in plans:
        assert plan.fan_in == "join" and plan.link == "requests" and plan.cpu_slack == 1.15
        assert all(node.knobs["parallelism"] == 1 for node in plan.nodes)
        assert sum(node.service == "image-transformer" for node in plan.nodes) == merges
        assert sum(node.service in ("cv-analyzer", "face-detector") for node in plan.nodes) == leaves
        assert plan.topology().sources() == ["camera"]
        assert longest_path(plan) == depth
        assert len({node.knobs["data_quality"] for node in plan.nodes if "data_quality" in node.knobs}) == 1
        assert all(node.knobs["model_size"] in (1, 2) for node in plan.nodes if node.service in ("cv-analyzer", "face-detector"))


@pytest.mark.parametrize("experiment_file", FILES, ids=lambda path: path.stem)
def test_b3_caps_cores_at_the_probe_and_keeps_the_camera_at_its_cores(experiment_file):
    plan = run_plans(load_experiment(experiment_file), 28)[0]
    assert plan.cap_cores_at_the_probe
    assert [node.auto_cores for node in plan.nodes if node.name == "camera"] == [False]


@pytest.mark.parametrize("experiment_file", FILES, ids=lambda path: path.stem)
def test_trees_with_more_than_four_leaves_use_frames_of_at_most_256_pixels(experiment_file):
    leaves = SHAPES[experiment_file.stem][0]
    highest = 640 if leaves <= 4 else 256
    qualities = {node.knobs["data_quality"] for plan in run_plans(load_experiment(experiment_file), 28)
                 for node in plan.nodes if "data_quality" in node.knobs}
    assert min(qualities) >= 160 and max(qualities) <= highest


HEIGHT_FILES = sorted(B3.glob("b3h-height-*.yaml"))


def test_there_is_a_height_file_for_every_height_from_one_to_five():
    assert [path.stem for path in HEIGHT_FILES] == [f"b3h-height-{levels}" for levels in range(1, 6)]


@pytest.mark.parametrize("experiment_file", HEIGHT_FILES, ids=lambda path: path.stem)
def test_every_height_run_shares_one_model_size_and_one_frame_size_with_one_worker_on_one_and_a_half_cores(experiment_file):
    levels = int(experiment_file.stem.split("-")[-1])
    plans = run_plans(load_experiment(experiment_file), 28)
    assert len(plans) == 48
    assert {(plan.nodes[1].knobs["data_quality"], plan.nodes[1].knobs["model_size"]) for plan in plans} == {
        (quality, size) for quality in (160, 192, 224, 256) for size in (1, 2)
    }
    for plan in plans:
        assert plan.fan_in == "join" and plan.cpu_slack == 0
        assert sum(node.service in ("cv-analyzer", "face-detector") for node in plan.nodes) == 2 ** (levels - 1)
        assert len(plan.nodes) == 2 ** levels
        assert all(node.knobs["parallelism"] == 1 for node in plan.nodes)
        assert all(node.cores == 1.5 for node in plan.nodes if node.name != "camera")
        assert len({node.knobs["data_quality"] for node in plan.nodes if "data_quality" in node.knobs}) == 1
        assert len({node.knobs["model_size"] for node in plan.nodes if "model_size" in node.knobs}) == 1
        assert longest_path(plan) == levels
