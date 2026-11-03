from __future__ import annotations

import json
import threading
from typing import Any, Callable, Dict, List, Optional

from dsg.load_generator.arrival_schedule import ArrivalSchedule
from dsg.load_generator.item_source import ItemSource
from dsg.monitor.exporter import PrometheusExporter
from dsg.monitor.window_metrics import ServiceIdentity, WindowMetrics, WindowMetricsReporter, write_window_metrics
from dsg.service_runtime.configuration import Configuration
from dsg.service_runtime.contract import ServiceSpec
from dsg.service_runtime.item_flow import ItemFlow
from dsg.service_runtime.item_queue import ItemQueue
from dsg.service_runtime.joins import Joins
from dsg.service_runtime.lifecycle import Lifecycle
from dsg.service_runtime.links import SATURATED_LINK, Link, link_named
from dsg.service_runtime.records import RecordBook, summarize_run, write_processing_records
from dsg.service_runtime.settings import RuntimeSettings
from dsg.service_runtime.timing import Clock, DeadlineLoop, TickSchedule
from dsg.service_runtime.workers import WorkerPool

NANOSECONDS_PER_MILLISECOND = 1_000_000
NANOSECONDS_PER_SECOND = 1_000_000_000
DRAIN_POLL_NS = 20_000_000


