from __future__ import annotations

import csv
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

from dsg.service_runtime.item_queue import FiredWindow, Item
from dsg.service_runtime.lifecycle import DRAINING, MEASURING

COMPLETED = "completed"
FAILED = "failed"
NANOSECONDS_PER_MILLISECOND = 1_000_000
NANOSECONDS_PER_SECOND = 1_000_000_000
RECENT_ITEMS = 20


@dataclass(frozen=True)
class WorkerResult:
    item_id: int
    started_at_ns: int
    finished_at_ns: int
    worker_id: int
    outcome: str
    output_count: int
    bytes_out: int
    error: str = ""


@dataclass(frozen=True)
class ProcessingRecord:
    item_id: int
    request_id: str
    request_entered_at_ns: int
    handed_over_by: str
    config_id: str
    admission_phase: str
    sample_index: int
    window_index: Optional[int]
    scheduled_at_ns: int
    arrived_at_ns: int
    released_at_ns: Optional[int]
    started_at_ns: int
    finished_at_ns: int
    worker_id: int
    outcome: str
    output_count: int
    bytes_in: int
    bytes_out: int
    queue_length_at_arrival: int
    workers_busy_at_arrival: int
    error: str
    first_input_at_ns: int


def processing_record(item: Item, result: WorkerResult, config_id: str) -> ProcessingRecord:
    return ProcessingRecord(
        item_id=item.item_id,
        request_id=item.request_id,
        request_entered_at_ns=item.request_entered_at_ns,
        handed_over_by=item.handed_over_by,
        config_id=config_id,
        admission_phase=item.admission_phase,
        sample_index=item.sample_index,
        window_index=item.window_index,
        scheduled_at_ns=item.scheduled_at_ns,
        arrived_at_ns=item.arrived_at_ns,
        released_at_ns=item.released_at_ns,
        started_at_ns=result.started_at_ns,
        finished_at_ns=result.finished_at_ns,
        worker_id=result.worker_id,
        outcome=result.outcome,
        output_count=result.output_count,
        bytes_in=item.payload_size(),
        bytes_out=result.bytes_out,
        queue_length_at_arrival=item.queue_length_at_arrival,
        workers_busy_at_arrival=item.workers_busy_at_arrival,
        error=result.error,
        first_input_at_ns=item.arrived_at_ns if item.first_input_at_ns is None else item.first_input_at_ns,
    )


class RecordBook:
    def __init__(self):
        self._admitted: Dict[int, Item] = {}
        self._records: List[ProcessingRecord] = []
        self._guard = threading.Lock()

    def note_admitted(self, item: Item) -> None:
        with self._guard:
            self._admitted[item.item_id] = item

    def note_resolved(self, record: ProcessingRecord) -> None:
        with self._guard:
            self._admitted.pop(record.item_id, None)
            self._records.append(record)

    def records(self) -> List[ProcessingRecord]:
        with self._guard:
            return list(self._records)

    def records_from(self, position: int) -> List[ProcessingRecord]:
        with self._guard:
            return list(self._records[position:])

    def unresolved_item_ids(self) -> List[int]:
        with self._guard:
            return sorted(self._admitted)

    def recent_processing_ms(self, most_items: int = RECENT_ITEMS) -> Optional[float]:
        with self._guard:
            recent = [record for record in self._records if record.outcome == COMPLETED][-most_items:]
        if not recent:
            return None
        return sum(record.finished_at_ns - record.started_at_ns for record in recent) / len(recent) / NANOSECONDS_PER_MILLISECOND

    def counts(self) -> Dict[str, int]:
        with self._guard:
            completed = sum(1 for record in self._records if record.outcome == COMPLETED)
            return {
                "admitted": len(self._records) + len(self._admitted),
                "completed": completed,
                "failed": len(self._records) - completed,
                "unresolved": len(self._admitted),
            }


def write_processing_records(path: Path, records: List[ProcessingRecord]) -> None:
    column_names = [field.name for field in fields(ProcessingRecord)]
    with Path(path).open("w", newline="") as records_file:
        writer = csv.DictWriter(records_file, fieldnames=column_names)
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))


def percentile(sorted_values: List[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    return sorted_values[min(len(sorted_values) - 1, round(fraction * (len(sorted_values) - 1)))]


def arrival_lateness_ms(records: List[ProcessingRecord]) -> Dict[str, float]:
    lateness = sorted((record.arrived_at_ns - record.scheduled_at_ns) / NANOSECONDS_PER_MILLISECOND for record in records)
    return {"median": percentile(lateness, 0.5), "p99": percentile(lateness, 0.99), "max": lateness[-1] if lateness else 0.0}


def window_lateness_ms(fired_windows: List[FiredWindow]) -> Dict[str, float]:
    lateness = sorted((window.fired_at_ns - window.planned_at_ns) / NANOSECONDS_PER_MILLISECOND for window in fired_windows)
    return {"median": percentile(lateness, 0.5), "max": lateness[-1] if lateness else 0.0}


def achieved_rate_per_second(measured: List[ProcessingRecord], entered_at_ns: Dict[str, int]) -> float:
    if MEASURING not in entered_at_ns or DRAINING not in entered_at_ns:
        return 0.0
    measured_seconds = (entered_at_ns[DRAINING] - entered_at_ns[MEASURING]) / NANOSECONDS_PER_SECOND
    return len(measured) / measured_seconds if measured_seconds > 0 else 0.0


BACKLOG_THAT_MEANS_OVERLOAD_SECONDS = 2.0


def backlog_seconds_when_measurement_ended(records: List[ProcessingRecord], entered_at_ns: Dict[str, int]) -> float:
    if DRAINING not in entered_at_ns:
        return 0.0
    measurement_ended_ns = entered_at_ns[DRAINING]
    still_waiting = [record for record in records if record.arrived_at_ns <= measurement_ended_ns < record.started_at_ns]
    if not still_waiting:
        return 0.0
    last_started_ns = max(record.started_at_ns for record in still_waiting)
    return (last_started_ns - measurement_ended_ns) / NANOSECONDS_PER_SECOND


def summarize_run(
    records: List[ProcessingRecord],
    entered_at_ns: Dict[str, int],
    fired_windows: List[FiredWindow],
    lateness_tolerance_ms: float,
    described_run: Dict[str, Any],
) -> Dict[str, Any]:
    measured = [record for record in records if record.admission_phase == "measure"]
    lateness = arrival_lateness_ms(measured)
    backlog_seconds = backlog_seconds_when_measurement_ended(records, entered_at_ns)
    flags = list(described_run.get("flags", []))
    if lateness["p99"] > lateness_tolerance_ms:
        flags.append("offered_load_late")
    if backlog_seconds > BACKLOG_THAT_MEANS_OVERLOAD_SECONDS:
        flags.append("overloaded")
    return {
        **described_run,
        "flags": flags,
        "measured_items": len(measured),
        "achieved_rate_per_second": achieved_rate_per_second(measured, entered_at_ns),
        "arrival_lateness_ms": lateness,
        "backlog_seconds_when_measurement_ended": round(backlog_seconds, 3),
        "window_lateness_ms": window_lateness_ms(fired_windows),
        "lifecycle_entered_at_ns": entered_at_ns,
    }
