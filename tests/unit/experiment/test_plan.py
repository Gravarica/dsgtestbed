import pytest

from dsg.experiment.plan import PlanInvalid, run_plans

CHAIN = {
    "nodes": {
        "qr": {"service": "qr-detector v1", "cores": [2, 3], "knobs": {"data_quality": [300, 552]}},
        "cv": {"service": "cv-analyzer v1", "parallelism": [1, 2], "knobs": {"model_size": 1}},
    },
    "edges": ["qr -> cv"],
    "load": {"rps": [10, 20]},
    "run": {"seed": 3, "repetitions": 2},
}


def smallest():
    return {"nodes": {"qr": {"service": "qr-detector v1"}}, "load": {"rps": 20}}


def test_the_smallest_file_is_one_run_with_defaults():
    plans = run_plans(smallest(), workload_cpu_count=28)
    assert len(plans) == 1
    node = plans[0].nodes[0]
    assert (node.service, node.version, node.cores, node.memory) == ("qr-detector", "v1", 2.0, "8g")
    assert node.knobs == {"parallelism": 1}
    assert (plans[0].rps, plans[0].load_pattern, plans[0].warmup_seconds, plans[0].measure_seconds) == (20, "constant", 10, 60)


def test_every_list_is_a_dimension_and_single_values_stay_fixed():
    plans = run_plans(CHAIN, 28)
    assert len(plans) == 2 * 2 * 2 * 2 * 2
    assert {plan.nodes[0].cores for plan in plans} == {2.0, 3.0}
    assert {plan.nodes[1].knobs["model_size"] for plan in plans} == {1}
    assert plans[0].edges == (("qr", "cv"),)


def test_a_service_without_cores_gets_one_more_than_its_largest_number_of_workers():
    assert {plan.nodes[1].cores for plan in run_plans(CHAIN, 28)} == {3.0}


def test_runs_picks_a_reproducible_random_part_of_the_space():
    limited = {**CHAIN, "run": {"seed": 3, "runs": 5}}
    first = [plan.settings_by_node() for plan in run_plans(limited, 28)]
    assert len(first) == 5
    assert first == [plan.settings_by_node() for plan in run_plans(limited, 28)]
    assert first != [plan.settings_by_node() for plan in run_plans({**CHAIN, "run": {"seed": 4, "runs": 5}}, 28)]


def test_settings_of_every_service_are_named_by_their_node():
    settings = run_plans(CHAIN, 28)[0].settings_by_node()
    assert settings["qr.service"] == "qr-detector:v1"
    assert {"qr.cores", "qr.data_quality", "cv.parallelism", "cv.model_size", "cv.memory"} <= set(settings)


@pytest.mark.parametrize(
    "change, complaint",
    [
        ({"nodes": {"qr": {"service": "ghost-service v1"}}}, "no service ghost-service"),
        ({"nodes": {"qr": {"service": "qr-detector"}}}, "name version"),
        ({"nodes": {"qr": {"service": "qr-detector v1", "knobs": {"data_quality": 5000}}}}, "outside"),
        ({"nodes": {"qr": {"service": "qr-detector v1", "knobs": {"model_size": 2}}}}, "no knob model_size"),
        ({"nodes": {"qr": {"service": "qr-detector v1", "data_quality": 300}}}, "go under 'knobs:'"),
        ({"nodes": {"qr": {"service": "qr-detector v1", "cores": 64}}}, "64.0 cores in total"),
        ({"nodes": {"qr": {"service": "qr-detector v1"}}, "edges": ["qr -> cv"]}, "do not exist"),
        ({"nodes": {"qr": {"service": "qr-detector v1"}}, "load": {"rps": 5, "pattern": "sawtooth"}}, "load pattern"),
        ({"nodes": {}}, "no 'nodes:'"),
    ],
)
def test_files_that_cannot_work_are_refused_before_anything_starts(change, complaint):
    with pytest.raises(PlanInvalid, match=complaint):
        run_plans({**smallest(), **change}, 28)


def test_services_are_linked_by_rates_unless_the_file_asks_for_requests():
    assert run_plans(CHAIN, 28)[0].link == "rates"
    assert run_plans({**CHAIN, "link": "requests"}, 28)[0].link == "requests"
    with pytest.raises(PlanInvalid, match="link must be one of"):
        run_plans({**CHAIN, "link": "pigeons"}, 28)


def test_the_cores_of_all_services_together_must_fit_on_the_machine():
    with pytest.raises(PlanInvalid, match="cores in total"):
        run_plans(CHAIN, workload_cpu_count=4)


