from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from dsg.experiment.plan import RunPlan, load_experiment, run_plans

SECONDS_PER_RUN_BEYOND_THE_LOAD = 15
SECONDS_PER_NODE = 3
SECONDS_PER_HOUR = 3600


def expected_seconds(plan: RunPlan) -> float:
    return plan.warmup_seconds + plan.measure_seconds + SECONDS_PER_RUN_BEYOND_THE_LOAD + SECONDS_PER_NODE * len(plan.nodes)


def estimate_of(experiment_file: Path, workload_cpu_count: int) -> Dict[str, Any]:
    plans = run_plans(load_experiment(experiment_file), workload_cpu_count)
    return {
        "experiment": Path(experiment_file).stem,
        "runs": len(plans),
        "nodes": max(len(plan.nodes) for plan in plans),
        "largest_core_sum": max(sum(node.cores for node in plan.nodes) for plan in plans),
        "hours": sum(expected_seconds(plan) for plan in plans) / SECONDS_PER_HOUR,
    }


def estimate_table(estimates: List[Dict[str, Any]]) -> str:
    lines = [f"{'experiment':40} {'runs':>6} {'nodes':>6} {'cores':>6} {'hours':>7}"]
    for estimate in estimates:
        lines.append(
            f"{estimate['experiment']:40} {estimate['runs']:>6} {estimate['nodes']:>6} "
            f"{estimate['largest_core_sum']:>6.1f} {estimate['hours']:>7.2f}"
        )
    lines.append(f"{'total':40} {sum(e['runs'] for e in estimates):>6} {'':>6} {'':>6} {sum(e['hours'] for e in estimates):>7.2f}")
    return "\n".join(lines)
