import json

import pytest

from dsg.docker_host import DockerCommandFailed
from dsg.experiment.dataset import dataset_rows
from dsg.experiment.plan import PlanInvalid, run_plans
from dsg.experiment.run import PipelineRun
from dsg.load_generator.rate_pattern import RatePattern
from dsg.node import NodeSettings
from dsg.service_runtime.control_client import ServiceRefused

NODE = NodeSettings("2-15,18-31", "0-1,16-17", 18080, 18000)
SINGLE = {
    "nodes": {"qr": {"service": "qr-detector v1", "cores": 2, "parallelism": 2, "knobs": {"data_quality": 552}}},
    "load": {"rps": 40},
    "run": {"warmup_seconds": 2, "measure_seconds": 3},
}
CHAIN = {
    "nodes": {
        "qr": {"service": "qr-detector v1", "knobs": {"data_quality": 552}},
        "face": {"service": "face-detector v1", "knobs": {"model_size": 1}},
    },
    "edges": ["qr -> face"],
    "load": {"rps": 30},
    "run": {"warmup_seconds": 2, "measure_seconds": 3},
}


class FakeDocker:
    def __init__(self, not_running=(), usage_step_usec=1000000, fails_to_start=False):
        self.not_running = not_running
        self.usage_step_usec = usage_step_usec
        self.fails_to_start = fails_to_start
        self.calls = []
        self.reads = 0

    def start(self, compose_file):
        self.calls.append("start")
        if self.fails_to_start:
            raise DockerCommandFailed("port is already allocated")

    def change_cores(self, container, cores):
        self.calls.append(f"cores {container} {cores}")

    def stop(self, compose_file):
        self.calls.append("stop")

    def image_id(self, image):
        return f"sha256:{image}"

    def is_running(self, container):
        return not any(container.endswith(name) for name in self.not_running)

    def was_killed_for_memory(self, container):
        return False

    def logs(self, container):
        return "log tail"

    def read_file(self, container, path):
        self.reads += 1
        if path.endswith("memory.current"):
            return "250000000\n"
        return f"nr_periods {100 * self.reads}\nnr_throttled {10 * self.reads}\nusage_usec {self.usage_step_usec * self.reads}\n"


class FakeService:
    def __init__(self, url, journal, saturates_after_polls=None, refuses_to_start=False, processing_ms=10.0):
        self.processing_ms = processing_ms
        self.url = url
        self.journal = journal
        self.state = "idle"
        self.flags = []
        self.polls_while_measuring = 0
        self.saturates_after_polls = saturates_after_polls
        self.refuses_to_start = refuses_to_start

    def note(self, what):
        self.journal.append(f"{self.url[-5:]} {what}")

    def is_reachable(self):
        return True

    def change_knob(self, knob_name, value):
        self.note(f"knob {knob_name}={value}")

    def change_rate(self, rate):
        self.note(f"rate {rate}")

    def start_processing(self):
        if self.refuses_to_start:
            raise ServiceRefused("start_processing: 500 workers failed to start")
        self.note("start_processing")
        self.state = "warming_up"

    def start_measurement(self):
        self.note("start_measurement")
        self.state = "measuring"

    def stop_processing(self):
        self.note("stop_processing")
        self.state = "finished"

    def status(self):
        if self.state == "measuring":
            self.polls_while_measuring += 1
            if self.saturates_after_polls and self.polls_while_measuring >= self.saturates_after_polls:
                self.state = "draining"
                self.flags = ["saturated_queue"]
        return {"state": self.state, "flags": self.flags, "completed": 10, "unresolved": 0, "recent_processing_ms": self.processing_ms}


def execute(tmp_path, experiment, docker=None, **service_options):
    plan = run_plans(experiment, 28)[0]
    journal, waits, services = [], [], {}

    def service_at(url):
        options = service_options.get(url[-5:], {})
        services[url[-5:]] = FakeService(url, journal, **options)
        return services[url[-5:]]

    docker = docker or FakeDocker()
    described = PipelineRun(plan, NODE, "dsg-test", tmp_path, docker, service_at, waits.append).execute()
    return described, journal, waits, docker


