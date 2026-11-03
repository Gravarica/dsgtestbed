from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from dsg.experiment.plan import LINK_KINDS, LOAD, LOAD_DEFAULTS, as_list, size_of_space, values_to_try

SUMMARY_FILE = "summary.json"
SETTINGS_THAT_ARE_NOT_KNOBS = ("service",)
SERVICE_NUMBERS = {
    "rate_received": "rate_received",
    "items": "measured_items",
    "processing_mean_ms": "processing_mean_ms",
    "processing_p99_ms": "processing_p99_ms",
    "waiting_mean_ms": "waiting_mean_ms",
    "waiting_p99_ms": "waiting_p99_ms",
    "sojourn_mean_ms": "sojourn_mean_ms",
    "throttled_fraction": "throttled_fraction",
    "memory_mb": "memory_mb_under_load",
}
END_TO_END_NUMBERS = ("requests_completed", "end_to_end_mean_ms", "end_to_end_p50_ms", "end_to_end_p95_ms", "end_to_end_p99_ms")
THROTTLING_THAT_COUNTS = 0.1
STATUS_LINE = re.compile(r"experiments/(?:[^/]+/)*(?P<name>[^/]+)\.yaml started (?P<started>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): plain(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(inner) for inner in value]
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, float):
        return round(value, 3)
    return value


def write_summary(results_directory: Path) -> Path:
    results_directory = Path(results_directory)
    summary = campaign_summary(results_directory) if (results_directory / "status.txt").exists() else experiment_summary(results_directory)
    summary_file = results_directory / SUMMARY_FILE
    summary_file.write_text(json.dumps(plain(summary), indent=2))
    return summary_file


def experiment_summary(results_directory: Path) -> Dict[str, Any]:
    import yaml

    experiment = yaml.safe_load((results_directory / "experiment.yaml").read_text())
    provenance = json.loads((results_directory / "provenance.json").read_text())
    dataset = pd.read_csv(results_directory / "dataset.csv")
    runs = run_descriptions(results_directory)
    nodes = list(dict.fromkeys(dataset["node"]))
    return {
        "experiment": provenance.get("experiment", results_directory.parent.name),
        "started_at": started_at_text(provenance.get("started_at")),
        "duration_minutes": duration_minutes(provenance.get("started_at"), last_record_written(results_directory)),
        "workflow": workflow_of(experiment, dataset),
        "hardware": hardware_of(provenance, runs, nodes),
        "outcome": outcome_of(dataset),
        "per_service": {node: service_summary(dataset, node, experiment) for node in nodes},
        "end_to_end": end_to_end_summary(dataset),
        "runs": [run_summary(dataset, run_id, nodes) for run_id in dict.fromkeys(dataset["run_id"])],
        "csv_rows": rows_of_every_csv(results_directory),
    }


def rows_of_every_csv(results_directory: Path) -> Dict[str, int]:
    rows = {}
    for csv_file in sorted(results_directory.rglob("*.csv")):
        with csv_file.open("rb") as lines:
            rows[str(csv_file.relative_to(results_directory))] = max(sum(1 for _ in lines) - 1, 0)
    return rows


def started_at_text(started_at: Optional[str]) -> Optional[str]:
    if not started_at:
        return None
    return datetime.strptime(started_at, "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M:%S UTC")


def last_record_written(results_directory: Path) -> Optional[float]:
    written = [file.stat().st_mtime for file in results_directory.glob("runs/run-*/*/records.csv")]
    return max(written) if written else None


