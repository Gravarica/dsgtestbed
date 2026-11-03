# service_runtime

Runs inside every service container. It wraps `services/<name>/<version>/service.py` and does everything else:
arrivals, the queue, window batching, the workers, the timestamps, the run sequence and the control API.

**Used from outside**
- `python -m dsg.service_runtime` is the container entry point.
- `ControlClient(base_url)` drives a running service: `change_knob`, `change_rate`, `start_processing`,
  `start_measurement`, `stop_processing`, `status`.
- `load_service_spec(directory)` returns the `ServiceSpec` of a service folder.

**A service author writes**
`init_worker(cfg) -> state` and `process(item, cfg, state) -> output`. `item.sample_index` selects the sample.
Return one output, `None`, or `Outputs([...])`. No threads, no network, no timing. Helper files next to
`service.py` can be imported by name. `cfg.native_threads_per_worker` is the thread budget for libraries that
manage their own threads, such as ONNX Runtime.

**The window rule** (in `item_queue`, nowhere else)
Every `window_ms` a tick releases up to `batch_size` waiting items. Released items keep their order. Free workers
take them. Unfinished items continue in the next window. `discipline: fifo` releases each item on arrival.

**The run sequence** (in `engine` and `lifecycle`)
idle → `start_processing` locks the knobs and warms every worker → warming_up → `start_measurement` → measuring →
`stop_processing` stops arrivals → draining until every admitted item is resolved → files written → finished.
A full queue stops arrivals by itself and flags the run `saturated_queue`.

**Chaining** (in `links`, nowhere else)
`NEXT_HOPS` holds the addresses of the services after this one, `LINK` says how to talk to them.
- `rates`: at the end of every window the service tells each next hop how many items it finished, as `/change_rps`
  with its own node name as the client. Rates from several feeders add up. When it has finished, it tells them zero.
- `requests`: every item that finished well and produced an output is handed to each next hop through
  `PUT /handover`, from a sending buffer, so no worker and no caller waits. The handover carries the `request_id`,
  the time the request entered the pipeline, its phase and who hands it over. No retries. A service is drained
  only when its sending buffers are empty.
- `JOIN_INPUTS=N` (in `joins`): a handed-over request is queued only when N feeders handed it over, as one item.
  `first_input_at_ns` in `records.csv` is when the first came, `arrived_at_ns` when the last came. Requests still
  waiting when the run ends are counted in `joins_never_completed`.

**Kept from elastic-workbench**
Endpoint names, knob names, port 8080, client rates that add up, rate updates while processing.
