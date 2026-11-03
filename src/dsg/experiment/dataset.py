from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from dsg.monitor.container_stats import cpu_seconds_used, throttled_fraction

NANOSECONDS_PER_MILLISECOND = 1_000_000
REPORTED_QUANTILES = {"p50": 0.50, "p95": 0.95, "p99": 0.99}


def latency_columns(prefix: str, latencies_ms: pd.Series) -> Dict[str, float]:
    if latencies_ms.empty:
        return {}
    columns = {f"{prefix}_mean_ms": latencies_ms.mean()}
    for label, quantile in REPORTED_QUANTILES.items():
        columns[f"{prefix}_{label}_ms"] = latencies_ms.quantile(quantile)
    return columns


def offered_rate_columns(offered_rates: Optional[List[float]], plan: Dict[str, Any], measure_seconds: float) -> Dict[str, float]:
    first_second = int(plan["warmup_seconds"])
    measured = pd.Series((offered_rates or [])[first_second : first_second + int(measure_seconds)], dtype=float)
    if measured.empty:
        return {}
    mean = float(measured.mean())
    return {"offered_rate_mean": mean, "offered_rate_cv": float(measured.std(ddof=0) / mean) if mean > 0 else 0.0}


def dataset_rows(run_directory: Path, end_to_end: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    described = json.loads((Path(run_directory) / "run.json").read_text())
    rows = [row_of_node(Path(run_directory), described, node_name) for node_name in described["nodes"]]
    return [{**row, **(end_to_end or {})} for row in rows]


def row_of_node(run_directory: Path, described: Dict[str, Any], node_name: str) -> Dict[str, Any]:
    plan = described["plan"]
    node = described["nodes"][node_name]
    cpu_before, cpu_after = node["cpu_stat"].get("before", {}), node["cpu_stat"].get("after", {})
    measure_seconds = described.get("measure_seconds", plan["measure_seconds"])
    row = {
        "run_id": plan["run_id"],
        "repetition": plan["repetition"],
        "node": node_name,
        "service": node["service"],
        "pipeline": " ".join(f"{sender}->{receiver}" for sender, receiver in plan["edges"]) or node_name,
        "link": plan["link"],
        "rps_on_first_service": described.get("rate_for_the_utilization") or plan["rps"],
        "utilization_asked": plan.get("utilization", 0.0),
        "arrival_variability": plan.get("arrival_variability", 1.0),
        "measure_seconds": measure_seconds,
        "load_pattern": plan["load_pattern"],
        "trace_speed": plan.get("trace_speed", 1.0),
        "burst_factor": plan.get("burst_factor", 1.0),
        "burst_seconds": plan.get("burst_seconds", 1),
        "arrival_process": plan["arrival_process"],
        **offered_rate_columns(described.get("offered_rates", {}).get(node_name), plan, measure_seconds),
        **described["settings"],
        "valid": described["valid"],
        "flags": ";".join(described["flags"] + described["problems"]),
        "throttled_fraction": throttled_fraction(cpu_before, cpu_after),
        "cpu_seconds_used": cpu_seconds_used(cpu_before, cpu_after),
        "memory_mb_under_load": round(node["memory_bytes_under_load"] / 1_000_000, 1),
    }
    records_file = run_directory / node_name / "records.csv"
    summary_file = run_directory / node_name / "run_summary.json"
    if not records_file.exists() or not summary_file.exists():
        return row
    summary = json.loads(summary_file.read_text())
    records = pd.read_csv(records_file)
    measured = records[(records["admission_phase"] == "measure") & (records["outcome"] == "completed")]
    processing_ms = (measured["finished_at_ns"] - measured["started_at_ns"]) / NANOSECONDS_PER_MILLISECOND
    settings = described["settings"]
    workers = float(settings.get(f"{node_name}.parallelism", 1))
    servers = workers if f"{node_name}.probe_cores" in settings else min(workers, float(settings[f"{node_name}.cores"]))
    row.update(
        {
            "utilization_measured": summary["achieved_rate_per_second"] * processing_ms.mean() / 1000 / servers if len(processing_ms) else None,
            "config_id": summary["config_id"],
            "measured_items": len(measured),
            "rate_received": summary["achieved_rate_per_second"],
            "arrival_lateness_p99_ms": summary["arrival_lateness_ms"]["p99"],
            **latency_columns("processing", (measured["finished_at_ns"] - measured["started_at_ns"]) / NANOSECONDS_PER_MILLISECOND),
            **latency_columns("waiting", (measured["started_at_ns"] - measured["arrived_at_ns"]) / NANOSECONDS_PER_MILLISECOND),
            **latency_columns("sojourn", (measured["finished_at_ns"] - measured["arrived_at_ns"]) / NANOSECONDS_PER_MILLISECOND),
        }
    )
    return row
