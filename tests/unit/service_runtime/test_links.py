import threading
import time

from dsg.service_runtime.control_client import ServiceRefused
from dsg.service_runtime.links import HANDOVER_FAILED, NEXT_HOP_UNREACHABLE, SATURATED_LINK, RateLink, RequestLink
from dsg.service_runtime.records import FAILED, WorkerResult
from tests.support import arrived_item, completed_result


class FakeNextHop:
    def __init__(self, refuses=False, holds_until: threading.Event = None):
        self.refuses = refuses
        self.holds_until = holds_until
        self.rates = []
        self.requests = []

    def change_rate(self, rate_per_second, client_id):
        if self.refuses:
            raise ServiceRefused("not there")
        self.rates.append((client_id, rate_per_second))

    def hand_over(self, request_id, request_entered_at_ns, admission_phase, handed_over_by):
        if self.holds_until is not None:
            self.holds_until.wait(timeout=5)
        if self.refuses:
            raise ServiceRefused("409")
        self.requests.append((request_id, request_entered_at_ns, admission_phase, handed_over_by))


def wait_until_idle(link, seconds=5):
    give_up_at = time.monotonic() + seconds
    while not link.is_idle() and time.monotonic() < give_up_at:
        time.sleep(0.005)
    assert link.is_idle()


def request(number, phase="measure"):
    item = arrived_item(number, arrived_at_ns=1000 + number)
    item.admission_phase = phase
    return item


def test_rate_link_tells_every_next_hop_the_finished_items_per_second():
    cv, pc = FakeNextHop(), FakeNextHop()
    link = RateLink("qr", [cv, pc], window_ms=500, on_failure=lambda flag: None)
    link.window_finished(10)
    link.item_finished(request(0), completed_result(0))
    link.nothing_more_comes()
    assert cv.rates == [("qr", 20.0), ("qr", 0.0)]
    assert pc.rates == cv.rates
    assert cv.requests == [] and link.is_idle() and link.handed_over() == 0


def test_rate_link_reports_an_unreachable_next_hop_and_still_tells_the_others():
    failures, cv = [], FakeNextHop()
    RateLink("qr", [FakeNextHop(refuses=True), cv], 1000, failures.append).window_finished(5)
    assert failures == [NEXT_HOP_UNREACHABLE]
    assert cv.rates == [("qr", 5.0)]


def test_request_link_hands_every_finished_request_to_every_next_hop_in_order():
    cv, pc = FakeNextHop(), FakeNextHop()
    link = RequestLink("qr", [cv, pc], on_failure=lambda flag: None)
    for number in range(20):
        link.item_finished(request(number), completed_result(number))
    wait_until_idle(link)
    assert [handed[0] for handed in cv.requests] == [f"node-{number}" for number in range(20)]
    assert cv.requests[3] == ("node-3", 1003, "measure", "qr")
    assert pc.requests == cv.requests
    assert link.handed_over() == 40


def test_request_link_never_makes_the_caller_wait_for_a_slow_next_hop():
    gate = threading.Event()
    link = RequestLink("qr", [FakeNextHop(holds_until=gate)], on_failure=lambda flag: None)
    began = time.monotonic()
    for number in range(50):
        link.item_finished(request(number), completed_result(number))
    assert time.monotonic() - began < 0.5
    assert not link.is_idle()
    gate.set()
    wait_until_idle(link)


def test_a_request_that_failed_or_produced_nothing_ends_here():
    cv = FakeNextHop()
    link = RequestLink("qr", [cv], on_failure=lambda flag: None)
    link.item_finished(request(0), WorkerResult(0, 0, 1, 1, FAILED, 0, 0, "boom"))
    link.item_finished(request(1), WorkerResult(1, 0, 1, 1, "completed", 0, 0))
    link.item_finished(request(2), completed_result(2))
    wait_until_idle(link)
    assert [handed[0] for handed in cv.requests] == ["node-2"]


def test_a_refused_handover_is_reported_and_not_tried_again():
    failures = []
    link = RequestLink("qr", [FakeNextHop(refuses=True)], failures.append)
    link.item_finished(request(0), completed_result(0))
    wait_until_idle(link)
    assert failures == [HANDOVER_FAILED]
    assert link.handed_over() == 0


def test_too_many_requests_waiting_for_a_slow_next_hop_is_saturation():
    gate, failures = threading.Event(), []
    link = RequestLink("qr", [FakeNextHop(holds_until=gate)], failures.append, waiting_at_most=3)
    for number in range(10):
        link.item_finished(request(number), completed_result(number))
    assert SATURATED_LINK in failures
    gate.set()
    wait_until_idle(link)


def test_window_ends_mean_nothing_to_a_request_link():
    cv = FakeNextHop()
    link = RequestLink("qr", [cv], on_failure=lambda flag: None)
    link.window_finished(99)
    link.nothing_more_comes()
    assert cv.rates == [] and cv.requests == [] and link.is_idle()