def test_one_service_is_configured_started_measured_and_stopped_in_that_order(tmp_path):
    described, journal, waits, docker = execute(tmp_path, SINGLE)
    assert journal == [
        "18080 knob parallelism=2",
        "18080 knob data_quality=552",
        "18080 rate 40.0",
        "18080 start_processing",
        "18080 start_measurement",
        "18080 stop_processing",
    ]
    assert sum(waits) == 2 + 3
    assert described["valid"]
    assert docker.calls == ["start", "stop"]
    assert described["nodes"]["qr"]["image_id"] == "sha256:dsg/qr-detector:v1"
    assert described["nodes"]["qr"]["memory_bytes_under_load"] == 250000000
    assert (tmp_path / "compose.yaml").exists() and (tmp_path / "run.json").exists()


def test_in_a_chain_only_the_first_service_gets_load_and_the_last_one_starts_first(tmp_path):
    described, journal, _, _ = execute(tmp_path, CHAIN)
    assert [line for line in journal if "rate" in line] == ["18080 rate 30.0"]
    started = [line for line in journal if "start_processing" in line]
    stopped = [line for line in journal if "stop_processing" in line]
    assert started == ["18081 start_processing", "18080 start_processing"]
    assert stopped == ["18080 stop_processing", "18081 stop_processing"]
    assert described["valid"]
    assert set(described["nodes"]) == {"qr", "face"}
    compose = (tmp_path / "compose.yaml").read_text()
    assert "NEXT_HOPS: http://face:8080" in compose
    assert "LINK: rates" in compose


def test_the_link_the_file_asks_for_is_given_to_every_service(tmp_path):
    execute(tmp_path, {**CHAIN, "link": "requests"})
    assert (tmp_path / "compose.yaml").read_text().count("LINK: requests") == 2


def test_a_trace_pattern_updates_the_rate_every_second_like_elastic_workbench(tmp_path):
    bursty = {**SINGLE, "load": {"rps": 397, "pattern": "bursty"}}
    _, journal, _, _ = execute(tmp_path, bursty)
    pushed = [float(line.split("rate ")[1]) for line in journal if "rate" in line]
    trace = RatePattern("bursty", 397)
    every_second = [trace.rate_at(second) for second in range(2 + 3 + 1)]
    assert pushed == [rate for position, rate in enumerate(every_second) if position == 0 or rate != every_second[position - 1]]


def test_a_service_that_cannot_keep_up_ends_the_measurement_and_is_named_in_the_flags(tmp_path):
    described, _, waits, _ = execute(tmp_path, CHAIN, **{"18081": {"saturates_after_polls": 1}})
    assert described["flags"] == ["face:saturated_queue"]
    assert not described["valid"]
    assert sum(waits) < 2 + 3


def test_flags_a_service_wrote_in_its_summary_make_the_run_invalid(tmp_path):
    plan = run_plans(SINGLE, 28)[0]
    journal = []

    def service_that_found_itself_overloaded(url):
        service = FakeService(url, journal)
        original_stop = service.stop_processing

        def stop_and_write_summary():
            original_stop()
            (tmp_path / "qr").mkdir(exist_ok=True)
            (tmp_path / "qr" / "run_summary.json").write_text(json.dumps({"flags": ["overloaded"]}))

        service.stop_processing = stop_and_write_summary
        return service

    described = PipelineRun(plan, NODE, "dsg-test", tmp_path, FakeDocker(), service_that_found_itself_overloaded, lambda s: None).execute()
    assert described["flags"] == ["qr:overloaded"]
    assert not described["valid"]