def duration_minutes(started_at: Optional[str], ended_at_timestamp: Optional[float]) -> Optional[int]:
    if not started_at or ended_at_timestamp is None:
        return None
    began = datetime.strptime(started_at, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
    ended = datetime.fromtimestamp(ended_at_timestamp, tz=timezone.utc)
    return max(0, round((ended - began).total_seconds() / 60))


def workflow_of(experiment: Dict[str, Any], dataset: pd.DataFrame) -> Dict[str, Any]:
    tried = values_to_try(experiment)
    space = {f"{owner}.{setting}": values for (owner, setting), values in tried.items() if owner != LOAD and len(values) > 1}
    combinations = size_of_space(tried)
    load = experiment.get("load") or {}
    run_settings = experiment.get("run") or {}
    return {
        "pipeline": dataset["pipeline"].iloc[0],
        "nodes": {name: node.get("service") for name, node in experiment["nodes"].items()},
        "edges": [edge if isinstance(edge, str) else " -> ".join(edge) for edge in experiment.get("edges") or []],
        "link": experiment.get("link", LINK_KINDS[0]),
        "load": {key: as_list(load.get(key, default)) for key, default in LOAD_DEFAULTS.items()},
        "space": space,
        "combinations_in_space": combinations,
        "runs": int(dataset["run_id"].nunique()),
        "repetitions": int(run_settings.get("repetitions", 1)),
        "warmup_seconds": run_settings.get("warmup_seconds", 10),
        "measure_seconds": run_settings.get("measure_seconds", 60),
    }


def run_descriptions(results_directory: Path) -> Dict[str, Dict[str, Any]]:
    described = {}
    for run_file in sorted((results_directory / "runs").glob("run-*/run.json")):
        described[run_file.parent.name] = json.loads(run_file.read_text())
    return described


def hardware_of(provenance: Dict[str, Any], runs: Dict[str, Dict[str, Any]], nodes: List[str]) -> Dict[str, Any]:
    hardware = dict(provenance.get("hardware") or {})
    first = next(iter(runs.values()), {})
    hardware["workload_cpuset"] = first.get("workload_cpuset")
    hardware["git_commit"] = provenance.get("git_commit")
    hardware["images"] = {
        f"{described['service'].replace(':', ' ')}": described.get("image_id")
        for node, described in first.get("nodes", {}).items()
    }
    return hardware


def outcome_of(dataset: pd.DataFrame) -> Dict[str, Any]:
    runs = dataset.drop_duplicates("run_id")
    flags: Dict[str, int] = {}
    for text in runs["flags"].dropna():
        for flag in str(text).split(";"):
            if flag:
                flags[flag] = flags.get(flag, 0) + 1
    return {"runs": len(runs), "valid": int(runs["valid"].sum()), "invalid": int((~runs["valid"]).sum()), "flags": flags}


def spread(values: pd.Series) -> Dict[str, Any]:
    values = values.dropna()
    if values.empty:
        return {"min": None, "median": None, "max": None}
    return {"min": values.min(), "median": values.median(), "max": values.max()}


def service_summary(dataset: pd.DataFrame, node: str, experiment: Dict[str, Any]) -> Dict[str, Any]:
    rows = dataset[(dataset["node"] == node) & dataset["valid"]]
    all_rows = dataset[dataset["node"] == node]
    tried = values_to_try(experiment)
    marginal = {}
    for (owner, setting), values in tried.items():
        column = f"{owner}.{setting}"
        if owner != node or len(values) < 2 or column not in rows or setting in SETTINGS_THAT_ARE_NOT_KNOBS:
            continue
        if "processing_mean_ms" not in rows:
            continue
        by_value = rows.groupby(column)[["processing_mean_ms", "waiting_mean_ms"]].mean()
        marginal[setting] = {str(value): {"processing_mean_ms": row.processing_mean_ms, "waiting_mean_ms": row.waiting_mean_ms} for value, row in by_value.iterrows()}
    return {
        "service": all_rows["service"].iloc[0],
        "valid_runs": len(rows),
        "processing_ms": spread(rows["processing_mean_ms"] if "processing_mean_ms" in rows else pd.Series(dtype=float)),
        "waiting_ms": spread(rows["waiting_mean_ms"] if "waiting_mean_ms" in rows else pd.Series(dtype=float)),
        "rate_received": spread(rows["rate_received"]) if "rate_received" in rows else None,
        "marginal_means": marginal,
        "runs_with_throttling_over_10_percent": int((all_rows["throttled_fraction"] > THROTTLING_THAT_COUNTS).sum()) if "throttled_fraction" in all_rows else 0,
    }


def end_to_end_summary(dataset: pd.DataFrame) -> Optional[Dict[str, Any]]:
    if "end_to_end_mean_ms" not in dataset or dataset["link"].iloc[0] != "requests":
        return None
    runs = dataset.drop_duplicates("run_id")
    valid = runs[runs["valid"]]
    return {
        "valid_runs": len(valid),
        "requests_completed_total": int(valid["requests_completed"].sum()) if "requests_completed" in valid else None,
        "mean_ms": spread(valid["end_to_end_mean_ms"]),
        "p99_ms": spread(valid["end_to_end_p99_ms"]) if "end_to_end_p99_ms" in valid else None,
    }


def run_summary(dataset: pd.DataFrame, run_id: str, nodes: List[str]) -> Dict[str, Any]:
    rows = dataset[dataset["run_id"] == run_id]
    first = rows.iloc[0]
    setting_columns = [c for c in dataset.columns if "." in c and c.split(".")[0] in nodes and c.split(".")[1] not in SETTINGS_THAT_ARE_NOT_KNOBS]
    summary = {
        "run_id": run_id,
        "settings": {column: first[column] for column in setting_columns},
        "rps": first["rps_on_first_service"],
        "valid": bool(first["valid"]),
        "flags": [flag for flag in str(first["flags"]).split(";") if flag and flag != "nan"],
        "services": {
            row["node"]: {name: row[column] for name, column in SERVICE_NUMBERS.items() if column in rows}
            for _, row in rows.iterrows()
        },
    }
    if first["link"] == "requests" and "end_to_end_mean_ms" in rows and pd.notna(first["end_to_end_mean_ms"]):
        summary["end_to_end"] = {column: first[column] for column in END_TO_END_NUMBERS if column in rows}
    return summary


SECONDS_BETWEEN_STATUS_LINE_AND_FOLDER = 120


def results_folder_started_at(experiment_root: Path, started_text: str) -> Optional[Path]:
    started = datetime.strptime(started_text, "%Y-%m-%d %H:%M:%S")
    candidates = []
    for folder in experiment_root.glob("*/"):
        try:
            folder_time = datetime.strptime(folder.name, "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        seconds_after = (folder_time - started).total_seconds()
        if -1 <= seconds_after <= SECONDS_BETWEEN_STATUS_LINE_AND_FOLDER and (folder / "dataset.csv").exists():
            candidates.append((seconds_after, folder))
    return min(candidates)[1] if candidates else None


def campaign_summary(campaign_directory: Path) -> Dict[str, Any]:
    status = (campaign_directory / "status.txt").read_text().splitlines()
    results_root = campaign_directory.parents[1]
    experiments = []
    for line in status:
        found = STATUS_LINE.search(line)
        if not found:
            continue
        results_directory = results_folder_started_at(results_root / found["name"], found["started"])
        if results_directory is None:
            continue
        full = experiment_summary(results_directory)
        experiments.append(
            {
                "experiment": full["experiment"],
                "results": str(results_directory.relative_to(results_root.parent)),
                "workflow": {key: full["workflow"][key] for key in ("pipeline", "link", "runs", "space")},
                "outcome": full["outcome"],
                "per_service": {node: {key: value[key] for key in ("processing_ms", "waiting_ms")} for node, value in full["per_service"].items()},
                "end_to_end": full["end_to_end"],
            }
        )
    first_line = status[0] if status else ""
    last_line = status[-1] if status else ""
    return {
        "campaign": campaign_directory.name,
        "started": first_line.split("started ")[-1].split(",")[0] if "started" in first_line else None,
        "done": last_line.split("done ")[-1] if "done" in last_line else None,
        "hardware": experiments and experiment_summary(results_root.parent / experiments[0]["results"])["hardware"] or None,
        "experiments": experiments,
        "runs": sum(item["outcome"]["runs"] for item in experiments),
        "valid": sum(item["outcome"]["valid"] for item in experiments),
        "invalid": sum(item["outcome"]["invalid"] for item in experiments),
    }
