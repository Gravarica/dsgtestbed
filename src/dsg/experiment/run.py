from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
import math
from typing import Any, Callable, Dict, List, Optional

from dsg.experiment.plan import JOIN, NodePlan, RunPlan
from dsg.load_generator.rate_pattern import Bursts, RatePattern, RateSetter
from dsg.monitor.container_stats import cpu_stat_from_text
from dsg.node import NodeSettings
from dsg.service_composer.compose import (
    NodeDeployment,
    compose_for_pipeline,
    container_name,
    control_url_on_the_host,
    records_directory_of,
    write_compose_file,
)
from dsg.service_generator.catalog import image_name
from dsg.service_runtime.control_client import ServiceRefused

SECONDS_TO_BECOME_REACHABLE = 120
SECONDS_TO_DRAIN = 300
SECONDS_TO_FINISH_THE_PROBE = 180
PROBE_RATE_PER_SECOND = 2.0
POLL_SECONDS = 1.0
CORES_STEP = 0.05
FEWEST_CORES = 0.1
CPU_STAT_FILE = "/sys/fs/cgroup/cpu.stat"
MEMORY_IN_USE_FILE = "/sys/fs/cgroup/memory.current"
STATES_THAT_ACCEPT_ARRIVALS = ("warming_up", "measuring")


