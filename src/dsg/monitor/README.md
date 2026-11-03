# monitor

Everything about observing a running service.

- `window_metrics` — the per-window numbers of elastic-workbench (`throughput`, `avg_p_latency`, ...) and its
  `metrics.csv` format.
- `PrometheusExporter` — the elastic-workbench gauges with labels `service_type`, `container_id`, `metric_id`,
  plus `queue_length`, `workers_busy`, `items_*`. Runs in the container on port 8000.
- `PrometheusConnection(url)` — from the host: `is_up`, `query`, `latest_value`, `latest_values`, `scrape_targets`.
- `container_stats` — CPU seconds and quota throttling of a container from its cgroup counters.
- `stack/` with `start_monitor_stack` / `stop_monitor_stack` — Prometheus, cAdvisor, Grafana on local ports.

Monitoring is for watching. The dataset is the per-item `records.csv`, not Prometheus.
