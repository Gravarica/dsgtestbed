from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from dsg.service_runtime.records import COMPLETED, ProcessingRecord, RecordBook
from dsg.service_runtime.timing import Clock, TickSchedule

ELASTIC_WORKBENCH_COLUMNS = [
    "timestamp",
    "service_type",
    "container_id",
    "avg_p_latency",
    "s_config",
    "cores",
    "rps",
    "throughput",
    "cooldown",
]
NO_ITEMS_PROCESSED = -1


@dataclass(frozen=True)
class WindowMetrics:
    timestamp: str
    service_type: str
    container_id: str
    avg_p_latency: int
    s_config: str
    cores: float
    rps: float
    throughput: int
    cooldown: int

    def as_row(self) -> List[Any]:
        return [getattr(self, column) for column in ELASTIC_WORKBENCH_COLUMNS]


@dataclass(frozen=True)
class ServiceIdentity:
    service_type: str
    container_id: str
    configuration: Dict[str, Any]
    cores: float


def average_processing_latency_ms(completed: List[ProcessingRecord]) -> int:
    if not completed:
        return NO_ITEMS_PROCESSED
    total_ns = sum(record.finished_at_ns - record.started_at_ns for record in completed)
    return max(1, round(total_ns / len(completed) / 1_000_000))


def metrics_of_window(
    resolved_in_window: List[ProcessingRecord], wall_ns: int, identity: ServiceIdentity, rate_per_second: float
) -> WindowMetrics:
    completed = [record for record in resolved_in_window if record.outcome == COMPLETED]
    return WindowMetrics(
        timestamp=str(datetime.fromtimestamp(wall_ns / 1_000_000_000, tz=timezone.utc).replace(tzinfo=None)),
        service_type=identity.service_type,
        container_id=identity.container_id,
        avg_p_latency=average_processing_latency_ms(completed),
        s_config=str(identity.configuration),
        cores=identity.cores,
        rps=rate_per_second,
        throughput=len(completed),
        cooldown=0,
    )


class WindowMetricsReporter:
    def __init__(
        self,
        windows: TickSchedule,
        record_book: RecordBook,
        clock: Clock,
        identity: ServiceIdentity,
        current_rate: Callable[[], float],
        publish: Callable[[WindowMetrics], None],
    ):
        self._windows = windows
        self._record_book = record_book
        self._clock = clock
        self._identity = identity
        self._current_rate = current_rate
        self._publish = publish
        self._records_already_reported = 0
        self._reported: List[WindowMetrics] = []

    def report_due_windows(self) -> None:
        for _ in self._windows.ticks_due(self._clock.monotonic_ns()):
            resolved = self._record_book.records_from(self._records_already_reported)
            self._records_already_reported += len(resolved)
            metrics = metrics_of_window(resolved, self._clock.wall_ns(), self._identity, self._current_rate())
            self._reported.append(metrics)
            self._publish(metrics)

    def next_report_at_ns(self) -> int:
        return self._windows.next_tick_at_ns()

    def reported(self) -> List[WindowMetrics]:
        return list(self._reported)


def write_window_metrics(path: Path, reported: List[WindowMetrics]) -> None:
    with Path(path).open("w", newline="") as metrics_file:
        writer = csv.writer(metrics_file)
        writer.writerow(ELASTIC_WORKBENCH_COLUMNS)
        for metrics in reported:
            writer.writerow(metrics.as_row())