def test_a_container_that_exits_invalidates_the_run_names_the_service_and_is_cleaned_up(tmp_path):
    docker = FakeDocker(not_running=("face",))
    described, _, _, _ = execute(tmp_path, CHAIN, docker=docker)
    assert described["problems"] == ["container_exited:face"]
    assert not described["valid"]
    assert described["container_log_tails"]["face"] == "log tail"
    assert docker.calls[-1] == "stop"


def test_a_service_that_refuses_to_start_gives_an_invalid_run_with_the_reason(tmp_path):
    described, _, _, docker = execute(tmp_path, SINGLE, **{"18080": {"refuses_to_start": True}})
    assert described["problems"] == ["service_refused"]
    assert "workers failed to start" in described["refusal"]
    assert docker.calls[-1] == "stop"


def test_dataset_has_one_row_per_service_with_the_settings_of_every_service(tmp_path):
    execute(tmp_path, CHAIN)
    for node_name, processing_ns in (("qr", 20000000), ("face", 4000000)):
        (tmp_path / node_name / "records.csv").write_text(
            "admission_phase,outcome,arrived_at_ns,started_at_ns,finished_at_ns\n"
            f"warmup,completed,0,0,900000000\n"
            f"measure,completed,0,10000000,{10000000 + processing_ns}\n"
            f"measure,completed,0,20000000,{20000000 + processing_ns}\n"
            f"measure,failed,0,0,500000000\n"
        )
        (tmp_path / node_name / "run_summary.json").write_text(
            json.dumps({"config_id": "abc", "achieved_rate_per_second": 29.5, "arrival_lateness_ms": {"p99": 0.4}})
        )
    rows = {row["node"]: row for row in dataset_rows(tmp_path)}
    assert set(rows) == {"qr", "face"}
    assert rows["qr"]["processing_mean_ms"] == 20 and rows["face"]["processing_mean_ms"] == 4
    assert rows["face"]["measured_items"] == 2
    assert rows["face"]["rate_received"] == 29.5
    assert rows["face"]["pipeline"] == "qr->face"
    assert rows["face"]["qr.data_quality"] == 552 and rows["qr"]["face.model_size"] == 1
    assert rows["qr"]["rps_on_first_service"] == 30
    assert rows["qr"]["memory_mb_under_load"] == 250.0


def test_every_source_gets_its_own_rate_and_its_own_bursts(tmp_path):
    merge = {
        "nodes": {
            "qr": {"service": "qr-detector v1", "rps": 10},
            "pc": {"service": "pc-visualizer v1"},
            "idx": {"service": "text-indexer v1"},
        },
        "edges": ["qr -> idx", "pc -> idx"],
        "load": {"rps": 40, "burst_factor": 4, "burst_seconds": 1},
        "run": {"warmup_seconds": 2, "measure_seconds": 20},
    }
    described, journal, _, _ = execute(tmp_path, merge)
    offered = described["offered_rates"]
    assert set(offered) == {"qr", "pc"}
    assert max(offered["qr"]) == 40 and max(offered["pc"]) == 160
    assert not any(line.startswith("18082 rate") for line in journal)
    rows = {row["node"]: row for row in dataset_rows(tmp_path)}
    assert rows["qr"]["burst_factor"] == 4.0
    assert rows["pc"]["offered_rate_cv"] > 0.5
    assert "offered_rate_mean" not in rows["idx"]


def test_a_utilization_becomes_the_rate_at_which_the_busiest_service_is_that_busy(tmp_path):
    chain = {
        "nodes": {
            "qr": {"service": "qr-detector v1", "cores": 2, "parallelism": 2},
            "face": {"service": "face-detector v1", "cores": 2, "parallelism": 1},
        },
        "edges": ["qr -> face"],
        "load": {"utilization": 0.5},
        "run": {"warmup_seconds": 2, "measure_seconds": 3, "probe_seconds": 4, "measure_requests": 100, "longest_measure_seconds": 20},
    }
    described, journal, waits, _ = execute(tmp_path, chain, **{"18080": {"processing_ms": 30.0}, "18081": {"processing_ms": 20.0}})
    rates = [line for line in journal if "rate" in line]
    assert rates == ["18080 rate 2.0", "18080 rate 0", "18080 rate 25.0"]
    assert journal.index("18080 start_processing") < journal.index("18080 rate 2.0")
    assert described["rate_for_the_utilization"] == 25.0
    assert described["probed_processing_ms"] == {"qr": 30.0, "face": 20.0}
    assert described["measure_seconds"] == 4
    assert sum(waits) == 4 + 2 + 4
    rows = {row["node"]: row for row in dataset_rows(tmp_path)}
    assert rows["qr"]["rps_on_first_service"] == 25.0 and rows["qr"]["utilization_asked"] == 0.5