class ServiceEngine:
    def __init__(
        self,
        settings: RuntimeSettings,
        spec: ServiceSpec,
        clock: Clock,
        exporter: PrometheusExporter,
        create_worker_pool: Callable[..., WorkerPool] = WorkerPool,
    ):
        self._settings = settings
        self._spec = spec
        self._clock = clock
        self._exporter = exporter
        self._create_worker_pool = create_worker_pool
        self._configuration = Configuration(spec.all_knobs())
        self._lifecycle = Lifecycle(clock)
        self._record_book = RecordBook()
        self._client_rates: Dict[str, float] = dict(settings.default_client_rates)
        self._clock_anchor = {"wall_ns": clock.wall_ns(), "monotonic_ns": clock.monotonic_ns()}
        self._loops: List[DeadlineLoop] = []
        self._worker_reports: List[Dict[str, Any]] = []
        self._queue: Optional[ItemQueue] = None
        self._workers: Optional[WorkerPool] = None
        self._flow: Optional[ItemFlow] = None
        self._source: Optional[ItemSource] = None
        self._reporter: Optional[WindowMetricsReporter] = None
        self._link: Optional[Link] = None
        self._exporter.publish_configuration(self._configuration.values())

    def change_knob(self, knob_name: str, raw_value: Any) -> Any:
        accepted_value = self._configuration.change(knob_name, raw_value)
        self._exporter.publish_configuration(self._configuration.values())
        return accepted_value

    def change_client_rate(self, client_id: str, rate_per_second: float) -> None:
        self._client_rates[client_id] = rate_per_second
        if self._source is not None:
            self._source.change_client_rate(client_id, rate_per_second)

    def start_processing(self) -> None:
        self._lifecycle.start_warming_up()
        self._configuration.lock()
        configuration = self._configuration.values()
        self._workers = self._create_worker_pool(
            self._settings.service_directory,
            configuration,
            configuration["parallelism"],
            self._settings.native_threads_per_worker,
            list(range(min(self._settings.warm_up_items_per_worker, self._spec.sample_count))),
        )
        self._worker_reports = self._workers.start()
        self._assemble(configuration)
        self._start_loops()

    def admit_handed_over(self, request_id: str, request_entered_at_ns: int, admission_phase: str, handed_over_by: str) -> bool:
        if self._flow is None:
            return False
        return self._flow.take_handed_over(request_id, request_entered_at_ns, admission_phase, handed_over_by)

    def start_measuring(self) -> None:
        self._lifecycle.start_measuring()

    def stop_processing(self, reason: str = "requested") -> None:
        self._lifecycle.start_draining(reason)
        threading.Thread(target=self._drain_then_finish, name="drain", daemon=True).start()

    def knobs(self) -> Dict[str, Any]:
        return self._configuration.values()

    def status(self) -> Dict[str, Any]:
        return {
            "state": self._lifecycle.state(),
            "flags": self._lifecycle.flags(),
            "config_id": self._configuration.identifier(),
            "queue_length": self._queue.length() if self._queue else 0,
            "workers_busy": self._workers.busy_workers() if self._workers else 0,
            "rate_per_second": sum(self._client_rates.values()),
            "next_hops": self._settings.next_hop_urls,
            "link": self._settings.link_kind,
            **self._record_book.counts(),
            "recent_processing_ms": self._record_book.recent_processing_ms(),
        }

    def _assemble(self, configuration: Dict[str, Any]) -> None:
        window_ns = configuration["window_ms"] * NANOSECONDS_PER_MILLISECOND
        now_ns = self._clock.monotonic_ns()
        self._queue = ItemQueue(
            self._settings.queue_capacity, configuration["discipline"], window_ns, configuration["batch_size"], now_ns
        )
        self._link = link_named(
            self._settings.link_kind,
            self._settings.node_name,
            self._settings.next_hop_urls,
            configuration["window_ms"],
            on_failure=self._note_link_failure,
        )
        self._flow = ItemFlow(
            self._settings.node_name,
            self._queue,
            self._workers,
            self._record_book,
            self._lifecycle,
            self._clock,
            self._configuration.identifier(),
            self._spec.sample_count,
            on_queue_full=lambda: self.stop_processing("saturated_queue"),
            on_item_finished=self._link.item_finished,
            joins=Joins(self._settings.join_inputs),
        )
        self._source = ItemSource(
            ArrivalSchedule(self._settings.arrival_process, self._settings.arrival_seed, self._settings.arrival_variability),
            self._flow.admit,
            self._clock.monotonic_ns,
            self._spec.sample_count,
        )
        self._reporter = WindowMetricsReporter(
            TickSchedule(window_ns, now_ns + window_ns),
            self._record_book,
            self._clock,
            ServiceIdentity(self._spec.service_type, self._settings.container_id, configuration, self._settings.cores),
            self._source.total_rate,
            self._publish_window,
        )
        for client_id, rate_per_second in self._client_rates.items():
            self._source.change_client_rate(client_id, rate_per_second)

    def _start_loops(self) -> None:
        self._loops = [
            DeadlineLoop("item-source", self._clock, self._source.emit_due_items, self._source.next_deadline_ns),
            DeadlineLoop("item-flow", self._clock, self._flow.advance, self._flow.next_release_at_ns),
            DeadlineLoop("window-metrics", self._clock, self._reporter.report_due_windows, self._reporter.next_report_at_ns),
        ]
        for loop in self._loops:
            loop.start()

    def _note_link_failure(self, flag: str) -> None:
        if flag == SATURATED_LINK:
            self.stop_processing(flag)
        else:
            self._lifecycle.raise_flag(flag)

    def _publish_window(self, metrics: WindowMetrics) -> None:
        self._link.window_finished(metrics.throughput)
        self._exporter.publish_window(metrics)
        self._exporter.publish_progress(self._queue.length(), self._workers.busy_workers(), self._record_book.counts())

    def _drain_then_finish(self) -> None:
        give_up_at_ns = self._clock.monotonic_ns() + round(self._settings.drain_timeout_seconds * NANOSECONDS_PER_SECOND)
        while not (self._flow.is_drained() and self._link.is_idle()):
            if self._clock.monotonic_ns() > give_up_at_ns:
                self._lifecycle.raise_flag("drain_timeout")
                break
            self._clock.sleep_until_ns(self._clock.monotonic_ns() + DRAIN_POLL_NS)
        for loop in self._loops:
            loop.stop()
        self._reporter.report_due_windows()
        self._link.nothing_more_comes()
        self._write_run_files()
        self._lifecycle.finish()
        self._workers.shutdown()

    def _write_run_files(self) -> None:
        directory = self._settings.records_directory
        directory.mkdir(parents=True, exist_ok=True)
        records = self._record_book.records()
        write_processing_records(directory / "records.csv", records)
        write_window_metrics(directory / "metrics.csv", self._reporter.reported())
        summary = summarize_run(
            records,
            self._lifecycle.entered_at_ns(),
            self._queue.fired_windows(),
            self._settings.lateness_tolerance_ms,
            self._described_run(),
        )
        (directory / "run_summary.json").write_text(json.dumps(summary, indent=2))

    def _described_run(self) -> Dict[str, Any]:
        return {
            "node_name": self._settings.node_name,
            "service": f"{self._spec.name}:{self._spec.version}",
            "service_type": self._spec.service_type,
            "container_id": self._settings.container_id,
            "configuration": self._configuration.values(),
            "config_id": self._configuration.identifier(),
            "cores": self._settings.cores,
            "arrival_process": self._settings.arrival_process,
            "arrival_seed": self._settings.arrival_seed,
            "arrival_variability": self._settings.arrival_variability,
            "rate_changes": [{"at_ns": at_ns, "rate_per_second": rate} for at_ns, rate in self._source.rate_changes()],
            "queue_capacity": self._settings.queue_capacity,
            "link": self._settings.link_kind,
            "requests_handed_over": self._link.handed_over(),
            "join_inputs": self._settings.join_inputs,
            "joins_never_completed": self._flow.joins_still_waiting(),
            "stop_reason": self._lifecycle.stop_reason(),
            "flags": self._lifecycle.flags(),
            "counts": self._record_book.counts(),
            "unresolved_item_ids": self._record_book.unresolved_item_ids(),
            "workers": self._worker_reports,
            "clock_anchor": self._clock_anchor,
        }
