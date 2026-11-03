import csv

import pytest

from dsg.service_runtime.item_flow import ItemFlow
from dsg.service_runtime.item_queue import FIFO, WINDOW, ItemQueue
from dsg.service_runtime.lifecycle import DRAINING, FINISHED, Lifecycle, TransitionRejected
from dsg.service_runtime.records import RecordBook, processing_record, summarize_run, write_processing_records
from tests.support import FakeClock, FakeWorkers, arrived_item, completed_result

SECOND_NS = 1_000_000_000


def build_flow(clock, worker_count=1, discipline=WINDOW, capacity=100, queue_full_calls=None):
    lifecycle = Lifecycle(clock)
    lifecycle.start_warming_up()
    workers = FakeWorkers(worker_count)
    record_book = RecordBook()
    queue = ItemQueue(capacity, discipline, SECOND_NS, 1000, first_window_at_ns=0)
    calls = queue_full_calls if queue_full_calls is not None else []
    finished = []
    flow = ItemFlow(
        "qr", queue, workers, record_book, lifecycle, clock, "config", 3,
        on_queue_full=lambda: calls.append(1),
        on_item_finished=lambda item, result: finished.append(item.request_id),
    )
    flow.finished_requests = finished
    return flow, workers, record_book, lifecycle


def test_arriving_item_sees_the_queue_and_the_busy_workers():
    clock = FakeClock()
    flow, workers, _, _ = build_flow(clock, discipline=FIFO)
    flow.admit(0, scheduled_at_ns=0)
    flow.admit(1, scheduled_at_ns=0)
    third = flow.admit(2, scheduled_at_ns=0)
    assert third.workers_busy_at_arrival == 1
    assert third.queue_length_at_arrival == 1
    assert third.request_id == "qr-2"
    assert third.request_entered_at_ns == third.arrived_at_ns
    assert third.handed_over_by == ""


def test_a_handed_over_request_keeps_its_id_entry_time_and_phase_and_gets_a_sample_of_this_service():
    clock = FakeClock(start_ns=5_000)
    flow, workers, record_book, lifecycle = build_flow(clock, worker_count=4, discipline=FIFO)
    lifecycle.start_measuring()
    lifecycle.start_draining("requested")
    assert flow.admit_handed_over("qr-7", 1_000, "measure", "qr") is None
    flow, workers, record_book, lifecycle = build_flow(clock, worker_count=4, discipline=FIFO)
    items = [flow.admit_handed_over(f"qr-{number}", 1_000 + number, "measure", "qr") for number in range(4)]
    assert [item.request_id for item in items] == ["qr-0", "qr-1", "qr-2", "qr-3"]
    assert items[0].request_entered_at_ns == 1_000
    assert items[0].arrived_at_ns == 5_000
    assert items[0].admission_phase == "measure" and lifecycle.admission_phase() == "warmup"
    assert items[0].handed_over_by == "qr"
    assert [item.sample_index for item in items] == [0, 1, 2, 0]


def test_every_finished_item_is_given_to_the_link():
    flow, workers, _, _ = build_flow(FakeClock(), discipline=FIFO)
    flow.admit(0, scheduled_at_ns=0)
    workers.finish_oldest()
    assert flow.finished_requests == ["qr-0"]


def test_window_items_start_only_after_the_flow_advances_past_a_window():
    clock = FakeClock(start_ns=1)
    flow, workers, _, _ = build_flow(clock)
    flow.admit(0, scheduled_at_ns=0)
    assert workers.submitted_item_ids == []
    flow.advance()
    assert workers.submitted_item_ids == [0]


def test_flow_never_hands_out_more_items_than_free_workers():
    flow, workers, _, _ = build_flow(FakeClock(), worker_count=2, discipline=FIFO)
    for sample_index in range(5):
        flow.admit(sample_index, scheduled_at_ns=0)
    assert workers.submitted_item_ids == [0, 1]


