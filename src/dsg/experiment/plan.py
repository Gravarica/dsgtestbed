from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from dsg.load_generator.arrival_schedule import ARRIVAL_PROCESSES
from dsg.load_generator.rate_pattern import CONSTANT, Bursts, BurstsImpossible, available_patterns
from dsg.service_composer.topology import Topology, TopologyInvalid, topology_of
from dsg.service_generator.catalog import ServiceMissing, service_directory
from dsg.service_runtime.contract import HARNESS_KNOBS, KnobValueRejected, load_service_spec

RESOURCE_SETTINGS = ("cores", "memory")
SOURCE_RATE = "rps"
CORES_BEYOND = "cores_beyond_the_workers"
NODE_SETTINGS_THAT_ARE_NOT_KNOBS = (*RESOURCE_SETTINGS, SOURCE_RATE, CORES_BEYOND)
AUTO_CORES = "auto_cores"
NODE_KEYS = ("service", "knobs", AUTO_CORES, *NODE_SETTINGS_THAT_ARE_NOT_KNOBS, *HARNESS_KNOBS)
DEFAULT_MEMORY = "8g"
LINK_KINDS = ("rates", "requests")
EACH = "each"
JOIN = "join"
FAN_IN_KINDS = (EACH, JOIN)
CORES_BEYOND_THE_WORKERS = 1
LOAD_DEFAULTS = {
    "rps": 0,
    "pattern": CONSTANT,
    "pattern_start_second": 0,
    "trace_speed": 1,
    "burst_factor": 1,
    "burst_seconds": 1,
    "arrival_process": "poisson",
    "arrival_variability": 1,
    "utilization": 0,
}
MOST_COMBINATIONS_TO_LIST = 200_000
DRAWS_PER_WANTED_RUN = 1000

Dimension = Tuple[str, str]
LOAD = "load"
SHARED = "shared"
SETTINGS_OF_THE_WHOLE_RUN = (LOAD, SHARED)


class PlanInvalid(Exception):
    pass


@dataclass(frozen=True)
class NodePlan:
    name: str
    service: str
    version: str
    cores: float
    memory: str
    knobs: Dict[str, Any]
    rps: Optional[float] = None
    auto_cores: bool = True


@dataclass(frozen=True)
class RunPlan:
    run_id: str
    nodes: Tuple[NodePlan, ...]
    edges: Tuple[Tuple[str, str], ...]
    link: str
    rps: float
    repetition: int
    warmup_seconds: float
    measure_seconds: float
    queue_capacity: int
    arrival_process: str
    arrival_seed: int
    load_pattern: str
    pattern_start_second: int
    trace_speed: float = 1.0
    burst_factor: float = 1.0
    burst_seconds: int = 1
    arrival_variability: float = 1.0
    utilization: float = 0.0
    probe_seconds: float = 5.0
    measure_requests: int = 0
    longest_measure_seconds: float = 0.0
    cpu_slack: float = 0.0
    fan_in: str = EACH
    cap_cores_at_the_probe: bool = False

    def topology(self) -> Topology:
        return topology_of([node.name for node in self.nodes], self.edges)

    def rate_of(self, source: str) -> float:
        own = next(node.rps for node in self.nodes if node.name == source)
        return self.rps if own is None else own

    def settings_by_node(self) -> Dict[str, Any]:
        settings = {}
        for node in self.nodes:
            settings[f"{node.name}.service"] = f"{node.service}:{node.version}"
            settings[f"{node.name}.cores"] = node.cores
            settings[f"{node.name}.memory"] = node.memory
            if node.rps is not None:
                settings[f"{node.name}.rps"] = node.rps
            settings.update({f"{node.name}.{knob}": value for knob, value in node.knobs.items()})
        return settings


def load_experiment(experiment_file: Path) -> Dict[str, Any]:
    return yaml.safe_load(Path(experiment_file).read_text())


