from __future__ import annotations

import itertools
import threading
from typing import Callable, Optional, Protocol

from dsg.service_runtime.item_queue import Item, ItemQueue
from dsg.service_runtime.joins import Joins
from dsg.service_runtime.lifecycle import Lifecycle
from dsg.service_runtime.records import RecordBook, WorkerResult, processing_record
from dsg.service_runtime.timing import Clock


class Workers(Protocol):
    def has_free_worker(self) -> bool: ...

    def busy_workers(self) -> int: ...

    def submit(self, item: Item, on_result: Callable[[Item, WorkerResult], None]) -> None: ...


class ItemFlow:
    def __init__(
        self,
        node_name: str,
        queue: ItemQueue,
        workers: Workers,
        record_book: RecordBook,
        lifecycle: Lifecycle,
        clock: Clock,
        config_id: str,
        sample_count: int,
        on_queue_full: Callable[[], None],
        on_item_finished: Callable[[Item, WorkerResult], None],
        joins: Optional[Joins] = None,
    ):
        self._node_name = node_name
        self._queue = queue
        self._workers = workers
        self._record_book = record_book
        self._lifecycle = lifecycle
        self._clock = clock
        self._config_id = config_id
        self._sample_count = sample_count
        self._on_queue_full = on_queue_full
        self._on_item_finished = on_item_finished
        self._joins = joins if joins is not None else Joins(1)
        self._samples_given_to_handed_over_requests = itertools.count()
        self._item_ids = itertools.count()
        self._admission_guard = threading.Lock()
        self._dispatch_guard = threading.RLock()

    def admit(self, sample_index: int, scheduled_at_ns: int, payload: Optional[bytes] = None) -> Optional[Item]:
        with self._admission_guard:
            if not self._lifecycle.accepts_arrivals():
                return None
            item = self._new_item(sample_index, scheduled_at_ns, payload)
            item.request_id = f"{self._node_name}-{item.item_id}"
            item.request_entered_at_ns = item.arrived_at_ns
            item.admission_phase = self._lifecycle.admission_phase()
            admitted = self._put_in_the_queue(item)
        self._give_released_items_to_free_workers()
        return admitted

    def take_handed_over(self, request_id: str, request_entered_at_ns: int, admission_phase: str, handed_over_by: str) -> bool:
        with self._admission_guard:
            if not self._lifecycle.accepts_arrivals():
                return False
            first_input_at_ns = self._joins.input_arrived(request_id, self._clock.monotonic_ns())
            if first_input_at_ns is None:
                return True
            admitted = self._admit_handed_over(request_id, request_entered_at_ns, admission_phase, handed_over_by, first_input_at_ns)
        self._give_released_items_to_free_workers()
        return admitted is not None

    def admit_handed_over(
        self, request_id: str, request_entered_at_ns: int, admission_phase: str, handed_over_by: str
    ) -> Optional[Item]:
        with self._admission_guard:
            if not self._lifecycle.accepts_arrivals():
                return None
            admitted = self._admit_handed_over(request_id, request_entered_at_ns, admission_phase, handed_over_by, None)
        self._give_released_items_to_free_workers()
        return admitted

    def joins_still_waiting(self) -> int:
        return self._joins.still_waiting()

    def _admit_handed_over(
        self,
        request_id: str,
        request_entered_at_ns: int,
        admission_phase: str,
        handed_over_by: str,
        first_input_at_ns: Optional[int],
    ) -> Optional[Item]:
        sample_index = next(self._samples_given_to_handed_over_requests) % self._sample_count
        item = self._new_item(sample_index, self._clock.monotonic_ns(), None)
        item.request_id = request_id
        item.request_entered_at_ns = request_entered_at_ns
        item.admission_phase = admission_phase
        item.handed_over_by = handed_over_by
        item.first_input_at_ns = item.arrived_at_ns if first_input_at_ns is None else first_input_at_ns
        return self._put_in_the_queue(item)

    def _put_in_the_queue(self, item: Item) -> Optional[Item]:
        if not self._queue.admit(item):
            self._on_queue_full()
            return None
        self._record_book.note_admitted(item)
        return item

    def advance(self) -> None:
        self._queue.release_due_items(self._clock.monotonic_ns())
        self._give_released_items_to_free_workers()

    def next_release_at_ns(self) -> Optional[int]:
        return self._queue.next_release_at_ns()

    def is_drained(self) -> bool:
        nothing_in_progress = self._queue.is_empty() and self._workers.busy_workers() == 0
        return nothing_in_progress and self._record_book.counts()["unresolved"] == 0

    def _new_item(self, sample_index: int, scheduled_at_ns: int, payload: Optional[bytes]) -> Item:
        item_id = next(self._item_ids)
        return Item(
            item_id=item_id,
            request_id="",
            request_entered_at_ns=0,
            handed_over_by="",
            sample_index=sample_index,
            scheduled_at_ns=scheduled_at_ns,
            arrived_at_ns=self._clock.monotonic_ns(),
            admission_phase="",
            queue_length_at_arrival=self._queue.length(),
            workers_busy_at_arrival=self._workers.busy_workers(),
            payload=payload,
        )

    def _give_released_items_to_free_workers(self) -> None:
        with self._dispatch_guard:
            while self._workers.has_free_worker():
                item = self._queue.take_next_released()
                if item is None:
                    return
                self._workers.submit(item, self._record_result)

    def _record_result(self, item: Item, result: WorkerResult) -> None:
        self._record_book.note_resolved(processing_record(item, result, self._config_id))
        self._on_item_finished(item, result)
        self._give_released_items_to_free_workers()