def test_finished_item_is_recorded_and_frees_its_worker_for_the_next_item():
    flow, workers, record_book, _ = build_flow(FakeClock(), discipline=FIFO)
    for sample_index in range(3):
        flow.admit(sample_index, scheduled_at_ns=0)
    workers.finish_oldest()
    assert workers.submitted_item_ids == [0, 1]
    assert [record.item_id for record in record_book.records()] == [0]


def test_flow_is_drained_only_when_queue_workers_and_records_are_settled():
    flow, workers, _, _ = build_flow(FakeClock(), discipline=FIFO)
    flow.admit(0, scheduled_at_ns=0)
    assert not flow.is_drained()
    workers.finish_oldest()
    assert flow.is_drained()


def test_nothing_is_admitted_after_draining_started():
    flow, workers, record_book, lifecycle = build_flow(FakeClock(), discipline=FIFO)
    lifecycle.start_draining("requested")
    assert flow.admit(0, scheduled_at_ns=0) is None
    assert record_book.counts()["admitted"] == 0


def test_full_queue_reports_saturation_and_does_not_admit():
    queue_full_calls = []
    flow, _, record_book, _ = build_flow(FakeClock(), capacity=2, queue_full_calls=queue_full_calls)
    for sample_index in range(5):
        flow.admit(sample_index, scheduled_at_ns=0)
    assert record_book.counts()["admitted"] == 2
    assert len(queue_full_calls) == 3


def test_record_book_reconciles_admitted_against_resolved_items():
    record_book = RecordBook()
    first, second = arrived_item(0), arrived_item(1)
    record_book.note_admitted(first)
    record_book.note_admitted(second)
    record_book.note_resolved(processing_record(first, completed_result(0), "config"))
    assert record_book.counts() == {"admitted": 2, "completed": 1, "failed": 0, "unresolved": 1}
    assert record_book.unresolved_item_ids() == [1]


def test_processing_records_are_written_with_one_row_per_item(tmp_path):
    record = processing_record(arrived_item(0, arrived_at_ns=10), completed_result(0, 20, 50), "abc")
    write_processing_records(tmp_path / "records.csv", [record])
    rows = list(csv.DictReader((tmp_path / "records.csv").open()))
    assert rows[0]["config_id"] == "abc"
    assert int(rows[0]["finished_at_ns"]) - int(rows[0]["started_at_ns"]) == 30
    assert "released_at_ns" in rows[0]
    assert {"request_id", "request_entered_at_ns", "handed_over_by"} <= set(rows[0])


def test_run_summary_flags_a_generator_that_fell_behind():
    late = arrived_item(0, arrived_at_ns=80_000_000)
    late.scheduled_at_ns = 0
    record = processing_record(late, completed_result(0), "c")
    entered = {"measuring": 0, "draining": 2 * SECOND_NS}
    summary = summarize_run([record], entered, [], lateness_tolerance_ms=50, described_run={"flags": []})
    assert summary["flags"] == ["offered_load_late"]
    assert summary["achieved_rate_per_second"] == 0.5


def test_a_backlog_still_waiting_when_the_measurement_ended_means_overload():
    measurement_ended = 10 * SECOND_NS
    waited_long = arrived_item(0, arrived_at_ns=9 * SECOND_NS)
    record = processing_record(waited_long, completed_result(0, started_at_ns=13 * SECOND_NS, finished_at_ns=13 * SECOND_NS + 1), "c")
    entered = {"measuring": 0, "draining": measurement_ended}
    summary = summarize_run([record], entered, [], lateness_tolerance_ms=50, described_run={"flags": []})
    assert summary["flags"] == ["overloaded"]
    assert summary["backlog_seconds_when_measurement_ended"] == 3.0


