from dsg.monitor.container_stats import cpu_seconds_used, cpu_stat_from_text, throttled_fraction
from dsg.monitor.exporter import PrometheusExporter
from dsg.monitor.window_metrics import (
    ELASTIC_WORKBENCH_COLUMNS,
    ServiceIdentity,
    WindowMetricsReporter,
    metrics_of_window,
    write_window_metrics,
)
from dsg.service_runtime.records import RecordBook, processing_record
from dsg.service_runtime.timing import TickSchedule
from tests.support import FakeClock, arrived_item, completed_result

QR = ServiceIdentity("elastic-workbench-qr-detector", "qr-1", {"data_quality": 550, "parallelism": 1}, 2.0)
MILLISECOND_NS = 1_000_000


def two_completed_records():
    return [
        processing_record(arrived_item(0), completed_result(0, 0, 20 * MILLISECOND_NS), "c"),
        processing_record(arrived_item(1), completed_result(1, 0, 40 * MILLISECOND_NS), "c"),
    ]


def test_window_metrics_match_the_elastic_workbench_columns(tmp_path):
    metrics = metrics_of_window(two_completed_records(), 1_700_000_000_000_000_000, QR, 80)
    assert metrics.avg_p_latency == 30
    assert metrics.throughput == 2
    assert metrics.s_config == "{'data_quality': 550, 'parallelism': 1}"
    write_window_metrics(tmp_path / "metrics.csv", [metrics])
    assert (tmp_path / "metrics.csv").read_text().splitlines()[0] == ",".join(ELASTIC_WORKBENCH_COLUMNS)


def test_window_without_completions_reports_minus_one_like_elastic_workbench():
    metrics = metrics_of_window([], 0, QR, 10)
    assert (metrics.avg_p_latency, metrics.throughput) == (-1, 0)


def test_reporter_counts_each_record_in_exactly_one_window():
    clock = FakeClock()
    record_book = RecordBook()
    published = []
    reporter = WindowMetricsReporter(
        TickSchedule(1000 * MILLISECOND_NS, first_tick_at_ns=1000 * MILLISECOND_NS),
        record_book, clock, QR, lambda: 40, published.append,
    )
    for record in two_completed_records():
        record_book.note_resolved(record)
    clock.advance_ms(1000)
    reporter.report_due_windows()
    clock.advance_ms(1000)
    reporter.report_due_windows()
    assert [metrics.throughput for metrics in published] == [2, 0]


def test_exporter_publishes_the_elastic_workbench_gauges_with_their_labels():
    exporter = PrometheusExporter("elastic-workbench-qr-detector", "qr-1")
    exporter.publish_configuration({"data_quality": 550, "discipline": "window"})
    exporter.publish_window(metrics_of_window(two_completed_records(), 0, QR, 80))
    labels = {"service_type": "elastic-workbench-qr-detector", "container_id": "qr-1"}
    assert exporter.registry.get_sample_value("throughput", {**labels, "metric_id": "throughput"}) == 2
    assert exporter.registry.get_sample_value("avg_p_latency", {**labels, "metric_id": "avg_p_latency"}) == 30
    assert exporter.registry.get_sample_value("data_quality", {**labels, "metric_id": "data_quality"}) == 550


def test_cpu_stat_text_gives_throttling_and_cpu_use():
    before = cpu_stat_from_text("usage_usec 1000000\nnr_periods 100\nnr_throttled 10\n")
    after = cpu_stat_from_text("usage_usec 3500000\nnr_periods 300\nnr_throttled 60\n")
    assert throttled_fraction(before, after) == 0.25
    assert cpu_seconds_used(before, after) == 2.5
    assert throttled_fraction({}, {}) == 0.0
