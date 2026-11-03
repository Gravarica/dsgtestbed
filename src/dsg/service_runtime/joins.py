from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class InputsSoFar:
    count: int
    first_at_ns: int


class Joins:
    def __init__(self, inputs: int):
        if inputs < 1:
            raise ValueError(f"a join waits for at least 1 input, not {inputs}")
        self._inputs = inputs
        self._waiting: Dict[str, InputsSoFar] = {}
        self._guard = threading.Lock()

    def inputs(self) -> int:
        return self._inputs

    def input_arrived(self, request_id: str, now_ns: int) -> Optional[int]:
        with self._guard:
            so_far = self._waiting.setdefault(request_id, InputsSoFar(0, now_ns))
            so_far.count += 1
            if so_far.count < self._inputs:
                return None
            del self._waiting[request_id]
            return so_far.first_at_ns

    def still_waiting(self) -> int:
        with self._guard:
            return len(self._waiting)
