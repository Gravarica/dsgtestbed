from __future__ import annotations

import threading
from typing import Callable, Dict, List, Optional, Tuple

from dsg.load_generator.arrival_schedule import ArrivalSchedule


class ItemSource:
    def __init__(
        self,
        schedule: ArrivalSchedule,
        admit: Callable[[int, int], object],
        monotonic_ns: Callable[[], int],
        sample_count: int,
    ):
        self._schedule = schedule
        self._admit = admit
        self._monotonic_ns = monotonic_ns
        self._sample_count = sample_count
        self._next_sample_index = 0
        self._rate_by_client: Dict[str, float] = {}
        self._rate_changes: List[Tuple[int, float]] = []
        self._guard = threading.Lock()

    def change_client_rate(self, client_id: str, rate_per_second: float) -> None:
        with self._guard:
            self._rate_by_client[client_id] = rate_per_second
            now_ns = self._monotonic_ns()
            self._schedule.change_rate(self._total_rate(), now_ns)
            self._rate_changes.append((now_ns, self._total_rate()))

    def total_rate(self) -> float:
        with self._guard:
            return self._total_rate()

    def rate_changes(self) -> List[Tuple[int, float]]:
        with self._guard:
            return list(self._rate_changes)

    def emit_due_items(self) -> int:
        emitted = 0
        with self._guard:
            now_ns = self._monotonic_ns()
            while self._is_due(now_ns):
                self._admit(self._next_sample_index, self._schedule.next_deadline_ns())
                self._next_sample_index = (self._next_sample_index + 1) % self._sample_count
                self._schedule.advance()
                emitted += 1
        return emitted

    def next_deadline_ns(self) -> Optional[int]:
        with self._guard:
            return self._schedule.next_deadline_ns()

    def _is_due(self, now_ns: int) -> bool:
        deadline_ns = self._schedule.next_deadline_ns()
        return deadline_ns is not None and deadline_ns <= now_ns

    def _total_rate(self) -> float:
        return sum(self._rate_by_client.values())
