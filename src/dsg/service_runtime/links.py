from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Protocol

from dsg.service_runtime.control_client import ControlClient, ServiceRefused
from dsg.service_runtime.item_queue import Item
from dsg.service_runtime.records import COMPLETED, WorkerResult

RATES = "rates"
REQUESTS = "requests"
LINK_KINDS = (RATES, REQUESTS)
MILLISECONDS_PER_SECOND = 1000
SECONDS_TO_WAIT_FOR_A_NEXT_HOP = 2.0
REQUESTS_WAITING_TO_BE_HANDED_OVER_AT_MOST = 10000

NEXT_HOP_UNREACHABLE = "next_hop_unreachable"
HANDOVER_FAILED = "handover_failed"
SATURATED_LINK = "saturated_link"


class Link(Protocol):
    def window_finished(self, items_finished_in_window: int) -> None: ...

    def item_finished(self, item: Item, result: WorkerResult) -> None: ...

    def nothing_more_comes(self) -> None: ...

    def is_idle(self) -> bool: ...

    def handed_over(self) -> int: ...


@dataclass(frozen=True)
class Handover:
    request_id: str
    request_entered_at_ns: int
    admission_phase: str
    handed_over_by: str


class RateLink:
    def __init__(self, node_name: str, next_hops: List[ControlClient], window_ms: int, on_failure: Callable[[str], None]):
        self._node_name = node_name
        self._next_hops = next_hops
        self._window_ms = window_ms
        self._on_failure = on_failure

    def window_finished(self, items_finished_in_window: int) -> None:
        self._tell_next_hops(items_finished_in_window * MILLISECONDS_PER_SECOND / self._window_ms)

    def item_finished(self, item: Item, result: WorkerResult) -> None:
        return None

    def nothing_more_comes(self) -> None:
        self._tell_next_hops(0.0)

    def is_idle(self) -> bool:
        return True

    def handed_over(self) -> int:
        return 0

    def _tell_next_hops(self, rate_per_second: float) -> None:
        for next_hop in self._next_hops:
            try:
                next_hop.change_rate(rate_per_second, client_id=self._node_name)
            except (ServiceRefused, OSError):
                self._on_failure(NEXT_HOP_UNREACHABLE)


class RequestLink:
    def __init__(
        self,
        node_name: str,
        next_hops: List[ControlClient],
        on_failure: Callable[[str], None],
        waiting_at_most: int = REQUESTS_WAITING_TO_BE_HANDED_OVER_AT_MOST,
    ):
        self._node_name = node_name
        self._on_failure = on_failure
        self._not_yet_handed_over = 0
        self._handed_over = 0
        self._guard = threading.Lock()
        self._outboxes: List[queue.Queue] = [queue.Queue(maxsize=waiting_at_most) for _ in next_hops]
        for outbox, next_hop in zip(self._outboxes, next_hops):
            threading.Thread(target=self._hand_over_from, args=(outbox, next_hop), daemon=True).start()

    def window_finished(self, items_finished_in_window: int) -> None:
        return None

    def item_finished(self, item: Item, result: WorkerResult) -> None:
        if result.outcome != COMPLETED or result.output_count < 1:
            return
        handover = Handover(item.request_id, item.request_entered_at_ns, item.admission_phase, self._node_name)
        for outbox in self._outboxes:
            self._count_waiting(+1)
            try:
                outbox.put_nowait(handover)
            except queue.Full:
                self._count_waiting(-1)
                self._on_failure(SATURATED_LINK)

    def nothing_more_comes(self) -> None:
        return None

    def is_idle(self) -> bool:
        with self._guard:
            return self._not_yet_handed_over == 0

    def handed_over(self) -> int:
        with self._guard:
            return self._handed_over

    def _hand_over_from(self, outbox: queue.Queue, next_hop: ControlClient) -> None:
        while True:
            handover = outbox.get()
            try:
                next_hop.hand_over(
                    handover.request_id, handover.request_entered_at_ns, handover.admission_phase, handover.handed_over_by
                )
                delivered = 1
            except (ServiceRefused, OSError):
                delivered = 0
                self._on_failure(HANDOVER_FAILED)
            with self._guard:
                self._handed_over += delivered
                self._not_yet_handed_over -= 1

    def _count_waiting(self, change: int) -> None:
        with self._guard:
            self._not_yet_handed_over += change


def link_named(
    kind: str, node_name: str, next_hop_urls: List[str], window_ms: int, on_failure: Callable[[str], None]
) -> Link:
    next_hops = [ControlClient(url, SECONDS_TO_WAIT_FOR_A_NEXT_HOP) for url in next_hop_urls]
    if kind == REQUESTS:
        return RequestLink(node_name, next_hops, on_failure)
    return RateLink(node_name, next_hops, window_ms, on_failure)
