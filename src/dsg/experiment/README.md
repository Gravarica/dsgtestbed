# experiment

Runs an experiment file.

- `run_experiment(experiment_file)` — makes `results/<name>/<timestamp>/`, runs every plan, keeps `dataset.csv`
  current after each run.
- `plan` — the experiment file (nodes with settings, edges, load, run) to a shuffled list of `RunPlan`. Every list
  and every range (`{from: 1, to: 4, step: 0.5}`) is a dimension, the load settings included (`rps`, `pattern`,
  `pattern_start_second`, `trace_speed`, `burst_factor`, `burst_seconds`, `arrival_process`). A source node may
  have its own `rps`. `runs: N` keeps a random part of the space: shuffled from the full list when the space has
  at most 200 000 points, drawn point by point when it is larger; points that ask for more cores than the machine
  offers are skipped. `repetitions: R` with `repeated_share: S` repeats only a share S of the runs. Refuses, before
  anything starts: unknown services, bad edges, cycles, knob values outside a spec, unknown settings, load that
  cannot be made, more cores than the machine offers in a full grid.
  `shared_knobs: {data_quality: {from: 160, to: 640, step: 32}}` draws one value per run and gives it to every
  service that has that knob, so a whole chain runs at one quality. A load is given as `rps`, or as `utilization`
  (the busy share of the busiest service): the run then first sends a few requests (`probe_seconds`), reads every
  service's processing time, and sets the rate to utilization ÷ (sources feeding the service × processing time ÷
  min(workers, cores)) of the busiest service. `arrival_process: renewal` with `arrival_variability` (the squared
  coefficient of variation of the gaps: 0 evenly spaced, 1 as Poisson, above 1 irregular) sets how regular the
  arrivals are. `measure_requests: N` measures until about N requests entered, at least `measure_seconds` and at
  most `longest_measure_seconds`.
  `fan_in: join` (needs `link: requests`) makes a service with several feeders wait until every feeder handed
  over the same request, then queue it once (map-reduce, hierarchical FL); the utilization then counts one
  stream through it instead of one per path. `fan_in: each` (the default) queues every handover on its own.
  `cap_cores_at_the_probe: true` (run setting) gives a service that needs more than its probe cores its probe
  cores and lists it in `cores_capped`, instead of an invalid run; its `throttled_fraction` shows what that cost.
  A node with `auto_cores: false` keeps its `cores` under `cpu_slack`: for a service whose own work is tiny
  next to the handing over, CPU per busy second means nothing. With `cpu_slack`, a run whose set cores add up to more than the workload CPUs is invalid
  (`cores_set_above_the_workload_cpus`).
  `cores_may_exceed_the_machine: true` (run setting) lets the core limits of a run add up to more than the
  workload CPUs: limits are caps, not reservations, so services that are not busy at the same time can share.
  `cores_beyond_the_workers: 0.5` (node setting, instead of `cores`) gives the node its drawn `parallelism` plus
  0.5 cores in every run: a busy worker uses about one core, the rest is room for bursts.
- `estimate` — runs, nodes, largest core sum and expected hours of experiment files, without running them
  (`just estimate <files>`). A run is expected to take its load plus 15 s plus 3 s per service.
- `run` — `PipelineRun`, the order of one run for any number of services: compose, start, set knobs, load on the
  first services only, start the last service first, warm up, measure, stop and drain from first to last,
  describe. Updates the rate every second from the load pattern. Names the service in every flag and problem.
- `dataset` — one run folder to one row per service: the settings of every service, the load settings, the rate
  received, validity, latency statistics, throttling, memory; on source rows also the rate offered while measuring
  (`offered_rate_mean`, `offered_rate_cv`). `utilization_asked` is the target of the run and `utilization_measured`
  what every service saw: rate received × mean processing time ÷ min(workers, cores).
- `traces` — only for `link: requests`: joins the records of all services on `request_id` along the edges and
  writes `traces.csv` (one row per request) and `trace_steps.csv` (one row per request and service, with
  `waiting_for_inputs_ms` at a join: last input minus first input), and gives the end-to-end columns for the dataset.
- `summary` — folds the experiment file, the provenance and the dataset of a results folder into `summary.json`;
  for a campaign folder, finds each experiment's results through `status.txt` and lists them. `csv_rows` holds the
  data rows of every csv in the folder, so a copy that was cut off is noticed.
- `provenance` — git commit, dirty flag, hardware.