def test_a_backlog_of_less_than_two_seconds_is_the_window_not_overload():
    measurement_ended = 10 * SECOND_NS
    waited_a_bit = arrived_item(0, arrived_at_ns=9 * SECOND_NS)
    record = processing_record(waited_a_bit, completed_result(0, started_at_ns=11 * SECOND_NS, finished_at_ns=11 * SECOND_NS + 1), "c")
    summary = summarize_run([record], {"measuring": 0, "draining": measurement_ended}, [], 50, {"flags": []})
    assert summary["flags"] == []


def test_lifecycle_follows_the_run_order_and_refuses_shortcuts():
    lifecycle = Lifecycle(FakeClock())
    with pytest.raises(TransitionRejected):
        lifecycle.start_measuring()
    lifecycle.start_warming_up()
    assert lifecycle.admission_phase() == "warmup"
    lifecycle.start_measuring()
    assert lifecycle.admission_phase() == "measure"
    lifecycle.start_draining("requested")
    assert not lifecycle.accepts_arrivals()
    lifecycle.finish()
    assert lifecycle.state() == FINISHED


def test_saturation_is_kept_as_a_flag_and_a_second_stop_is_harmless():
    lifecycle = Lifecycle(FakeClock())
    lifecycle.start_warming_up()
    lifecycle.start_draining("saturated_queue")
    lifecycle.start_draining("requested")
    assert lifecycle.state() == DRAINING
    assert lifecycle.flags() == ["saturated_queue"]
    assert lifecycle.stop_reason() == "saturated_queue"


def test_record_book_tells_the_mean_processing_time_of_its_most_recent_completed_items():
    record_book = RecordBook()
    assert record_book.recent_processing_ms() is None
    for item_id, processing_ns in enumerate((10_000_000, 20_000_000, 30_000_000)):
        item = arrived_item(item_id)
        record_book.note_admitted(item)
        record_book.note_resolved(processing_record(item, completed_result(item_id, 0, processing_ns), "config"))
    assert record_book.recent_processing_ms() == 20.0
    assert record_book.recent_processing_ms(most_items=2) == 25.0


def test_a_join_queues_a_request_once_every_feeder_handed_it_over_and_keeps_when_the_first_came():
    from dsg.service_runtime.joins import Joins

    clock = FakeClock(start_ns=1_000)
    lifecycle = Lifecycle(clock)
    lifecycle.start_warming_up()
    workers = FakeWorkers(0)
    queue = ItemQueue(100, FIFO, SECOND_NS, 1000, first_window_at_ns=0)
    flow = ItemFlow("merge", queue, workers, RecordBook(), lifecycle, clock, "config", 3,
                    on_queue_full=lambda: None, on_item_finished=lambda item, result: None, joins=Joins(2))
    assert flow.take_handed_over("camera-0", 500, "measure", "left")
    assert queue.length() == 0 and flow.joins_still_waiting() == 1
    clock.advance_ms(0.004)
    assert flow.take_handed_over("camera-0", 500, "measure", "right")
    assert queue.length() == 1 and flow.joins_still_waiting() == 0
    item = queue.take_next_released()
    assert item.first_input_at_ns == 1_000 and item.arrived_at_ns == 5_000 and item.handed_over_by == "right"


def test_without_a_join_every_handover_is_queued_and_its_first_input_is_its_arrival():
    clock = FakeClock(start_ns=2_000)
    flow, workers, _, _ = build_flow(clock, worker_count=0, discipline=FIFO)
    assert flow.take_handed_over("qr-1", 500, "measure", "qr")
    assert flow.take_handed_over("qr-1", 500, "measure", "pc")
    assert flow.joins_still_waiting() == 0


def test_a_record_holds_when_the_first_input_came():
    item = arrived_item(0, arrived_at_ns=10)
    assert processing_record(item, completed_result(0, 20, 50), "abc").first_input_at_ns == 10
    item.first_input_at_ns = 4
    assert processing_record(item, completed_result(0, 20, 50), "abc").first_input_at_ns == 4
