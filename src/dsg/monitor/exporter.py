from __future__ import annotations

from typing import Any, Dict

from prometheus_client import CollectorRegistry, Gauge, start_http_server

from dsg.monitor.window_metrics import WindowMetrics

ELASTIC_WORKBENCH_LABELS = ["service_type", "container_id", "metric_id"]


class PrometheusExporter:
    def __init__(self, service_type: str, container_id: str):
        self.registry = CollectorRegistry()
        self._service_type = service_type
        self._container_id = container_id
        self._gauges: Dict[str, Gauge] = {}

    def serve(self, port: int) -> None:
        start_http_server(port, registry=self.registry)

    def publish_window(self, metrics: WindowMetrics) -> None:
        self._set("throughput", metrics.throughput)
        self._set("avg_p_latency", metrics.avg_p_latency)
        self._set("cores", metrics.cores)
        self._set("rps", metrics.rps)

    def publish_configuration(self, configuration: Dict[str, Any]) -> None:
        for knob_name, value in configuration.items():
            if isinstance(value, (int, float)):
                self._set(knob_name, value)

    def publish_progress(self, queue_length: int, workers_busy: int, counts: Dict[str, int]) -> None:
        self._set("queue_length", queue_length)
        self._set("workers_busy", workers_busy)
        for count_name, count in counts.items():
            self._set(f"items_{count_name}", count)

    def _set(self, metric_name: str, value: float) -> None:
        if metric_name not in self._gauges:
            self._gauges[metric_name] = Gauge(metric_name, metric_name, ELASTIC_WORKBENCH_LABELS, registry=self.registry)
        self._gauges[metric_name].labels(
            service_type=self._service_type, container_id=self._container_id, metric_id=metric_name
        ).set(value)
