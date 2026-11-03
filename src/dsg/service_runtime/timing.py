from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol

LONGEST_SLEEP_NS = 50_000_000


class Clock(Protocol):
    def monotonic_ns(self) -> int: ...

    def wall_ns(self) -> int: ...

    def sleep_until_ns(self, deadline_ns: int) -> None: ...


class SystemClock:
    def monotonic_ns(self) -> int:
        return time.monotonic_ns()

    def wall_ns(self) -> int:
        return time.time_ns()

    def sleep_until_ns(self, deadline_ns: int) -> None:
        remaining_ns = deadline_ns - time.monotonic_ns()
        if remaining_ns > 0:
            time.sleep(remaining_ns / 1_000_000_000)


@dataclass(frozen=True)
class Tick:
    index: int
    planned_at_ns: int


class TickSchedule:
    def __init__(self, period_ns: int, first_tick_at_ns: int):
        self._period_ns = period_ns
        self._first_tick_at_ns = first_tick_at_ns
        self._next_index = 0

    def next_tick_at_ns(self) -> int:
        return self._first_tick_at_ns + self._next_index * self._period_ns

    def ticks_due(self, now_ns: int) -> List[Tick]:
        due = []
        while self.next_tick_at_ns() <= now_ns:
            due.append(Tick(self._next_index, self.next_tick_at_ns()))
            self._next_index += 1
        return due


class DeadlineLoop(threading.Thread):
    def __init__(self, name: str, clock: Clock, act: Callable[[], object], next_deadline_ns: Callable[[], Optional[int]]):
        super().__init__(name=name, daemon=True)
        self._clock = clock
        self._act = act
        self._next_deadline_ns = next_deadline_ns
        self._stop_requested = threading.Event()

    def run(self) -> None:
        while not self._stop_requested.is_set():
            self._act()
            self._clock.sleep_until_ns(self._wake_up_at_ns())

    def stop(self) -> None:
        self._stop_requested.set()

    def _wake_up_at_ns(self) -> int:
        latest_ns = self._clock.monotonic_ns() + LONGEST_SLEEP_NS
        deadline_ns = self._next_deadline_ns()
        return latest_ns if deadline_ns is None else min(deadline_ns, latest_ns)