def test_a_range_is_a_dimension_of_every_step_from_first_to_last():
    ranged = {"nodes": {"qr": {"service": "qr-detector v1", "cores": {"from": 1, "to": 2.5, "step": 0.5}}}, "load": {"rps": {"from": 10, "to": 30, "step": 10}}}
    plans = run_plans(ranged, 28)
    assert {plan.nodes[0].cores for plan in plans} == {1.0, 1.5, 2.0, 2.5}
    assert {plan.rps for plan in plans} == {10.0, 20.0, 30.0}
    with pytest.raises(PlanInvalid, match="a range is written as"):
        run_plans({**smallest(), "load": {"rps": {"from": 10}}}, 28)


def huge_tree(runs, seed=5):
    sensor = {"service": "qr-detector v1", "cores": {"from": 1, "to": 4}, "knobs": {"data_quality": {"from": 100, "to": 1000, "step": 50}}}
    return {
        "nodes": {**{f"s{index}": dict(sensor) for index in range(6)}, "final": {"service": "text-indexer v1", "cores": {"from": 1, "to": 4}}},
        "edges": [f"s{index} -> final" for index in range(6)],
        "load": {"rps": {"from": 5, "to": 40, "step": 5}},
        "run": {"runs": runs, "seed": seed},
    }


def test_a_space_too_large_to_list_is_drawn_from_reproducibly_and_only_where_it_fits():
    plans = run_plans(huge_tree(runs=50), workload_cpu_count=14)
    assert len(plans) == 50
    assert all(sum(node.cores for node in plan.nodes) <= 14 for plan in plans)
    assert len({tuple(sorted(plan.settings_by_node().items())) + (plan.rps,) for plan in plans}) == 50
    again = run_plans(huge_tree(runs=50), workload_cpu_count=14)
    assert [plan.settings_by_node() for plan in plans] == [plan.settings_by_node() for plan in again]
    other_seed = run_plans(huge_tree(runs=50, seed=6), workload_cpu_count=14)
    assert [plan.settings_by_node() for plan in plans] != [plan.settings_by_node() for plan in other_seed]


def test_a_space_too_large_to_list_needs_a_number_of_runs():
    tree = huge_tree(runs=1)
    del tree["run"]["runs"]
    with pytest.raises(PlanInvalid, match="say how many to run"):
        run_plans(tree, 28)


def test_only_a_share_of_the_runs_is_repeated():
    shared = {**CHAIN, "run": {"seed": 3, "runs": 10, "repetitions": 3, "repeated_share": 0.2}}
    plans = run_plans(shared, 28)
    assert len(plans) == 2 * 3 + 8 * 1
    assert sorted(plan.repetition for plan in plans).count(2) == 2


def test_a_source_can_have_its_own_rate_and_the_others_take_the_load_rate():
    merge = {
        "nodes": {
            "speech": {"service": "speech-transcriber v1", "rps": [0.5, 1]},
            "qr": {"service": "qr-detector v1"},
            "idx": {"service": "text-indexer v1"},
        },
        "edges": ["speech -> idx", "qr -> idx"],
        "load": {"rps": 20},
    }
    plans = run_plans(merge, 28)
    assert {plan.rate_of("speech") for plan in plans} == {0.5, 1.0}
    assert {plan.rate_of("qr") for plan in plans} == {20.0}
    assert {plan.settings_by_node()["speech.rps"] for plan in plans} == {0.5, 1.0}
    with pytest.raises(PlanInvalid, match="cannot have its own rps"):
        run_plans({**merge, "nodes": {**merge["nodes"], "idx": {"service": "text-indexer v1", "rps": 5}}}, 28)


def test_every_load_setting_can_be_a_dimension():
    bursty = {**smallest(), "load": {"rps": 20, "burst_factor": [1, 4], "burst_seconds": [1, 3], "trace_speed": 1}}
    plans = run_plans(bursty, 28)
    assert {(plan.burst_factor, plan.burst_seconds) for plan in plans} == {(1.0, 1), (1.0, 3), (4.0, 1), (4.0, 3)}


@pytest.mark.parametrize(
    "load, complaint",
    [
        ({"rps": 5, "burst_factor": 0.5}, "at least 1"),
        ({"rps": 5, "burst_factor": 2, "burst_seconds": 1.5}, "whole number"),
        ({"rps": 5, "trace_speed": 0}, "above 0"),
        ({"rps": 5, "arrival_process": "uniform"}, "arrival_process"),
        ({"rps": 5, "burst": 2}, "does not know"),
    ],
)
def test_load_that_cannot_be_made_is_refused(load, complaint):
    with pytest.raises(PlanInvalid, match=complaint):
        run_plans({**smallest(), "load": load}, 28)


