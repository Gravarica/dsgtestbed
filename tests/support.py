from __future__ import annotations

from typing import Callable, List, Tuple

from dsg.service_runtime.item_queue import Item
from dsg.service_runtime.records import COMPLETED, WorkerResult


class FakeClock:
    def __init__(self, start_ns: int = 0):
        self.now_ns = start_ns

    def monotonic_ns(self) -> int:
        return self.now_ns

    def wall_ns(self) -> int:
        return 1_700_000_000_000_000_000 + self.now_ns

    def sleep_until_ns(self, deadline_ns: int) -> None:
        self.now_ns = max(self.now_ns, deadline_ns)

    def advance_ms(self, milliseconds: float) -> None:
        self.now_ns += round(milliseconds * 1_000_000)


class FakeWorkers:
    def __init__(self, worker_count: int):
        self.worker_count = worker_count
        self.running: List[Tuple[Item, Callable]] = []
        self.submitted_item_ids: List[int] = []

    def has_free_worker(self) -> bool:
        return len(self.running) < self.worker_count

    def busy_workers(self) -> int:
        return len(self.running)

    def submit(self, item: Item, on_result: Callable[[Item, WorkerResult], None]) -> None:
        self.running.append((item, on_result))
        self.submitted_item_ids.append(item.item_id)

    def finish_oldest(self, started_at_ns: int = 0, finished_at_ns: int = 1) -> None:
        item, on_result = self.running.pop(0)
        on_result(item, completed_result(item.item_id, started_at_ns, finished_at_ns))


def completed_result(item_id: int, started_at_ns: int = 0, finished_at_ns: int = 1) -> WorkerResult:
    return WorkerResult(item_id, started_at_ns, finished_at_ns, 1, COMPLETED, 1, 0)


def arrived_item(item_id: int, arrived_at_ns: int = 0) -> Item:
    return Item(
        item_id=item_id,
        request_id=f"node-{item_id}",
        request_entered_at_ns=arrived_at_ns,
        handed_over_by="",
        sample_index=0,
        scheduled_at_ns=arrived_at_ns,
        arrived_at_ns=arrived_at_ns,
        admission_phase="measure",
        queue_length_at_arrival=0,
        workers_busy_at_arrival=0,
    )
