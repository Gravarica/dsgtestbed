from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List

import pandas as pd

from dsg.experiment.plan import NodePlan, RunPlan
from dsg.monitor.container_stats import cpu_seconds_used, throttled_fraction
from dsg.service_runtime.contract import Knob, ServiceSpec

NANOSECONDS_PER_MILLISECOND = 1_000_000
NANOSECONDS_PER_SECOND = 1_000_000_000
PROBE_RATE_PER_SECOND = 2.0
PROBE_SECONDS = 5.0
SHARE_OF_CAPACITY_USED = 0.5
SLOWEST_TRIAL_RATE = 1.0
FASTEST_TRIAL_RATE = 200.0
ITEMS_WANTED_PER_TRIAL = 30
LONGEST_TRIAL_SECONDS = 60.0
KNOB_TRIAL_RATE_LIMIT = 5.0
WORKERS_IN_SCALING_TRIAL = 4
CORES_BEYOND_THE_WORKERS = 1
CLEAR_EFFECT_RATIO = 1.15
SMALLEST_DIFFERENCE_THAT_COUNTS_MS = 0.05
HARNESS_CPU_SECONDS_PER_ITEM = 0.001
HARNESS_CPU_SHARE_WHEN_IDLE = 0.01
UNEXPLAINED_CPU_SECONDS_IGNORED = 0.2
UNEXPLAINED_CPU_SHARE_IGNORED = 0.3

HIGHER_TAKES_LONGER = "higher takes longer"
HIGHER_IS_FASTER = "higher is faster"
NO_EFFECT_ON_TIME = "no effect on time"

RunTrial = Callable[[RunPlan, Path], Dict[str, Any]]


@dataclass
class Behaviour:
    default_trial_failures: List[str] = field(default_factory=list)
    at_default: Dict[str, Any] = field(default_factory=dict)
    knobs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    workers: Dict[str, Any] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    safe_rate_per_second: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def behaviour_of(spec: ServiceSpec, memory_limit: str, run_trial: RunTrial, workspace: Path) -> Behaviour:
    trials = Trials(spec, memory_limit, run_trial, Path(workspace))
    probe = trials.probe()
    if probe.failures:
        return Behaviour(default_trial_failures=probe.failures)
    safe_rate = safe_rate_per_second(probe.processing_ms["mean"], workers=1)
    default = trials.run("default", {}, workers=1, rate=safe_rate, measure_seconds=8)
    if default.failures:
        return Behaviour(default_trial_failures=default.failures, safe_rate_per_second=safe_rate)
    behaviour = Behaviour(at_default=default.summary(), safe_rate_per_second=safe_rate)
    if default.has_unexplained_cpu():
        behaviour.flags.append("more_cpu_than_the_workers_explain")
    knob_rate = min(safe_rate, KNOB_TRIAL_RATE_LIMIT)
    for knob_name, knob in spec.application_knobs.items():
        behaviour.knobs[knob_name] = effect_of_knob(knob, trials, knob_rate)
        if behaviour.knobs[knob_name]["seen"] == NO_EFFECT_ON_TIME:
            behaviour.notes.append(f"knob {knob_name} has no effect on the processing time")
    behaviour.workers = scaling_with_workers(trials, default.processing_ms["mean"])
    return behaviour


def safe_rate_per_second(processing_mean_ms: float, workers: int) -> float:
    capacity = workers * 1000.0 / max(processing_mean_ms, 0.001)
    return round(min(FASTEST_TRIAL_RATE, max(SLOWEST_TRIAL_RATE, SHARE_OF_CAPACITY_USED * capacity)), 1)


def seconds_to_measure(rate_per_second: float, at_least_seconds: float) -> float:
    seconds_for_enough_items = ITEMS_WANTED_PER_TRIAL / max(rate_per_second, 0.001)
    return min(LONGEST_TRIAL_SECONDS, max(at_least_seconds, seconds_for_enough_items))


def lowest_and_highest(knob: Knob) -> List[Any]:
    return [knob.choices[0], knob.choices[-1]] if knob.kind == "choice" else [knob.minimum, knob.maximum]


