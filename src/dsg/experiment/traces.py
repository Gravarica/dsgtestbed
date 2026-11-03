from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from dsg.service_composer.topology import topology_of

NANOSECONDS_PER_MILLISECOND = 1_000_000
REQUESTS = "requests"
TRACES_FILE = "traces.csv"
TRACE_STEPS_FILE = "trace_steps.csv"
REPORTED_QUANTILES = {"p50": 0.50, "p95": 0.95, "p99": 0.99}
STEP_COLUMNS = [
    "request_id",
    "node",
    "position",
    "outcome",
    "handed_over_by",
    "handover_ms",
    "waiting_for_inputs_ms",
    "waiting_ms",
    "processing_ms",
    "arrived_at_ns",
    "finished_at_ns",
]


def write_traces(run_directory: Path) -> Optional[Dict[str, Any]]:
    run_directory = Path(run_directory)
    plan = json.loads((run_directory / "run.json").read_text())["plan"]
    if plan["link"] != REQUESTS:
        return None
    traces, steps = paths_of_requests(run_directory, plan)
    traces.to_csv(run_directory / TRACES_FILE, index=False)
    steps.to_csv(run_directory / TRACE_STEPS_FILE, index=False)
    return end_to_end_columns(traces)


def paths_of_requests(run_directory: Path, plan: Dict[str, Any]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    topology = topology_of([node["name"] for node in plan["nodes"]], [tuple(edge) for edge in plan["edges"]])
    steps = steps_of_measured_requests(run_directory, topology.from_first_to_last())
    last_services = [name for name in topology.node_names if not topology.next_hops_of(name)]
    return traces_from(steps, last_services), steps[STEP_COLUMNS]


def steps_of_measured_requests(run_directory: Path, services_in_order) -> pd.DataFrame:
    per_service = []
    for position, node_name in enumerate(services_in_order):
        records_file = run_directory / node_name / "records.csv"
        if records_file.exists():
            records = pd.read_csv(records_file, dtype={"handed_over_by": "string"})
            per_service.append(records.assign(node=node_name, position=position))
    if not per_service:
        return pd.DataFrame(columns=STEP_COLUMNS + ["request_entered_at_ns"])
    steps = pd.concat(per_service, ignore_index=True)
    steps = steps[steps["admission_phase"] == "measure"].copy()
    steps["first_input_at_ns"] = steps.get("first_input_at_ns", steps["arrived_at_ns"]).fillna(steps["arrived_at_ns"])
    finished_before = steps[["request_id", "node", "finished_at_ns"]].rename(
        columns={"node": "handed_over_by", "finished_at_ns": "finished_before_at_ns"}
    )
    steps = steps.merge(finished_before, on=["request_id", "handed_over_by"], how="left")
    steps["handover_ms"] = (steps["arrived_at_ns"] - steps["finished_before_at_ns"]) / NANOSECONDS_PER_MILLISECOND
    steps["waiting_for_inputs_ms"] = (steps["arrived_at_ns"] - steps["first_input_at_ns"]) / NANOSECONDS_PER_MILLISECOND
    steps["waiting_ms"] = (steps["started_at_ns"] - steps["arrived_at_ns"]) / NANOSECONDS_PER_MILLISECOND
    steps["processing_ms"] = (steps["finished_at_ns"] - steps["started_at_ns"]) / NANOSECONDS_PER_MILLISECOND
    return steps.sort_values(["request_entered_at_ns", "request_id", "position"]).reset_index(drop=True)


def traces_from(steps: pd.DataFrame, last_services) -> pd.DataFrame:
    columns = ["request_id", "entered_at_ns", "left_at_ns", "total_ms", "services_passed", "completed"]
    if steps.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for request_id, path in steps.groupby("request_id", sort=False):
        finished_well = set(path[path["outcome"] == "completed"]["node"])
        entered_at_ns = int(path["request_entered_at_ns"].min())
        left_at_ns = int(path["finished_at_ns"].max())
        rows.append(
            {
                "request_id": request_id,
                "entered_at_ns": entered_at_ns,
                "left_at_ns": left_at_ns,
                "total_ms": (left_at_ns - entered_at_ns) / NANOSECONDS_PER_MILLISECOND,
                "services_passed": len(finished_well),
                "completed": all(service in finished_well for service in last_services),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def end_to_end_columns(traces: pd.DataFrame) -> Dict[str, Any]:
    completed = traces[traces["completed"]] if not traces.empty else traces
    columns: Dict[str, Any] = {"requests_entered": len(traces), "requests_completed": len(completed)}
    if len(completed):
        columns["end_to_end_mean_ms"] = completed["total_ms"].mean()
        for label, quantile in REPORTED_QUANTILES.items():
            columns[f"end_to_end_{label}_ms"] = completed["total_ms"].quantile(quantile)
    return columns
