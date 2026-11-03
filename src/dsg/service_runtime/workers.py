from __future__ import annotations

import multiprocessing
import os
import sys
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from dsg.service_runtime.contract import WorkItem, load_service_module, outputs_from, size_in_bytes
from dsg.service_runtime.item_queue import Item
from dsg.service_runtime.records import COMPLETED, FAILED, WorkerResult

WARM_UP_HOLD_SECONDS = 0.5
THREAD_COUNT_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


class WorkersFailedToStart(Exception):
    pass


class WorkerPool:
    def __init__(
        self,
        service_directory: Path,
        configuration: Dict[str, Any],
        parallelism: int,
        native_threads_per_worker: int,
        warm_up_sample_indexes: List[int],
    ):
        self._service_directory = Path(service_directory)
        self._configuration = configuration
        self._parallelism = parallelism
        self._native_threads_per_worker = native_threads_per_worker
        self._warm_up_sample_indexes = warm_up_sample_indexes
        self._busy_workers = 0
        self._guard = threading.Lock()
        self._executor: Optional[ProcessPoolExecutor] = None

    def start(self) -> List[Dict[str, Any]]:
        limit_native_threads_in_environment(self._native_threads_per_worker)
        self._executor = ProcessPoolExecutor(
            max_workers=self._parallelism,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=initialize_worker,
            initargs=(str(self._service_directory), self._configuration, self._native_threads_per_worker),
        )
        return self._warm_up_every_worker()

    def has_free_worker(self) -> bool:
        with self._guard:
            return self._busy_workers < self._parallelism

    def busy_workers(self) -> int:
        with self._guard:
            return self._busy_workers

    def submit(self, item: Item, on_result: Callable[[Item, WorkerResult], None]) -> None:
        with self._guard:
            self._busy_workers += 1
        future = self._executor.submit(process_item, item.item_id, item.sample_index, item.payload)
        future.add_done_callback(lambda finished: self._hand_back(item, finished, on_result))

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)

    def _hand_back(self, item: Item, finished: Future, on_result: Callable[[Item, WorkerResult], None]) -> None:
        with self._guard:
            self._busy_workers -= 1
        on_result(item, self._result_of(item, finished))

    def _result_of(self, item: Item, finished: Future) -> WorkerResult:
        try:
            return finished.result()
        except Exception as error:
            now_ns = time.monotonic_ns()
            return WorkerResult(item.item_id, now_ns, now_ns, 0, FAILED, 0, 0, repr(error))

    def _warm_up_every_worker(self) -> List[Dict[str, Any]]:
        warm_ups = [
            self._executor.submit(warm_up_worker, self._warm_up_sample_indexes, WARM_UP_HOLD_SECONDS)
            for _ in range(self._parallelism)
        ]
        reports = [warm_up.result() for warm_up in warm_ups]
        started_workers = {report["worker_id"] for report in reports}
        if len(started_workers) != self._parallelism:
            raise WorkersFailedToStart(f"{len(started_workers)} of {self._parallelism} workers started")
        return reports


def limit_native_threads_in_environment(threads_per_worker: int) -> None:
    for variable in THREAD_COUNT_VARIABLES:
        os.environ[variable] = str(threads_per_worker)


def limit_native_threads_in_loaded_libraries(threads_per_worker: int) -> Dict[str, int]:
    effective = {variable: int(os.environ.get(variable, 0)) for variable in THREAD_COUNT_VARIABLES}
    if "cv2" in sys.modules:
        sys.modules["cv2"].setNumThreads(threads_per_worker)
        effective["opencv"] = sys.modules["cv2"].getNumThreads()
    if "torch" in sys.modules:
        sys.modules["torch"].set_num_threads(threads_per_worker)
        effective["torch"] = sys.modules["torch"].get_num_threads()
    return effective


@dataclass
class LoadedService:
    module: ModuleType
    cfg: SimpleNamespace
    state: Any
    native_threads: Dict[str, int]


_loaded_service: Optional[LoadedService] = None


def initialize_worker(service_directory: str, configuration: Dict[str, Any], threads_per_worker: int) -> None:
    global _loaded_service
    module = load_service_module(Path(service_directory))
    cfg = SimpleNamespace(
        **configuration,
        service_directory=Path(service_directory),
        native_threads_per_worker=threads_per_worker,
    )
    native_threads = limit_native_threads_in_loaded_libraries(threads_per_worker)
    state = module.init_worker(cfg) if hasattr(module, "init_worker") else None
    _loaded_service = LoadedService(module, cfg, state, native_threads)


def warm_up_worker(sample_indexes: List[int], hold_seconds: float) -> Dict[str, Any]:
    for sample_index in sample_indexes:
        _loaded_service.module.process(WorkItem(sample_index, None), _loaded_service.cfg, _loaded_service.state)
    time.sleep(hold_seconds)
    return {"worker_id": os.getpid(), "native_threads": _loaded_service.native_threads}


def process_item(item_id: int, sample_index: int, payload: Optional[bytes]) -> WorkerResult:
    work_item = WorkItem(sample_index, payload)
    started_at_ns = time.monotonic_ns()
    try:
        returned = _loaded_service.module.process(work_item, _loaded_service.cfg, _loaded_service.state)
    except Exception as error:
        return WorkerResult(item_id, started_at_ns, time.monotonic_ns(), os.getpid(), FAILED, 0, 0, repr(error))
    finished_at_ns = time.monotonic_ns()
    outputs = outputs_from(returned)
    bytes_out = sum(size_in_bytes(output) for output in outputs)
    return WorkerResult(item_id, started_at_ns, finished_at_ns, os.getpid(), COMPLETED, len(outputs), bytes_out)
