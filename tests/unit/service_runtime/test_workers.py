import threading

import pytest

from dsg.service_runtime.records import COMPLETED, FAILED
from dsg.service_runtime.workers import WorkerPool
from tests.support import arrived_item

DUMMY_SERVICE = """
import time
import helper_module
from dsg.service_runtime.contract import Outputs


def init_worker(cfg):
    assert cfg.native_threads_per_worker == 1
    return {"copies": helper_module.COPIES_FACTOR * cfg.copies}


def process(item, cfg, state):
    if item.sample_index == 99:
        raise RuntimeError("bad sample")
    time.sleep(0.01)
    if item.sample_index == 50:
        return None
    if item.sample_index == 60:
        return Outputs([b"a", b"bb", b"ccc"])
    return b"x" * state["copies"]
"""


@pytest.fixture
def service_directory(tmp_path):
    (tmp_path / "service.py").write_text(DUMMY_SERVICE)
    (tmp_path / "helper_module.py").write_text("COPIES_FACTOR = 1\n")
    return tmp_path


def process_in_pool(pool, sample_indexes):
    results = {}
    all_done = threading.Event()

    def collect(item, result):
        results[item.sample_index] = result
        if len(results) == len(sample_indexes):
            all_done.set()

    for item_id, sample_index in enumerate(sample_indexes):
        item = arrived_item(item_id)
        item.sample_index = sample_index
        pool.submit(item, collect)
    assert all_done.wait(timeout=30)
    return results


def test_every_worker_is_started_and_warmed_before_the_pool_is_ready(service_directory):
    pool = WorkerPool(service_directory, {"copies": 4}, 2, 1, [0, 1])
    reports = pool.start()
    pool.shutdown()
    assert len({report["worker_id"] for report in reports}) == 2
    assert reports[0]["native_threads"]["OMP_NUM_THREADS"] == 1


def test_worker_stamps_start_and_finish_around_the_service_function(service_directory):
    pool = WorkerPool(service_directory, {"copies": 4}, 1, 1, [0])
    pool.start()
    result = process_in_pool(pool, [0])[0]
    pool.shutdown()
    assert result.outcome == COMPLETED
    assert result.finished_at_ns - result.started_at_ns >= 10_000_000
    assert result.bytes_out == 4
    assert pool.busy_workers() == 0


def test_no_output_several_outputs_and_failures_are_told_apart(service_directory):
    pool = WorkerPool(service_directory, {"copies": 1}, 1, 1, [0])
    pool.start()
    results = process_in_pool(pool, [50, 60, 99])
    pool.shutdown()
    assert (results[50].outcome, results[50].output_count) == (COMPLETED, 0)
    assert (results[60].output_count, results[60].bytes_out) == (3, 6)
    assert results[99].outcome == FAILED
    assert "bad sample" in results[99].error