def test_a_shared_knob_has_one_value_per_run_for_every_service_that_has_it():
    vision = {
        "nodes": {
            "qr": {"service": "qr-detector v1"},
            "camera": {"service": "image-compressor v1"},
            "face": {"service": "face-detector v1"},
        },
        "edges": ["qr -> camera", "camera -> face"],
        "shared_knobs": {"data_quality": {"from": 200, "to": 600, "step": 100}},
        "load": {"rps": 10},
    }
    plans = run_plans(vision, 28)
    assert len(plans) == 5
    for plan in plans:
        knobs = {node.name: node.knobs for node in plan.nodes}
        assert knobs["qr"]["data_quality"] == knobs["camera"]["data_quality"]
        assert "data_quality" not in knobs["face"]
    assert {plan.nodes[0].knobs["data_quality"] for plan in plans} == {200, 300, 400, 500, 600}


@pytest.mark.parametrize(
    "change, complaint",
    [
        ({"shared_knobs": {"data_quality": 5000}}, "shared knob data_quality, node qr"),
        ({"shared_knobs": {"sharpness": 3}}, "no service of the experiment has the shared knob"),
        ({"shared_knobs": {"data_quality": 300}, "nodes": {"qr": {"service": "qr-detector v1", "knobs": {"data_quality": 300}}}}, "sets data_quality itself"),
        ({"load": {"utilization": 0.5, "rps": 10}}, "either as utilization or as rps"),
        ({"load": {"utilization": -1}}, "at least 0"),
        ({"load": {"rps": 5, "arrival_variability": 4}}, "needs arrival_process: renewal"),
    ],
)
def test_shared_knobs_and_loads_that_cannot_work_are_refused(change, complaint):
    with pytest.raises(PlanInvalid, match=complaint):
        run_plans({**smallest(), **change}, 28)


def test_utilization_and_arrival_variability_are_load_dimensions():
    swept = {**smallest(), "load": {"utilization": [0.1, 0.5, 0.9], "arrival_process": "renewal", "arrival_variability": [0, 0.3, 1, 4]}}
    plans = run_plans(swept, 28)
    assert {(plan.utilization, plan.arrival_variability) for plan in plans} == {(u, v) for u in (0.1, 0.5, 0.9) for v in (0.0, 0.3, 1.0, 4.0)}


def test_runs_that_do_not_fit_on_the_machine_are_refused_not_silently_dropped():
    experiment = {
        "nodes": {"qr": {"service": "qr-detector v1", "cores": 20}, "face": {"service": "face-detector v1", "cores": 20}},
        "edges": ["qr -> face"],
        "load": {"rps": 10},
        "run": {"runs": 3},
    }
    with pytest.raises(PlanInvalid, match="found only 0 of 3 runs"):
        run_plans(experiment, 28)


def test_core_limits_may_add_up_to_more_than_the_machine_when_the_experiment_allows_it():
    experiment = {
        "nodes": {"qr": {"service": "qr-detector v1", "cores": 20}, "face": {"service": "face-detector v1", "cores": 20}},
        "edges": ["qr -> face"],
        "load": {"rps": 10},
        "run": {"runs": 1, "cores_may_exceed_the_machine": True},
    }
    plans = run_plans(experiment, 28)
    assert [sum(node.cores for node in plan.nodes) for plan in plans] == [40.0]


def test_cores_beyond_the_workers_gives_every_run_the_drawn_workers_plus_that_many_cores():
    experiment = {
        "nodes": {"qr": {"service": "qr-detector v1", "parallelism": [1, 2, 3, 4], "cores_beyond_the_workers": 0.5}},
        "load": {"rps": 10},
    }
    plans = run_plans(experiment, 28)
    assert sorted((plan.nodes[0].knobs["parallelism"], plan.nodes[0].cores) for plan in plans) == [(1, 1.5), (2, 2.5), (3, 3.5), (4, 4.5)]


def test_cores_beyond_the_workers_counts_towards_the_machine():
    experiment = {
        "nodes": {"qr": {"service": "qr-detector v1", "parallelism": [2, 4], "cores_beyond_the_workers": 0.5}},
        "load": {"rps": 10},
        "run": {"runs": 1},
    }
    assert [plan.nodes[0].cores for plan in run_plans(experiment, 3)] == [2.5]


def test_a_node_cannot_set_both_cores_and_cores_beyond_the_workers():
    experiment = {"nodes": {"qr": {"service": "qr-detector v1", "cores": 2, "cores_beyond_the_workers": 0.5}}, "load": {"rps": 10}}
    with pytest.raises(PlanInvalid, match="sets both cores and cores_beyond_the_workers"):
        run_plans(experiment, 28)
