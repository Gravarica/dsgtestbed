from __future__ import annotations

import threading
from typing import Dict, List, Optional

from dsg.service_runtime.timing import Clock

IDLE = "idle"
WARMING_UP = "warming_up"
MEASURING = "measuring"
DRAINING = "draining"
FINISHED = "finished"

ALLOWED_TRANSITIONS = {
    IDLE: (WARMING_UP,),
    WARMING_UP: (MEASURING, DRAINING),
    MEASURING: (DRAINING,),
    DRAINING: (FINISHED,),
    FINISHED: (),
}


class TransitionRejected(Exception):
    pass


class Lifecycle:
    def __init__(self, clock: Clock):
        self._clock = clock
        self._state = IDLE
        self._entered_at_ns: Dict[str, int] = {IDLE: clock.monotonic_ns()}
        self._stop_reason: Optional[str] = None
        self._flags: List[str] = []
        self._guard = threading.Lock()

    def state(self) -> str:
        with self._guard:
            return self._state

    def start_warming_up(self) -> None:
        self._move_to(WARMING_UP)

    def start_measuring(self) -> None:
        self._move_to(MEASURING)

    def start_draining(self, reason: str) -> None:
        with self._guard:
            if self._state == DRAINING:
                return
            self._transition(DRAINING)
            self._stop_reason = reason
            if reason != "requested":
                self._flags.append(reason)

    def finish(self) -> None:
        self._move_to(FINISHED)

    def accepts_arrivals(self) -> bool:
        return self.state() in (WARMING_UP, MEASURING)

    def admission_phase(self) -> str:
        return "measure" if self.state() == MEASURING else "warmup"

    def raise_flag(self, flag: str) -> None:
        with self._guard:
            if flag not in self._flags:
                self._flags.append(flag)

    def flags(self) -> List[str]:
        with self._guard:
            return list(self._flags)

    def stop_reason(self) -> Optional[str]:
        with self._guard:
            return self._stop_reason

    def entered_at_ns(self) -> Dict[str, int]:
        with self._guard:
            return dict(self._entered_at_ns)

    def _move_to(self, target: str) -> None:
        with self._guard:
            self._transition(target)

    def _transition(self, target: str) -> None:
        if target not in ALLOWED_TRANSITIONS[self._state]:
            raise TransitionRejected(f"cannot go from {self._state} to {target}")
        self._state = target
        self._entered_at_ns[target] = self._clock.monotonic_ns()