def test_a_merging_service_carries_the_requests_of_all_sources_that_feed_it(tmp_path):
    merge = {
        "nodes": {"qr": {"service": "qr-detector v1"}, "pc": {"service": "pc-visualizer v1"}, "idx": {"service": "text-indexer v1"}},
        "edges": ["qr -> idx", "pc -> idx"],
        "load": {"utilization": 0.8},
        "run": {"warmup_seconds": 1, "measure_seconds": 1},
    }
    described, _, _, _ = execute(tmp_path, merge, **{"18082": {"processing_ms": 10.0}})
    assert described["rate_for_the_utilization"] == 0.8 / (2 * 0.010)


AUTO_CORES = {
    "nodes": {"qr": {"service": "qr-detector v1", "cores": 4, "parallelism": 2}},
    "load": {"utilization": 0.5},
    "run": {"warmup_seconds": 1, "measure_seconds": 1, "probe_seconds": 2, "cpu_slack": 1.15},
}


def test_cpu_slack_sets_the_cores_the_workers_used_while_busy_times_the_slack(tmp_path):
    docker = FakeDocker(usage_step_usec=50000)
    described, _, _, _ = execute(tmp_path, AUTO_CORES, docker=docker, **{"18080": {"processing_ms": 10.0}})
    assert described["cpu_per_busy_worker"] == {"qr": pytest.approx(0.5)}
    assert described["cores_set"] == {"qr": 1.15}
    assert "cores dsg-test-qr 1.15" in docker.calls
    assert described["settings"]["qr.cores"] == 1.15 and described["settings"]["qr.probe_cores"] == 4
    assert described["rate_for_the_utilization"] == pytest.approx(0.5 / (0.010 / 2))
    assert described["valid"]
    (tmp_path / "qr" / "records.csv").write_text(
        "admission_phase,outcome,arrived_at_ns,started_at_ns,finished_at_ns\nmeasure,completed,0,0,10000000\n"
    )
    (tmp_path / "qr" / "run_summary.json").write_text(json.dumps({"config_id": "abc", "achieved_rate_per_second": 100, "arrival_lateness_ms": {"p99": 0.1}}))
    rows = dataset_rows(tmp_path)
    assert rows[0]["qr.cores"] == 1.15
    assert rows[0]["utilization_measured"] == pytest.approx(0.5)


def test_a_service_that_needs_more_cores_than_the_probe_had_gives_an_invalid_run(tmp_path):
    described, journal, _, docker = execute(tmp_path, AUTO_CORES, docker=FakeDocker(usage_step_usec=1000000))
    assert described["problems"] == ["cores_needed_above_the_probe_cores:qr"]
    assert not described["valid"]
    assert not any(call.startswith("cores") for call in docker.calls)
    assert "18080 start_measurement" not in journal


def test_cpu_slack_below_one_or_without_a_utilization_is_refused():
    with pytest.raises(PlanInvalid, match="at least 1"):
        run_plans({**AUTO_CORES, "run": {**AUTO_CORES["run"], "cpu_slack": 0.9}}, 28)
    with pytest.raises(PlanInvalid, match="needs load"):
        run_plans({**AUTO_CORES, "load": {"rps": 10}}, 28)


