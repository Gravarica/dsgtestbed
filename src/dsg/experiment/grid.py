from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from dsg.docker_host import DockerHost
from dsg.experiment.dataset import dataset_rows
from dsg.experiment.plan import load_experiment, run_plans
from dsg.experiment.provenance import capture_provenance
from dsg.experiment.run import PipelineRun
from dsg.experiment.summary import write_summary
from dsg.experiment.traces import write_traces
from dsg.node import load_node_settings
from dsg.repository import NODE_FILE, REPOSITORY_ROOT, RESULTS_DIRECTORY
from dsg.service_runtime.control_client import ControlClient


def new_results_directory(experiment_name: str, experiment_file: Path) -> Path:
    started_at = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    directory = RESULTS_DIRECTORY / experiment_name / started_at
    directory.mkdir(parents=True)
    shutil.copy2(experiment_file, directory / "experiment.yaml")
    provenance = {**capture_provenance(REPOSITORY_ROOT), "experiment": experiment_name, "started_at": started_at}
    (directory / "provenance.json").write_text(json.dumps(provenance, indent=2))
    return directory


def run_experiment(experiment_file: Path) -> Path:
    experiment_file = Path(experiment_file)
    experiment_name = experiment_file.stem
    node = load_node_settings(NODE_FILE)
    plans = run_plans(load_experiment(experiment_file), node.workload_cpu_count())
    results_directory = new_results_directory(experiment_name, experiment_file)
    os.sched_setaffinity(0, node.infrastructure_cpus())
    print(f"[{experiment_name}] {len(plans)} runs, results in {results_directory}")
    rows = []
    for position, plan in enumerate(plans, start=1):
        run_directory = results_directory / "runs" / plan.run_id
        run_directory.mkdir(parents=True)
        try:
            PipelineRun(
                plan=plan,
                node_settings=node,
                project=f"dsg-{experiment_name}-{results_directory.name}-{plan.run_id}",
                run_directory=run_directory,
                docker=DockerHost(),
                service_at=ControlClient,
                wait=time.sleep,
            ).execute()
            rows_of_this_run = dataset_rows(run_directory, write_traces(run_directory))
        except Exception as failure:
            print(f"[{experiment_name}] {position}/{len(plans)} {plan.run_id} -> INVALID (crashed: {type(failure).__name__}: {str(failure)[:300]})")
            continue
        rows.extend(rows_of_this_run)
        pd.DataFrame(rows).to_csv(results_directory / "dataset.csv", index=False)
        print(f"[{experiment_name}] {position}/{len(plans)} {plan.run_id} rps={plan.rps} {described(rows_of_this_run)}")
    print(f"[{experiment_name}] dataset -> {results_directory / 'dataset.csv'}")
    print(f"[{experiment_name}] summary -> {write_summary(results_directory)}")
    return results_directory


def described(rows_of_one_run: List[Dict[str, Any]]) -> str:
    verdict = "valid" if rows_of_one_run[0]["valid"] else f"INVALID ({rows_of_one_run[0]['flags']})"
    per_node = []
    for row in rows_of_one_run:
        latency = row.get("processing_mean_ms")
        measured = f"{row.get('measured_items', 0)} items, {latency:.1f} ms" if latency is not None else "no records"
        per_node.append(f"{row['node']}: {measured}")
    end_to_end = rows_of_one_run[0].get("end_to_end_mean_ms")
    whole_pipeline = f" | end to end: {end_to_end:.0f} ms over {rows_of_one_run[0]['requests_completed']} requests" if end_to_end else ""
    return f"-> {verdict} | " + " | ".join(per_node) + whole_pipeline
