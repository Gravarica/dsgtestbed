from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional

from dsg.service_runtime.timing import TickSchedule

WINDOW = "window"
FIFO = "fifo"


@dataclass
class Item:
    item_id: int
    request_id: str
    request_entered_at_ns: int
    handed_over_by: str
    sample_index: int
    scheduled_at_ns: int
    arrived_at_ns: int
    admission_phase: str
    queue_length_at_arrival: int
    workers_busy_at_arrival: int
    payload: Optional[bytes] = None
    released_at_ns: Optional[int] = None
    window_index: Optional[int] = None
    first_input_at_ns: Optional[int] = None

    def payload_size(self) -> int:
        return len(self.payload) if self.payload is not None else 0


@dataclass(frozen=True)
class FiredWindow:
    window_index: int
    planned_at_ns: int
    fired_at_ns: int
    items_released: int


class ItemQueue:
    def __init__(self, capacity: int, discipline: str, window_ns: int, batch_size: int, first_window_at_ns: int):
        self._capacity = capacity
        self._releases_on_arrival = discipline == FIFO
        self._batch_size = batch_size
        self._windows = TickSchedule(window_ns, first_window_at_ns)
        self._waiting: Deque[Item] = deque()
        self._released: Deque[Item] = deque()
        self._fired_windows: List[FiredWindow] = []
        self._guard = threading.Lock()

    def admit(self, item: Item) -> bool:
        with self._guard:
            if len(self._waiting) + len(self._released) >= self._capacity:
                return False
            if self._releases_on_arrival:
                item.released_at_ns = item.arrived_at_ns
                self._released.append(item)
            else:
                self._waiting.append(item)
            return True

    def release_due_items(self, now_ns: int) -> None:
        if self._releases_on_arrival:
            return
        with self._guard:
            for window in self._windows.ticks_due(now_ns):
                released = self._release_one_batch(now_ns, window.index)
                self._fired_windows.append(FiredWindow(window.index, window.planned_at_ns, now_ns, released))

    def next_release_at_ns(self) -> Optional[int]:
        return None if self._releases_on_arrival else self._windows.next_tick_at_ns()

    def take_next_released(self) -> Optional[Item]:
        with self._guard:
            return self._released.popleft() if self._released else None

    def length(self) -> int:
        with self._guard:
            return len(self._waiting) + len(self._released)

    def is_empty(self) -> bool:
        return self.length() == 0

    def fired_windows(self) -> List[FiredWindow]:
        with self._guard:
            return list(self._fired_windows)

    def _release_one_batch(self, now_ns: int, window_index: int) -> int:
        released = 0
        while self._waiting and released < self._batch_size:
            item = self._waiting.popleft()
            item.released_at_ns = now_ns
            item.window_index = window_index
            self._released.append(item)
            released += 1
        return released
