# dsg-testbed — Architecture

The testbed is one Python package, `dsg`, with one sub-package per component. Each sub-package has a `README.md`
with its purpose and its public functions.

```
                         just  ->  dsg (cli.py)
                                      |
                     service_verifier                   is this service built right, does it work, how does it behave
                                      |
                                  experiment            experiment file -> runs -> dataset
                 _____________________|______________________
                |              |              |              |
        service_generator  service_composer  monitor   load_generator
        folder -> image    what to deploy    observe    when items
                           -> Compose file   a service  arrive
                |______________|______________|
                          docker_host                   the only module that calls Docker

  inside every service container:
        service_runtime   (uses load_generator for arrivals and monitor for metrics)
              wraps   services/<name>/<version>/service.py
```

Dependencies point downward only. Only `service_verifier` and `cli` use `experiment`; nothing imports `cli`.

## Components

| Package | Purpose | Main entry points |
|---|---|---|
| `service_runtime` | Runs inside the container. Queue, window batching, workers, per-item records, run sequence, the elastic-workbench control API. | `python -m dsg.service_runtime`, `ControlClient`, `ServiceSpec` |
| `service_generator` | Service folder to checked image. Home of generated services later. | `new_service`, `build`, `check`, `list_services` |
| `service_composer` | `topology`: nodes, edges, order, cycle check. `compose`: a Compose file for any number of services with limits, ports and next hops. | `topology_of`, `compose_for_pipeline`, `NodeDeployment` |
| `load_generator` | When items arrive: arrival schedule, item source, elastic-workbench rate traces. | `ArrivalSchedule`, `ItemSource`, `RatePattern`, `RateSetter` |
| `monitor` | Observing a service: per-window metrics, Prometheus gauges, Prometheus queries, container CPU, the monitoring stack. | `PrometheusExporter`, `PrometheusConnection`, `start_monitor_stack` |
| `service_verifier` | The testbed's judgement of a service: static checks, build, own tests, short trial runs on a closed network, the verification report. | `verify`, `status_of` |
| `experiment` | The experiment file (nodes, settings to explore, edges, link, load, run) to run plans; the order of one pipeline run; dataset rows per service; the path of every request (`traces`); `summary.json` per results or campaign folder; provenance. | `run_experiment`, `PipelineRun`, `write_traces`, `write_summary` |
| `docker_host`, `node`, `repository`, `cli` | Docker calls, `node.yaml`, repo paths, the `dsg` command. | |

## Inside `service_runtime`

| Module | Purpose | Hides |
|---|---|---|
| `contract` | what a service is: `spec.yaml`, knobs, `WorkItem`, `Outputs`, loading `service.py` | validation rules, harness knob defaults |
| `configuration` | knob values, locked while processing, config id | locking, hashing |
| `item_queue` | the one queue, with the discipline inside | the window rule, batch size, FIFO versus window |
| `item_flow` | the path of an item: admit, wait, release, process, record | ids, arrival snapshots, when workers get items |
| `workers` | worker processes | spawn, warm-up, one native thread per worker, timestamps, failures |
| `records` | one row per item, counts, run summary | reconciliation of admitted and resolved items |
| `lifecycle` | idle, warming_up, measuring, draining, finished, flags | allowed transitions |
| `engine` | builds the parts, runs the sequence, writes the files | threads, the drain rule |
| `endpoints`, `control_api`, `control_client` | the REST surface and its client | endpoint names live in `endpoints` only |
| `links` | how a service is connected to the services after it, both ways side by side: `RateLink` and `RequestLink` | what is sent, when, without making anyone wait, and what a failure means |
| `timing`, `settings` | clock, ticks, thread loop; environment variables | |

## The path of an item

`item_source` plans an arrival → `item_flow.admit` stamps it and puts it in `item_queue` → a window tick releases
up to `batch_size` items → a free worker runs `process()` and stamps start and finish → `records` keeps the row →
at the end of the run `engine` writes `records.csv`, `metrics.csv`, `run_summary.json`.

## How services are chained

`experiment.plan` reads nodes, edges and `link:` → `service_composer` gives every container the addresses of its
next hops → in the container, `links` builds the link the file asked for. Load from outside goes only to services
that nobody feeds.

- `link: rates`: at the end of each window `RateLink` sends the finished count to every next hop's `/change_rps`;
  their `item_source` uses the sum of what all feeders sent as its arrival rate.
- `link: requests`: for each finished item `RequestLink` puts a handover into a sending buffer per next hop; a
  sender calls the next hop's `/handover`; `item_flow` admits it under the same `request_id`. After the run,
  `experiment.traces` joins the records of all services on `request_id` along the edges.

## Other folders

`procedures/` the texts an assistant or a person follows: one service, a batch, an application ·
`services/` service store · `experiments/` one YAML file per experiment · `results/` run output, not in git ·
`tests/unit/` same package names, no Docker, no network · `tests/integration/` one real container run.
