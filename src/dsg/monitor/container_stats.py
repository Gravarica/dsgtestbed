from __future__ import annotations

from typing import Dict


def cpu_stat_from_text(text: str) -> Dict[str, int]:
    stat = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            stat[parts[0]] = int(parts[1])
    return stat


def throttled_fraction(before: Dict[str, int], after: Dict[str, int]) -> float:
    periods = after.get("nr_periods", 0) - before.get("nr_periods", 0)
    throttled = after.get("nr_throttled", 0) - before.get("nr_throttled", 0)
    return throttled / periods if periods > 0 else 0.0


def cpu_seconds_used(before: Dict[str, int], after: Dict[str, int]) -> float:
    return (after.get("usage_usec", 0) - before.get("usage_usec", 0)) / 1_000_000