class PipelineRun:
    def __init__(
        self,
        plan: RunPlan,
        node_settings: NodeSettings,
        project: str,
        run_directory: Path,
        docker,
        service_at: Callable[[str], Any],
        wait: Callable[[float], None],
        without_network: bool = False,
    ):
        self._plan = plan
        self._node_settings = node_settings
        self._project = project
        self._run_directory = Path(run_directory)
        self._docker = docker
        self._wait = wait
        self._without_network = without_network
        self._topology = plan.topology()
        self._order = self._topology.from_first_to_last()
        self._services = {
            node.name: service_at(control_url_on_the_host(node_settings, position))
            for position, node in enumerate(plan.nodes)
        }
        self._compose_file = self._run_directory / "compose.yaml"
        self._problems: List[str] = []
        self._refusal = ""
        self._seconds_under_load = 0.0
        self._cpu_stat: Dict[str, Dict[str, Dict[str, int]]] = {node.name: {} for node in plan.nodes}
        self._memory_bytes_under_load: Dict[str, int] = {}
        self._rate_setters: Dict[str, RateSetter] = {}
        self._probed_processing_ms: Dict[str, float] = {}
        self._rate_for_the_utilization: Optional[float] = None
        self._measure_seconds = plan.measure_seconds
        self._cores_set: Dict[str, float] = {}
        self._cpu_per_busy_worker: Dict[str, float] = {}
        self._cores_capped: List[str] = []

    def _rate_of(self, source: str) -> float:
        return self._plan.rate_of(source) if self._rate_for_the_utilization is None else self._rate_for_the_utilization

    def _pattern_for(self, source: str, position: int) -> RatePattern:
        plan = self._plan
        bursts = None if plan.burst_factor == 1 else Bursts(plan.burst_factor, plan.burst_seconds, seed=plan.arrival_seed * 100 + position)
        return RatePattern(plan.load_pattern, self._rate_of(source), plan.pattern_start_second, plan.trace_speed, bursts)

    def _set_up_the_load(self) -> None:
        self._rate_setters = {
            source: RateSetter(self._pattern_for(source, position), self._services[source].change_rate)
            for position, source in enumerate(self._topology.sources())
        }
        requests_per_second = sum(self._rate_of(source) for source in self._topology.sources())
        if self._plan.measure_requests and requests_per_second > 0:
            wanted_seconds = math.ceil(self._plan.measure_requests / requests_per_second)
            self._measure_seconds = min(max(wanted_seconds, self._plan.measure_seconds), self._plan.longest_measure_seconds)

    def _sources_feeding(self, node_name: str) -> int:
        feeders = self._topology.feeders_of(node_name)
        if not feeders:
            return 1
        streams = [self._sources_feeding(feeder) for feeder in feeders]
        return max(streams) if self._plan.fan_in == JOIN else sum(streams)

    def _inputs_joined_by(self, node_name: str) -> int:
        return max(1, len(self._topology.feeders_of(node_name))) if self._plan.fan_in == JOIN else 1

    def _probe_the_services_for_the_utilization(self) -> None:
        sources = self._topology.sources()
        cpu_before = self._cpu_usage_seconds()
        for source in sources:
            self._services[source].change_rate(PROBE_RATE_PER_SECOND)
        self._wait(self._plan.probe_seconds)
        for source in sources:
            self._services[source].change_rate(0)
        if not self._becomes_true(self._every_service_finished_what_it_received, SECONDS_TO_FINISH_THE_PROBE):
            self._problems.append("probe_not_finished")
            return
        cpu_after = self._cpu_usage_seconds()
        seconds_of_work_per_request_and_core = []
        for node in self._plan.nodes:
            status = self._services[node.name].status()
            processing_ms = status["recent_processing_ms"]
            self._probed_processing_ms[node.name] = processing_ms
            workers = float(node.knobs.get("parallelism", 1))
            servers = min(workers, node.cores)
            if self._plan.cpu_slack and node.auto_cores:
                busy_seconds = status["completed"] * processing_ms / 1000
                self._cpu_per_busy_worker[node.name] = (cpu_after[node.name] - cpu_before[node.name]) / busy_seconds
                self._set_the_cores_the_workers_need(node, workers)
                servers = workers
            seconds_of_work_per_request_and_core.append(self._sources_feeding(node.name) * processing_ms / 1000 / servers)
        if self._problems:
            return
        if self._plan.cpu_slack and sum(self._cores_set.values()) > self._node_settings.workload_cpu_count():
            self._problems.append("cores_set_above_the_workload_cpus")
            return
        self._rate_for_the_utilization = self._plan.utilization / max(seconds_of_work_per_request_and_core)

    def _cpu_usage_seconds(self) -> Dict[str, float]:
        return {
            node.name: cpu_stat_from_text(self._docker.read_file(container_name(self._project, node.name), CPU_STAT_FILE)).get("usage_usec", 0) / 1e6
            for node in self._plan.nodes
        }

    def _set_the_cores_the_workers_need(self, node: NodePlan, workers: float) -> None:
        needed = self._plan.cpu_slack * workers * self._cpu_per_busy_worker[node.name]
        cores = max(FEWEST_CORES, math.ceil(needed / CORES_STEP - 1e-9) * CORES_STEP)
        if cores > node.cores and self._plan.cap_cores_at_the_probe:
            self._cores_capped.append(node.name)
            cores = node.cores
        if cores > node.cores:
            self._problems.append(f"cores_needed_above_the_probe_cores:{node.name}")
            return
        self._docker.change_cores(container_name(self._project, node.name), round(cores, 2))
        self._cores_set[node.name] = round(cores, 2)

    def _every_service_finished_what_it_received(self) -> bool:
        statuses = [service.status() for service in self._services.values()]
        return all(status["completed"] > 0 and status["unresolved"] == 0 for status in statuses)

    def execute(self) -> Dict[str, Any]:
        for node in self._plan.nodes:
            records_directory_of(self._run_directory, node.name).mkdir(parents=True, exist_ok=True)
        compose = compose_for_pipeline(
            [self._deployment_of(node) for node in self._plan.nodes],
            self._node_settings,
            self._project,
            self._run_directory,
            f"{os.getuid()}:{os.getgid()}",
            self._without_network,
        )
        write_compose_file(self._compose_file, compose)
        try:
            self._docker.start(self._compose_file)
            self._drive_the_services_and_note_a_refusal()
            described = self._described_run()
        finally:
            self._docker.stop(self._compose_file)
        (self._run_directory / "run.json").write_text(json.dumps(described, indent=2))
        return described

    def _deployment_of(self, node: NodePlan) -> NodeDeployment:
        return NodeDeployment(
            name=node.name,
            image=image_name(node.service, node.version),
            cores=node.cores,
            memory_limit=node.memory,
            next_hops=self._topology.next_hops_of(node.name),
            environment={
                "QUEUE_CAPACITY": str(self._plan.queue_capacity),
                "ARRIVAL_PROCESS": self._plan.arrival_process,
                "ARRIVAL_SEED": str(self._plan.arrival_seed),
                "ARRIVAL_VARIABILITY": str(self._plan.arrival_variability),
                "LINK": self._plan.link,
                "JOIN_INPUTS": str(self._inputs_joined_by(node.name)),
            },
        )

    def _drive_the_services_and_note_a_refusal(self) -> None:
        try:
            self._drive_the_services()
        except ServiceRefused as refusal:
            self._problems.append("service_refused")
            self._refusal = str(refusal)

    def _drive_the_services(self) -> None:
        if not self._becomes_true(self._every_service_is_reachable, SECONDS_TO_BECOME_REACHABLE):
            self._problems.append("service_unreachable")
            return
        for node in self._plan.nodes:
            for knob_name, value in node.knobs.items():
                self._services[node.name].change_knob(knob_name, value)
        if self._plan.utilization > 0:
            for node_name in reversed(self._order):
                self._services[node_name].start_processing()
            self._probe_the_services_for_the_utilization()
            if self._problems:
                return
            self._set_up_the_load()
            self._apply_the_load(0)
        else:
            self._set_up_the_load()
            self._apply_the_load(0)
            for node_name in reversed(self._order):
                self._services[node_name].start_processing()
        self._stay_under_load(self._plan.warmup_seconds)
        self._read_container_counters("before")
        if not self._problems:
            for node_name in self._order:
                self._services[node_name].start_measurement()
            self._stay_under_load(self._measure_seconds)
        self._read_container_counters("after")
        if any(problem.startswith("container_exited") for problem in self._problems):
            return
        for node_name in self._order:
            self._services[node_name].stop_processing()
            finished = lambda name=node_name: self._services[name].status()["state"] == "finished"
            if not self._becomes_true(finished, SECONDS_TO_DRAIN):
                self._problems.append(f"drain_not_finished:{node_name}")

    def _every_service_is_reachable(self) -> bool:
        return all(service.is_reachable() for service in self._services.values())

    def _apply_the_load(self, elapsed_seconds: float) -> None:
        for rate_setter in self._rate_setters.values():
            rate_setter.apply(elapsed_seconds)

    def _stay_under_load(self, seconds: float) -> None:
        waited = 0.0
        while waited < seconds:
            self._wait(POLL_SECONDS)
            waited += POLL_SECONDS
            self._seconds_under_load += POLL_SECONDS
            for node in self._plan.nodes:
                if not self._docker.is_running(container_name(self._project, node.name)):
                    self._problems.append(f"container_exited:{node.name}")
                    return
            if any(service.status()["state"] not in STATES_THAT_ACCEPT_ARRIVALS for service in self._services.values()):
                return
            self._apply_the_load(self._seconds_under_load)

    def _read_container_counters(self, moment: str) -> None:
        for node in self._plan.nodes:
            container = container_name(self._project, node.name)
            self._cpu_stat[node.name][moment] = cpu_stat_from_text(self._docker.read_file(container, CPU_STAT_FILE))
            memory_text = self._docker.read_file(container, MEMORY_IN_USE_FILE).strip()
            self._memory_bytes_under_load[node.name] = int(memory_text) if memory_text.isdigit() else 0

    def _becomes_true(self, condition: Callable[[], bool], within_seconds: float) -> bool:
        waited = 0.0
        while waited < within_seconds:
            if condition():
                return True
            self._wait(POLL_SECONDS)
            waited += POLL_SECONDS
        return condition()

    def _described_run(self) -> Dict[str, Any]:
        nodes = {node.name: self._described_node(node) for node in self._plan.nodes}
        flags = [f"{name}:{flag}" for name, described in nodes.items() for flag in self._flags_of(name, described)]
        settings = self._plan.settings_by_node()
        for node_name, cores in self._cores_set.items():
            settings[f"{node_name}.probe_cores"] = settings[f"{node_name}.cores"]
            settings[f"{node_name}.cores"] = cores
        described = {
            "plan": asdict(self._plan),
            "settings": settings,
            "project": self._project,
            "workload_cpuset": self._node_settings.workload_cpuset,
            "without_network": self._without_network,
            "problems": self._problems,
            "flags": flags,
            "valid": not self._problems and not flags,
            "nodes": nodes,
            "host_load_average": list(os.getloadavg()),
            "offered_rates": {source: setter.offered_rates for source, setter in self._rate_setters.items()},
            "measure_seconds": self._measure_seconds,
            "rate_for_the_utilization": self._rate_for_the_utilization,
            "probed_processing_ms": self._probed_processing_ms,
            "cpu_per_busy_worker": self._cpu_per_busy_worker,
            "cores_set": self._cores_set,
            "cores_capped": self._cores_capped,
        }
        if self._problems:
            described["refusal"] = self._refusal
            described["container_log_tails"] = {
                node.name: self._docker.logs(container_name(self._project, node.name)) for node in self._plan.nodes
            }
        return described

    def _flags_of(self, node_name: str, described: Dict[str, Any]) -> List[str]:
        flags = list(described["service_status"].get("flags", []))
        summary_file = records_directory_of(self._run_directory, node_name) / "run_summary.json"
        if summary_file.exists():
            for flag in json.loads(summary_file.read_text()).get("flags", []):
                if flag not in flags:
                    flags.append(flag)
        return flags

    def _described_node(self, node: NodePlan) -> Dict[str, Any]:
        container = container_name(self._project, node.name)
        if self._docker.was_killed_for_memory(container):
            self._problems.append(f"killed_for_memory:{node.name}")
        gone = "service_unreachable" in self._problems or f"container_exited:{node.name}" in self._problems
        return {
            "service": f"{node.service}:{node.version}",
            "image_id": self._docker.image_id(image_name(node.service, node.version)),
            "service_status": {} if gone else self._services[node.name].status(),
            "cpu_stat": self._cpu_stat[node.name],
            "memory_bytes_under_load": self._memory_bytes_under_load.get(node.name, 0),
        }
