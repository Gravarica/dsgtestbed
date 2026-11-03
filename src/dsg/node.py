from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import yaml

CPUS_KEPT_FOR_THE_TESTBED = 2
FEWEST_CPUS_FOR_SERVICES = 2
DEFAULT_PORTS = {"control_port": 18080, "metrics_port": 18000, "prometheus_port": 19090, "cadvisor_port": 18090, "grafana_port": 13000}


class MachineNotReady(Exception):
    pass


@dataclass(frozen=True)
class NodeSettings:
    workload_cpuset: str
    infrastructure_cpuset: str
    control_port: int
    metrics_port: int
    prometheus_port: int = DEFAULT_PORTS["prometheus_port"]
    cadvisor_port: int = DEFAULT_PORTS["cadvisor_port"]
    grafana_port: int = DEFAULT_PORTS["grafana_port"]

    def workload_cpu_count(self) -> int:
        return len(cpus_in_set(self.workload_cpuset))

    def infrastructure_cpus(self) -> List[int]:
        return cpus_in_set(self.infrastructure_cpuset)


def cpus_in_set(cpuset: str) -> List[int]:
    cpus = []
    for part in cpuset.split(","):
        first, _, last = part.partition("-")
        cpus.extend(range(int(first), int(last or first) + 1))
    return cpus


def cpuset_of(cpus: List[int]) -> str:
    ranges, start, previous = [], None, None
    for cpu in sorted(cpus) + [None]:
        if start is None:
            start = previous = cpu
        elif cpu is not None and cpu == previous + 1:
            previous = cpu
        else:
            ranges.append(f"{start}-{previous}" if start != previous else str(start))
            start = previous = cpu
    return ",".join(ranges)


def load_node_settings(path: Path) -> NodeSettings:
    return NodeSettings(**yaml.safe_load(Path(path).read_text()))


def siblings_of(cpu: int, sysfs: Path = Path("/sys/devices/system/cpu")) -> List[int]:
    siblings_file = sysfs / f"cpu{cpu}" / "topology" / "thread_siblings_list"
    return cpus_in_set(siblings_file.read_text().strip()) if siblings_file.exists() else [cpu]


def node_settings_for_this_machine(cpu_count: int, siblings_of_cpu=siblings_of) -> NodeSettings:
    if cpu_count < CPUS_KEPT_FOR_THE_TESTBED + FEWEST_CPUS_FOR_SERVICES:
        raise MachineNotReady(f"this machine has {cpu_count} CPUs; the testbed needs at least {CPUS_KEPT_FOR_THE_TESTBED + FEWEST_CPUS_FOR_SERVICES}")
    kept: List[int] = []
    for cpu in range(cpu_count):
        if len({core for core in kept if core == min(siblings_of_cpu(core))}) >= CPUS_KEPT_FOR_THE_TESTBED:
            break
        if cpu not in kept:
            kept.extend(sibling for sibling in siblings_of_cpu(cpu) if sibling < cpu_count)
    if cpu_count - len(kept) < FEWEST_CPUS_FOR_SERVICES:
        kept = list(range(CPUS_KEPT_FOR_THE_TESTBED))
    services = [cpu for cpu in range(cpu_count) if cpu not in kept]
    return NodeSettings(cpuset_of(services), cpuset_of(kept), **DEFAULT_PORTS)


def write_node_settings(path: Path, settings: NodeSettings) -> None:
    Path(path).write_text(yaml.safe_dump(settings.__dict__, sort_keys=False))


def problems_with_this_machine() -> List[str]:
    problems = []
    if not shutil.which("docker"):
        problems.append("docker is not installed")
    else:
        answer = subprocess.run(["docker", "info"], capture_output=True, text=True)
        if answer.returncode != 0:
            problems.append("docker does not answer; is the daemon running and are you allowed to use it?")
        compose = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
        if compose.returncode != 0:
            problems.append("docker compose v2 is not installed")
    if not Path("/sys/fs/cgroup/cgroup.controllers").exists():
        problems.append("this machine does not use cgroup v2; the testbed reads CPU and memory counters from it")
    return problems