def effect_seen(at_lowest_ms: float, at_highest_ms: float) -> str:
    if abs(at_highest_ms - at_lowest_ms) < SMALLEST_DIFFERENCE_THAT_COUNTS_MS:
        return NO_EFFECT_ON_TIME
    if at_highest_ms > at_lowest_ms * CLEAR_EFFECT_RATIO:
        return HIGHER_TAKES_LONGER
    if at_lowest_ms > at_highest_ms * CLEAR_EFFECT_RATIO:
        return HIGHER_IS_FASTER
    return NO_EFFECT_ON_TIME


def effect_of_knob(knob: Knob, trials: "Trials", rate: float) -> Dict[str, Any]:
    lowest, highest = lowest_and_highest(knob)
    at_lowest = trials.run(f"{knob.name}-lowest", {knob.name: lowest}, workers=1, rate=rate, measure_seconds=6)
    at_highest = trials.run(f"{knob.name}-highest", {knob.name: highest}, workers=1, rate=rate, measure_seconds=6)
    if at_lowest.failures or at_highest.failures:
        return {"seen": "trial failed", "failures": at_lowest.failures + at_highest.failures}
    return {
        "lowest_value": lowest,
        "highest_value": highest,
        "at_lowest_ms": at_lowest.processing_ms["mean"],
        "at_highest_ms": at_highest.processing_ms["mean"],
        "items_measured": [at_lowest.measured_items, at_highest.measured_items],
        "seen": effect_seen(at_lowest.processing_ms["mean"], at_highest.processing_ms["mean"]),
    }


def scaling_with_workers(trials: "Trials", processing_mean_ms: float) -> Dict[str, Any]:
    rate = safe_rate_per_second(processing_mean_ms, WORKERS_IN_SCALING_TRIAL)
    several = trials.run("several-workers", {}, workers=WORKERS_IN_SCALING_TRIAL, rate=rate, measure_seconds=6)
    if several.failures:
        return {"workers": WORKERS_IN_SCALING_TRIAL, "failures": several.failures}
    return {
        "workers": WORKERS_IN_SCALING_TRIAL,
        "rate_per_second": rate,
        "kept_up": several.achieved_rate_per_second >= 0.8 * rate,
        "processing_mean_ms": several.processing_ms["mean"],
        "processing_mean_ms_with_one_worker": processing_mean_ms,
    }


@dataclass
class TrialOutcome:
    name: str
    failures: List[str]
    processing_ms: Dict[str, float] = field(default_factory=dict)
    spread: float = 0.0
    measured_items: int = 0
    throttled_share_of_periods: float = 0.0
    achieved_rate_per_second: float = 0.0
    memory_mb: float = 0.0
    seconds_inside_process: float = 0.0
    unexplained_cpu_seconds: float = 0.0

    def has_unexplained_cpu(self) -> bool:
        ignored = max(UNEXPLAINED_CPU_SECONDS_IGNORED, UNEXPLAINED_CPU_SHARE_IGNORED * self.seconds_inside_process)
        return self.unexplained_cpu_seconds > ignored

    def summary(self) -> Dict[str, Any]:
        return {
            "processing_ms": self.processing_ms,
            "spread_std_over_mean": self.spread,
            "measured_items": self.measured_items,
            "measured_at_items_per_second": self.achieved_rate_per_second,
            "throttled_share_of_periods": self.throttled_share_of_periods,
            "memory_mb_one_worker": self.memory_mb,
            "seconds_inside_process": self.seconds_inside_process,
            "cpu_seconds_not_explained_by_workers_or_harness": self.unexplained_cpu_seconds,
        }


