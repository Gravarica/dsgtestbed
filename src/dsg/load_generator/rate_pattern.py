from __future__ import annotations

import csv
import math
import random
from pathlib import Path
from typing import Callable, List, Optional

PATTERN_DIRECTORY = Path(__file__).parent / "patterns"
CONSTANT = "constant"
QUIET_SHARE_OF_MEAN = 0.5


class PatternUnknown(Exception):
    pass


class BurstsImpossible(Exception):
    pass


def available_patterns() -> List[str]:
    return [CONSTANT] + sorted(path.stem for path in PATTERN_DIRECTORY.glob("*.csv"))


class Bursts:
    def __init__(self, factor: float, seconds: int, seed: int):
        if factor < 1:
            raise BurstsImpossible(f"burst_factor is how many times the mean rate a burst carries, at least 1, not {factor}")
        if seconds < 1 or int(seconds) != seconds:
            raise BurstsImpossible(f"burst_seconds is a whole number of seconds, at least 1, not {seconds}")
        self.factor = float(factor)
        self.seconds = int(seconds)
        self.period_seconds = self._period_seconds()
        self._burst_starts_at = random.Random(seed).randrange(self.period_seconds)

    def share_of_mean_at(self, second: int) -> float:
        if self.factor == 1:
            return 1.0
        position = (second - self._burst_starts_at) % self.period_seconds
        return self.factor if position < self.seconds else self._quiet_share()

    def _period_seconds(self) -> int:
        if self.factor == 1:
            return 1
        share_of_time_in_bursts = (1 - QUIET_SHARE_OF_MEAN) / (self.factor - QUIET_SHARE_OF_MEAN)
        return max(self.seconds + 1, math.ceil(self.seconds / share_of_time_in_bursts))

    def _quiet_share(self) -> float:
        quiet_seconds = self.period_seconds - self.seconds
        return (self.period_seconds - self.factor * self.seconds) / quiet_seconds


class RatePattern:
    def __init__(
        self,
        name: str,
        peak_rate: float,
        start_second: int = 0,
        speed: float = 1.0,
        bursts: Optional[Bursts] = None,
    ):
        if name not in available_patterns():
            raise PatternUnknown(f"{name} is not one of {available_patterns()}")
        self._peak_rate = peak_rate
        self._start_second = start_second
        self._speed = speed
        self._bursts = bursts
        self._follows_a_trace = name != CONSTANT
        self._shares_of_peak = normalized_trace(PATTERN_DIRECTORY / f"{name}.csv") if self._follows_a_trace else [1.0]

    def rate_at(self, elapsed_seconds: float) -> float:
        position = (self._start_second + int(elapsed_seconds * self._speed)) % len(self._shares_of_peak)
        rate = self._shares_of_peak[position] * self._peak_rate
        if self._bursts is not None:
            return round(rate * self._bursts.share_of_mean_at(int(elapsed_seconds)), 2)
        return float(round(rate)) if self._follows_a_trace else round(rate, 4)


def normalized_trace(trace_file: Path) -> List[float]:
    with trace_file.open() as trace:
        return [float(row["rps_normalized"]) for row in csv.DictReader(trace)]


class RateSetter:
    def __init__(self, pattern: RatePattern, change_rate: Callable[[float], None]):
        self._pattern = pattern
        self._change_rate = change_rate
        self._last_rate: Optional[float] = None
        self.offered_rates: List[float] = []

    def apply(self, elapsed_seconds: float) -> None:
        rate = self._pattern.rate_at(elapsed_seconds)
        self.offered_rates.append(rate)
        if rate != self._last_rate:
            self._change_rate(rate)
            self._last_rate = rate