def test_a_compose_start_that_fails_halfway_is_still_taken_down(tmp_path):
    docker = FakeDocker(fails_to_start=True)
    with pytest.raises(DockerCommandFailed):
        execute(tmp_path, SINGLE, docker=docker)
    assert docker.calls == ["start", "stop"]


TREE = {
    "nodes": {
        "camera": {"service": "qr-detector v1"},
        "left": {"service": "face-detector v1"},
        "right": {"service": "pc-visualizer v1"},
        "merge": {"service": "text-indexer v1"},
    },
    "edges": ["camera -> left", "camera -> right", "left -> merge", "right -> merge"],
    "link": "requests",
    "fan_in": "join",
    "load": {"utilization": 0.5},
    "run": {"warmup_seconds": 1, "measure_seconds": 1},
}


def test_a_join_waits_for_every_feeder_and_carries_one_stream_not_one_per_path(tmp_path):
    described, _, _, _ = execute(tmp_path, TREE, **{"18083": {"processing_ms": 20.0}})
    assert described["rate_for_the_utilization"] == pytest.approx(0.5 / 0.020)
    compose = (tmp_path / "compose.yaml").read_text()
    assert compose.count("JOIN_INPUTS: '2'") == 1 and compose.count("JOIN_INPUTS: '1'") == 3


def test_without_a_join_the_merging_service_counts_every_path(tmp_path):
    described, _, _, _ = execute(tmp_path, {**TREE, "fan_in": "each"}, **{"18083": {"processing_ms": 20.0}})
    assert described["rate_for_the_utilization"] == pytest.approx(0.5 / (2 * 0.020))


def test_a_join_needs_requests_and_fan_in_is_join_or_each():
    with pytest.raises(PlanInvalid, match="needs link: requests"):
        run_plans({**TREE, "link": "rates"}, 28)
    with pytest.raises(PlanInvalid, match="fan_in must be one of"):
        run_plans({**TREE, "fan_in": "merge"}, 28)


def test_cores_set_that_add_up_to_more_than_the_machine_give_an_invalid_run(tmp_path):
    tree = {**TREE, "nodes": {name: {**node, "cores": 10} for name, node in TREE["nodes"].items()}, "run": {**TREE["run"], "cpu_slack": 1.15}}
    plan = run_plans(tree, 40)[0]
    journal = []
    docker = FakeDocker(usage_step_usec=162500)
    described = PipelineRun(plan, NODE, "dsg-test", tmp_path, docker, lambda url: FakeService(url, journal), lambda s: None).execute()
    assert sum(described["cores_set"].values()) > 28
    assert described["problems"] == ["cores_set_above_the_workload_cpus"]
    assert not any("start_measurement" in line for line in journal)


def test_a_node_without_auto_cores_keeps_its_cores_while_the_others_get_theirs(tmp_path):
    tree = {**TREE, "run": {**TREE["run"], "cpu_slack": 1.15}}
    tree["nodes"] = {name: {**node, "cores": 4} for name, node in TREE["nodes"].items()}
    tree["nodes"]["camera"] = {**tree["nodes"]["camera"], "cores": 1, "auto_cores": False}
    described, _, _, docker = execute(tmp_path, tree, docker=FakeDocker(usage_step_usec=10000))
    assert "camera" not in described["cores_set"] and set(described["cores_set"]) == {"left", "right", "merge"}
    assert not any("camera" in call for call in docker.calls if call.startswith("cores"))
    assert described["valid"]


def test_with_the_cap_a_service_that_needs_more_than_its_probe_cores_gets_them_and_is_listed(tmp_path):
    capped = {**AUTO_CORES, "run": {**AUTO_CORES["run"], "cap_cores_at_the_probe": True}}
    described, journal, _, docker = execute(tmp_path, capped, docker=FakeDocker(usage_step_usec=1000000))
    assert described["cores_capped"] == ["qr"] and described["cores_set"] == {"qr": 4.0}
    assert "cores dsg-test-qr 4.0" in docker.calls
    assert described["valid"] and "18080 start_measurement" in journal