def as_list(value: Any) -> List[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return values_of_range(value)
    return [value]


def values_of_range(written: Dict[str, Any]) -> List[Any]:
    if set(written) - {"from", "to", "step"} or not {"from", "to"} <= set(written):
        raise PlanInvalid(f"a range is written as {{from: 1, to: 4, step: 0.5}} (step 1 when left out), not {written}")
    first, last, step = written["from"], written["to"], written.get("step", 1)
    if step <= 0 or last < first:
        raise PlanInvalid(f"a range needs from <= to and a step above 0, not {written}")
    count = math.floor((last - first) / step + 1e-9) + 1
    whole_numbers = all(isinstance(number, int) for number in (first, step))
    return [first + index * step if whole_numbers else round(first + index * step, 6) for index in range(count)]


def service_and_version(text: str) -> Tuple[str, str]:
    parts = str(text).split()
    if len(parts) != 2:
        raise PlanInvalid(f"a service is written as 'name version', for example 'qr-detector v1', not {text!r}")
    return parts[0], parts[1]


def values_to_try(experiment: Dict[str, Any]) -> Dict[Dimension, List[Any]]:
    load = experiment.get("load") or {}
    unknown_load = [key for key in load if key not in LOAD_DEFAULTS]
    if unknown_load:
        raise PlanInvalid(f"load has settings the testbed does not know: {unknown_load}. It knows {list(LOAD_DEFAULTS)}")
    tried: Dict[Dimension, List[Any]] = {(LOAD, key): as_list(load.get(key, default)) for key, default in LOAD_DEFAULTS.items()}
    for knob_name, values in (experiment.get("shared_knobs") or {}).items():
        tried[(SHARED, knob_name)] = as_list(values)
    for node_name, node in experiment["nodes"].items():
        unknown = [key for key in node if key not in NODE_KEYS]
        if unknown:
            raise PlanInvalid(f"node {node_name} has settings the testbed does not know: {unknown}. Service knobs go under 'knobs:'")
        workers = as_list(node.get("parallelism", 1))
        tried[(node_name, "parallelism")] = workers
        if CORES_BEYOND in node:
            if "cores" in node:
                raise PlanInvalid(f"node {node_name} sets both cores and {CORES_BEYOND}; set one")
            tried[(node_name, CORES_BEYOND)] = as_list(node[CORES_BEYOND])
        else:
            tried[(node_name, "cores")] = as_list(node.get("cores", max(workers) + CORES_BEYOND_THE_WORKERS))
        tried[(node_name, "memory")] = as_list(node.get("memory", DEFAULT_MEMORY))
        if SOURCE_RATE in node:
            tried[(node_name, SOURCE_RATE)] = as_list(node[SOURCE_RATE])
        for harness_knob in HARNESS_KNOBS:
            if harness_knob in node and harness_knob != "parallelism":
                tried[(node_name, harness_knob)] = as_list(node[harness_knob])
        for knob_name, values in (node.get("knobs") or {}).items():
            tried[(node_name, knob_name)] = as_list(values)
    return tried


def combinations_of(tried: Dict[Dimension, List[Any]]) -> List[Dict[Dimension, Any]]:
    dimensions = list(tried)
    return [dict(zip(dimensions, values)) for values in itertools.product(*(tried[dimension] for dimension in dimensions))]


def size_of_space(tried: Dict[Dimension, List[Any]]) -> int:
    return math.prod(len(values) for values in tried.values())


def cores_asked_by(combination: Dict[Dimension, Any]) -> float:
    total = 0.0
    for (owner, setting), value in combination.items():
        if owner in SETTINGS_OF_THE_WHOLE_RUN:
            continue
        if setting == "cores":
            total += float(value)
        elif setting == CORES_BEYOND:
            total += float(combination[(owner, "parallelism")]) + float(value)
    return total


def chosen_combinations(
    experiment: Dict[str, Any], tried: Dict[Dimension, List[Any]], fits: Callable[[Dict[Dimension, Any]], bool]
) -> List[Dict[Dimension, Any]]:
    run_settings = experiment.get("run") or {}
    randomness = random.Random(run_settings.get("seed", 0))
    size = size_of_space(tried)
    if "runs" not in run_settings:
        if size > MOST_COMBINATIONS_TO_LIST:
            raise PlanInvalid(f"the space has {size} combinations; say how many to run with run: {{runs: N}}")
        combinations = combinations_of(tried)
        randomness.shuffle(combinations)
        return combinations
    wanted = int(run_settings["runs"])
    if size <= MOST_COMBINATIONS_TO_LIST:
        combinations = combinations_of(tried)
        randomness.shuffle(combinations)
        fitting = [combination for combination in combinations if fits(combination)][:wanted]
        if len(fitting) < wanted:
            raise PlanInvalid(f"found only {len(fitting)} of {wanted} runs that fit on the machine; allow fewer cores")
        return fitting
    return drawn_combinations(tried, wanted, randomness, fits)


def drawn_combinations(
    tried: Dict[Dimension, List[Any]], wanted: int, randomness: random.Random, fits: Callable[[Dict[Dimension, Any]], bool]
) -> List[Dict[Dimension, Any]]:
    chosen: List[Dict[Dimension, Any]] = []
    seen = set()
    for _ in range(wanted * DRAWS_PER_WANTED_RUN):
        if len(chosen) == wanted:
            break
        combination = {dimension: randomness.choice(values) for dimension, values in tried.items()}
        identity = tuple(combination.values())
        if identity in seen or not fits(combination):
            continue
        seen.add(identity)
        chosen.append(combination)
    if len(chosen) < wanted:
        raise PlanInvalid(f"found only {len(chosen)} of {wanted} runs that fit on the machine; allow fewer cores")
    return chosen


def with_repetitions(chosen: List[Dict[Dimension, Any]], run_settings: Dict[str, Any]) -> List[Tuple[Dict[Dimension, Any], int]]:
    repetitions = int(run_settings.get("repetitions", 1))
    repeated_share = float(run_settings.get("repeated_share", 1.0))
    if not 0 <= repeated_share <= 1:
        raise PlanInvalid(f"repeated_share is the share of runs that are repeated, from 0 to 1, not {repeated_share}")
    repeated_count = math.ceil(repeated_share * len(chosen))
    return [
        (combination, repetition)
        for position, combination in enumerate(chosen)
        for repetition in range(repetitions if position < repeated_count else 1)
    ]


def run_plans(experiment: Dict[str, Any], workload_cpu_count: int) -> List[RunPlan]:
    if not experiment.get("nodes"):
        raise PlanInvalid("the experiment has no 'nodes:'")
    try:
        topology = topology_of(experiment["nodes"], experiment.get("edges") or [])
    except TopologyInvalid as problem:
        raise PlanInvalid(str(problem))
    if experiment.get("link", LINK_KINDS[0]) not in LINK_KINDS:
        raise PlanInvalid(f"link must be one of {list(LINK_KINDS)}, not {experiment['link']!r}")
    refuse_fan_in_that_cannot_be_made(experiment)
    run_settings = experiment.get("run") or {}
    tried = values_to_try(experiment)
    refuse_load_that_cannot_be_made(tried)
    refuse_shared_knobs_that_cannot_be_shared(experiment, tried)
    refuse_source_rates_on_other_nodes(experiment, topology)
    refuse_values_outside_the_specs(experiment, tried)
    refuse_cpu_slack_that_cannot_be_set(run_settings, tried)
    cores_may_exceed_the_machine = bool(run_settings.get("cores_may_exceed_the_machine", False))
    fits = lambda combination: cores_may_exceed_the_machine or cores_asked_by(combination) <= workload_cpu_count
    runs = with_repetitions(chosen_combinations(experiment, tried, fits), run_settings)
    random.Random(run_settings.get("seed", 0)).shuffle(runs)
    plans = [run_plan(experiment, topology, combination, repetition, position) for position, (combination, repetition) in enumerate(runs)]
    if not cores_may_exceed_the_machine:
        refuse_plans_that_do_not_fit(plans, workload_cpu_count)
    return plans


def run_plan(
    experiment: Dict[str, Any], topology: Topology, combination: Dict[Dimension, Any], repetition: int, position: int
) -> RunPlan:
    run_settings = experiment.get("run") or {}
    load = {setting: value for (owner, setting), value in combination.items() if owner == LOAD}
    return RunPlan(
        run_id=f"run-{position:04d}",
        nodes=tuple(node_plan(name, experiment["nodes"][name], combination) for name in topology.node_names),
        edges=topology.edges,
        link=experiment.get("link", LINK_KINDS[0]),
        rps=float(load["rps"]),
        repetition=repetition,
        warmup_seconds=float(run_settings.get("warmup_seconds", 10)),
        measure_seconds=float(run_settings.get("measure_seconds", 60)),
        queue_capacity=int(run_settings.get("queue_capacity", 10000)),
        arrival_process=load["arrival_process"],
        arrival_seed=int(run_settings.get("seed", 0)) + position,
        load_pattern=load["pattern"],
        pattern_start_second=int(load["pattern_start_second"]),
        trace_speed=float(load["trace_speed"]),
        burst_factor=float(load["burst_factor"]),
        burst_seconds=int(load["burst_seconds"]),
        arrival_variability=float(load["arrival_variability"]),
        utilization=float(load["utilization"]),
        probe_seconds=float(run_settings.get("probe_seconds", 5)),
        measure_requests=int(run_settings.get("measure_requests", 0)),
        longest_measure_seconds=float(run_settings.get("longest_measure_seconds", run_settings.get("measure_seconds", 60))),
        cpu_slack=float(run_settings.get("cpu_slack", 0)),
        fan_in=experiment.get("fan_in", EACH),
        cap_cores_at_the_probe=bool(run_settings.get("cap_cores_at_the_probe", False)),
    )


def node_plan(node_name: str, node: Dict[str, Any], combination: Dict[Dimension, Any]) -> NodePlan:
    service, version = service_and_version(node.get("service", ""))
    own = {setting: value for (owner, setting), value in combination.items() if owner == node_name}
    own_rate = own.pop(SOURCE_RATE, None)
    knobs_of_the_service = knobs_of(service, version, node_name)
    for (owner, knob_name), value in combination.items():
        if owner == SHARED and knob_name in knobs_of_the_service:
            own[knob_name] = value
    return NodePlan(
        name=node_name,
        service=service,
        version=version,
        cores=float(own.pop("cores")) if "cores" in own else float(own["parallelism"]) + float(own.pop(CORES_BEYOND)),
        memory=str(own.pop("memory")),
        knobs=own,
        rps=None if own_rate is None else float(own_rate),
        auto_cores=bool(node.get(AUTO_CORES, True)),
    )


def knobs_of(service: str, version: str, node_name: str) -> Dict[str, Any]:
    try:
        return load_service_spec(service_directory(service, version)).all_knobs()
    except ServiceMissing:
        raise PlanInvalid(f"node {node_name}: there is no service {service} {version} in services/")


def refuse_shared_knobs_that_cannot_be_shared(experiment: Dict[str, Any], tried: Dict[Dimension, List[Any]]) -> None:
    for (owner, knob_name), values in tried.items():
        if owner != SHARED:
            continue
        holders = 0
        for node_name, node in experiment["nodes"].items():
            knobs = knobs_of(*service_and_version(node.get("service", "")), node_name)
            if knob_name not in knobs:
                continue
            holders += 1
            if knob_name in (node.get("knobs") or {}):
                raise PlanInvalid(f"node {node_name} sets {knob_name} itself, but it is a shared knob of the whole run")
            for value in values:
                try:
                    knobs[knob_name].validated(value)
                except KnobValueRejected as problem:
                    raise PlanInvalid(f"shared knob {knob_name}, node {node_name}: {problem}")
        if not holders:
            raise PlanInvalid(f"no service of the experiment has the shared knob {knob_name}")


def refuse_load_that_cannot_be_made(tried: Dict[Dimension, List[Any]]) -> None:
    for pattern in tried[(LOAD, "pattern")]:
        if pattern not in available_patterns():
            raise PlanInvalid(f"load pattern must be one of {available_patterns()}, not {pattern!r}")
    for process in tried[(LOAD, "arrival_process")]:
        if process not in ARRIVAL_PROCESSES:
            raise PlanInvalid(f"arrival_process must be one of {list(ARRIVAL_PROCESSES)}, not {process!r}")
    for variability in tried[(LOAD, "arrival_variability")]:
        if variability < 0:
            raise PlanInvalid(f"arrival_variability is the squared coefficient of variation of the gaps, at least 0, not {variability}")
        if variability != 1 and tried[(LOAD, "arrival_process")] != ["renewal"]:
            raise PlanInvalid("arrival_variability other than 1 needs arrival_process: renewal")
    for utilization in tried[(LOAD, "utilization")]:
        if utilization < 0:
            raise PlanInvalid(f"utilization is the busy share of the busiest service, at least 0, not {utilization}")
    if any(tried[(LOAD, "utilization")]):
        if any(tried[(LOAD, "rps")]) or any(setting == SOURCE_RATE for _, setting in tried if _ != LOAD):
            raise PlanInvalid("a load is given either as utilization or as rps, not both")
        if not all(tried[(LOAD, "utilization")]):
            raise PlanInvalid("utilization 0 means no utilization target; do not mix it with other values")
    for speed in tried[(LOAD, "trace_speed")]:
        if speed <= 0:
            raise PlanInvalid(f"trace_speed must be above 0, not {speed}")
    for factor in tried[(LOAD, "burst_factor")]:
        for seconds in tried[(LOAD, "burst_seconds")]:
            try:
                Bursts(factor, seconds, seed=0)
            except BurstsImpossible as problem:
                raise PlanInvalid(str(problem))


def refuse_fan_in_that_cannot_be_made(experiment: Dict[str, Any]) -> None:
    fan_in = experiment.get("fan_in", EACH)
    if fan_in not in FAN_IN_KINDS:
        raise PlanInvalid(f"fan_in must be one of {list(FAN_IN_KINDS)}, not {fan_in!r}")
    if fan_in == JOIN and experiment.get("link", LINK_KINDS[0]) != "requests":
        raise PlanInvalid("fan_in: join waits for the same request from every feeder, so it needs link: requests")


def refuse_cpu_slack_that_cannot_be_set(run_settings: Dict[str, Any], tried: Dict[Dimension, List[Any]]) -> None:
    cpu_slack = float(run_settings.get("cpu_slack", 0))
    if cpu_slack == 0:
        return
    if cpu_slack < 1:
        raise PlanInvalid(f"cpu_slack multiplies the cores a service needs, so it is at least 1 (or 0 for off), not {cpu_slack}")
    if not all(tried[(LOAD, "utilization")]):
        raise PlanInvalid("cpu_slack measures the cores a service needs in the utilization probe, so it needs load: {utilization: ...}")


def refuse_source_rates_on_other_nodes(experiment: Dict[str, Any], topology: Topology) -> None:
    sources = set(topology.sources())
    for node_name, node in experiment["nodes"].items():
        if SOURCE_RATE in node and node_name not in sources:
            raise PlanInvalid(f"node {node_name} is fed by other services, so it cannot have its own rps; only {sorted(sources)} can")


def refuse_values_outside_the_specs(experiment: Dict[str, Any], tried: Dict[Dimension, List[Any]]) -> None:
    for node_name, node in experiment["nodes"].items():
        service, version = service_and_version(node.get("service", ""))
        knobs = knobs_of(service, version, node_name)
        for (owner, setting), values in tried.items():
            if owner != node_name or setting in NODE_SETTINGS_THAT_ARE_NOT_KNOBS:
                continue
            if setting not in knobs:
                raise PlanInvalid(f"node {node_name}: {service} has no knob {setting}. It has {sorted(knobs)}")
            for value in values:
                try:
                    knobs[setting].validated(value)
                except KnobValueRejected as problem:
                    raise PlanInvalid(f"node {node_name}: {problem}")


def refuse_plans_that_do_not_fit(plans: List[RunPlan], workload_cpu_count: int) -> None:
    for plan in plans:
        cores_asked = sum(node.cores for node in plan.nodes)
        if cores_asked > workload_cpu_count:
            raise PlanInvalid(
                f"{plan.run_id} asks for {cores_asked} cores in total, the machine offers {workload_cpu_count} to services"
            )
