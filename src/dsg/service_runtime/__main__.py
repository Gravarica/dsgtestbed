from __future__ import annotations

from dsg.monitor.exporter import PrometheusExporter
from dsg.service_runtime.contract import load_service_spec
from dsg.service_runtime.control_api import create_control_app
from dsg.service_runtime.engine import ServiceEngine
from dsg.service_runtime.settings import runtime_settings_from_environment
from dsg.service_runtime.timing import SystemClock
from dsg.service_runtime.workers import limit_native_threads_in_environment


def main() -> None:
    settings = runtime_settings_from_environment()
    limit_native_threads_in_environment(settings.native_threads_per_worker)
    spec = load_service_spec(settings.service_directory)
    exporter = PrometheusExporter(spec.service_type, settings.container_id)
    exporter.serve(settings.metrics_port)
    engine = ServiceEngine(settings, spec, SystemClock(), exporter)
    create_control_app(engine).run(host="0.0.0.0", port=settings.control_port, threaded=True)


if __name__ == "__main__":
    main()
