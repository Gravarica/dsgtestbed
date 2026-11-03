from __future__ import annotations

import random
from typing import Optional

NANOSECONDS_PER_SECOND = 1_000_000_000
ARRIVAL_PROCESSES = ("poisson", "deterministic", "renewal")
POISSON_VARIABILITY = 1.0


class ArrivalSchedule:
    def __init__(self, arrival_process: str, seed: int, variability: float = POISSON_VARIABILITY):
        if arrival_process not in ARRIVAL_PROCESSES:
            raise ValueError(f"arrival process must be one of {ARRIVAL_PROCESSES}")
        if variability < 0:
            raise ValueError(f"variability is the squared coefficient of variation of the gaps, at least 0, not {variability}")
        self._arrival_process = arrival_process
        self._variability = variability
        self._random = random.Random(seed)
        self._rate_per_second = 0.0
        self._next_deadline_ns: Optional[int] = None

    def change_rate(self, rate_per_second: float, now_ns: int) -> None:
        self._rate_per_second = rate_per_second
        if rate_per_second <= 0:
            self._next_deadline_ns = None
            return
        after_one_new_gap_ns = now_ns + self._gap_ns()
        already_planned_ns = self._next_deadline_ns
        self._next_deadline_ns = (
            after_one_new_gap_ns if already_planned_ns is None else min(already_planned_ns, after_one_new_gap_ns)
        )

    def next_deadline_ns(self) -> Optional[int]:
        return self._next_deadline_ns

    def advance(self) -> None:
        if self._next_deadline_ns is not None:
            self._next_deadline_ns += self._gap_ns()

    def _gap_ns(self) -> int:
        mean_gap_seconds = 1 / self._rate_per_second
        if self._arrival_process == "deterministic" or (self._arrival_process == "renewal" and self._variability == 0):
            return round(mean_gap_seconds * NANOSECONDS_PER_SECOND)
        if self._arrival_process == "renewal":
            shape = 1 / self._variability
            return round(self._random.gammavariate(shape, mean_gap_seconds / shape) * NANOSECONDS_PER_SECOND)
        return round(self._random.expovariate(self._rate_per_second) * NANOSECONDS_PER_SECOND)
