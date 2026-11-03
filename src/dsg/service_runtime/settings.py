from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping


@dataclass(frozen=True)
class RuntimeSettings:
    service_directory: Path
    records_directory: Path
    node_name: str
    container_id: str
    cores: float
    queue_capacity: int
    arrival_process: str
    arrival_seed: int
    arrival_variability: float
    native_threads_per_worker: int
    warm_up_items_per_worker: int
    drain_timeout_seconds: float
    lateness_tolerance_ms: float
    control_port: int
    metrics_port: int
    default_client_rates: Dict[str, float]
    next_hop_urls: List[str]
    link_kind: str
    join_inputs: int = 1


def client_rates_from_text(text: str) -> Dict[str, float]:
    rates = {}
    for entry in filter(None, text.split(",")):
        client_id, rate = entry.split(":")
        rates[client_id] = float(rate)
    return rates


def runtime_settings_from_environment(environment: Mapping[str, str] = os.environ) -> RuntimeSettings:
    return RuntimeSettings(
        service_directory=Path(environment.get("SERVICE_DIRECTORY", "/service")),
        records_directory=Path(environment.get("RECORDS_DIRECTORY", "/records")),
        node_name=environment.get("NODE_NAME", "service"),
        container_id=environment.get("CONTAINER_REF", "unknown"),
        cores=float(environment.get("DEFAULT_CORES", 1.0)),
        queue_capacity=int(environment.get("QUEUE_CAPACITY", 10000)),
        arrival_process=environment.get("ARRIVAL_PROCESS", "poisson"),
        arrival_seed=int(environment.get("ARRIVAL_SEED", 0)),
        arrival_variability=float(environment.get("ARRIVAL_VARIABILITY", 1.0)),
        native_threads_per_worker=int(environment.get("NATIVE_THREADS_PER_WORKER", 1)),
        warm_up_items_per_worker=int(environment.get("WARM_UP_ITEMS_PER_WORKER", 3)),
        drain_timeout_seconds=float(environment.get("DRAIN_TIMEOUT_SECONDS", 120)),
        lateness_tolerance_ms=float(environment.get("LATENESS_TOLERANCE_MS", 50)),
        control_port=int(environment.get("CONTROL_PORT", 8080)),
        metrics_port=int(environment.get("METRICS_PORT", 8000)),
        default_client_rates=client_rates_from_text(environment.get("DEFAULT_CLIENTS", "")),
        next_hop_urls=[url for url in environment.get("NEXT_HOPS", "").split(",") if url],
        link_kind=environment.get("LINK", "rates"),
        join_inputs=int(environment.get("JOIN_INPUTS", 1)),
    )
