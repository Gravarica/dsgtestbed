from dsg.service_runtime.item_queue import FIFO, WINDOW, ItemQueue
from dsg.service_runtime.timing import TickSchedule
from tests.support import arrived_item

MILLISECOND_NS = 1_000_000
SECOND_NS = 1000 * MILLISECOND_NS


def window_queue(capacity=100, batch_size=1000):
    return ItemQueue(capacity, WINDOW, SECOND_NS, batch_size, first_window_at_ns=0)


def test_queue_refuses_items_beyond_capacity():
    queue = window_queue(capacity=2)
    assert queue.admit(arrived_item(0))
    assert queue.admit(arrived_item(1))
    assert not queue.admit(arrived_item(2))


def test_nothing_can_start_before_a_window_releases_it():
    queue = window_queue()
    queue.admit(arrived_item(0))
    assert queue.take_next_released() is None
    queue.release_due_items(now_ns=0)
    assert queue.take_next_released().item_id == 0


def test_queue_length_counts_waiting_and_released_items():
    queue = window_queue(batch_size=2)
    for item_id in range(4):
        queue.admit(arrived_item(item_id))
    queue.release_due_items(now_ns=0)
    assert queue.length() == 4
    queue.take_next_released()
    assert queue.length() == 3


def test_released_items_are_stamped_with_time_and_window():
    queue = window_queue()
    queue.admit(arrived_item(0))
    queue.release_due_items(now_ns=7)
    item = queue.take_next_released()
    assert (item.released_at_ns, item.window_index) == (7, 0)


def test_each_window_releases_one_batch_and_earlier_items_keep_priority():
    queue = window_queue(batch_size=2)
    for item_id in range(5):
        queue.admit(arrived_item(item_id))
    queue.release_due_items(now_ns=0)
    assert queue.take_next_released().item_id == 0
    queue.release_due_items(now_ns=SECOND_NS)
    assert [queue.take_next_released().item_id for _ in range(3)] == [1, 2, 3]
    assert queue.take_next_released() is None
    assert [window.items_released for window in queue.fired_windows()] == [2, 2]


def test_a_late_window_is_recorded_with_its_lateness():
    queue = window_queue()
    queue.release_due_items(now_ns=30 * MILLISECOND_NS)
    fired = queue.fired_windows()[0]
    assert fired.fired_at_ns - fired.planned_at_ns == 30 * MILLISECOND_NS


def test_fifo_releases_every_item_on_arrival_and_has_no_windows():
    queue = ItemQueue(100, FIFO, SECOND_NS, 1000, first_window_at_ns=0)
    queue.admit(arrived_item(0, arrived_at_ns=5))
    assert queue.next_release_at_ns() is None
    item = queue.take_next_released()
    assert (item.released_at_ns, item.window_index) == (5, None)


def test_tick_schedule_reports_every_missed_tick_when_late():
    ticks = TickSchedule(SECOND_NS, first_tick_at_ns=0)
    due = ticks.ticks_due(2500 * MILLISECOND_NS)
    assert [tick.index for tick in due] == [0, 1, 2]
    assert ticks.ticks_due(2900 * MILLISECOND_NS) == []
    assert ticks.next_tick_at_ns() == 3 * SECOND_NS