class Trials:
    def __init__(self, spec: ServiceSpec, memory_limit: str, run_trial: RunTrial, workspace: Path):
        self._spec = spec
        self._memory_limit = memory_limit
        self._run_trial = run_trial
        self._workspace = workspace
        self._trials_run = 0

    def probe(self) -> TrialOutcome:
        return self._run_for("probe", {"discipline": "fifo"}, 1, PROBE_RATE_PER_SECOND, PROBE_SECONDS)

    def run(self, name: str, knobs: Dict[str, Any], workers: int, rate: float, measure_seconds: float) -> TrialOutcome:
        return self._run_for(name, knobs, workers, rate, seconds_to_measure(rate, measure_seconds))

    def _run_for(self, name: str, knobs: Dict[str, Any], workers: int, rate: float, measure_seconds: float) -> TrialOutcome:
        directory = self._workspace / name
        directory.mkdir(parents=True, exist_ok=True)
        node = NodePlan(
            name=self._spec.name,
            service=self._spec.name,
            version=self._spec.version,
            cores=float(workers + CORES_BEYOND_THE_WORKERS),
            memory=self._memory_limit,
            knobs={**knobs, "parallelism": workers},
        )
        plan = RunPlan(
            run_id=name,
            nodes=(node,),
            edges=(),
            link="rates",
            rps=rate,
            repetition=0,
            warmup_seconds=2,
            measure_seconds=measure_seconds,
            queue_capacity=10000,
            arrival_process="deterministic",
            arrival_seed=self._trials_run,
            load_pattern="constant",
            pattern_start_second=0,
        )
        self._trials_run += 1
        return outcome_of_trial(name, self._spec.name, self._run_trial(plan, directory), directory)


def outcome_of_trial(name: str, node_name: str, described_run: Dict[str, Any], directory: Path) -> TrialOutcome:
    failures = list(described_run["problems"]) + list(described_run["flags"])
    records_file = directory / node_name / "records.csv"
    summary_file = directory / node_name / "run_summary.json"
    measured_container = described_run.get("nodes", {}).get(node_name, {})
    if failures or not records_file.exists() or not summary_file.exists():
        return TrialOutcome(name, failures or ["the service wrote no records"])
    summary = json.loads(summary_file.read_text())
    records = pd.read_csv(records_file)
    not_completed = int((records["outcome"] != "completed").sum())
    if not_completed or summary["counts"]["unresolved"]:
        return TrialOutcome(name, [f"{not_completed} items failed, {summary['counts']['unresolved']} never finished"])
    measured = records[records["admission_phase"] == "measure"]
    if measured.empty:
        return TrialOutcome(name, ["no item arrived during the measurement"])
    processing_ms = (measured["finished_at_ns"] - measured["started_at_ns"]) / NANOSECONDS_PER_MILLISECOND
    inside_process, unexplained = cpu_not_explained(measured_container, summary, records)
    return TrialOutcome(
        name=name,
        failures=[],
        processing_ms={
            "mean": round(float(processing_ms.mean()), 3),
            "median": round(float(processing_ms.median()), 3),
            "p99": round(float(processing_ms.quantile(0.99)), 3),
        },
        spread=round(float(processing_ms.std(ddof=0) / processing_ms.mean()), 3) if processing_ms.mean() > 0 else 0.0,
        measured_items=len(measured),
        throttled_share_of_periods=round(throttled_share(measured_container), 3),
        achieved_rate_per_second=float(summary["achieved_rate_per_second"]),
        memory_mb=round(measured_container.get("memory_bytes_under_load", 0) / 1_000_000, 1),
        seconds_inside_process=round(inside_process, 3),
        unexplained_cpu_seconds=round(unexplained, 3),
    )


def throttled_share(measured_container: Dict[str, Any]) -> float:
    cpu_stat = measured_container.get("cpu_stat", {})
    return throttled_fraction(cpu_stat.get("before", {}), cpu_stat.get("after", {}))


def cpu_not_explained(measured_container: Dict[str, Any], summary: Dict[str, Any], records: pd.DataFrame):
    entered = summary["lifecycle_entered_at_ns"]
    if "measuring" not in entered or "draining" not in entered:
        return 0.0, 0.0
    window_seconds = (entered["draining"] - entered["measuring"]) / NANOSECONDS_PER_SECOND
    inside = records[(records["started_at_ns"] >= entered["measuring"]) & (records["finished_at_ns"] <= entered["draining"])]
    seconds_inside_process = float((inside["finished_at_ns"] - inside["started_at_ns"]).sum()) / NANOSECONDS_PER_SECOND
    cpu_stat = measured_container.get("cpu_stat", {})
    cpu_seconds = cpu_seconds_used(cpu_stat.get("before", {}), cpu_stat.get("after", {}))
    harness_allowance = len(inside) * HARNESS_CPU_SECONDS_PER_ITEM + window_seconds * HARNESS_CPU_SHARE_WHEN_IDLE
    return seconds_inside_process, max(0.0, cpu_seconds - seconds_inside_process - harness_allowance)
