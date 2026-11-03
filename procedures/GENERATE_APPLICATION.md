# Generate an application

You are building one application on the dsg testbed: several services connected into a pipeline or a graph,
verified, with an experiment file ready to explore, and a first measured run. You may be an AI assistant or a
person. Read `README.md` in the repository root first, then `SERVICE_CONTRACT.md` and `GENERATE_SERVICE.md` in
this folder. You will follow `GENERATE_SERVICE.md` once for every new stage.

The person decides what the application does. You decide how it is built. After step 2 the person is not asked
anything.

## What you may touch

The folders of the new services, `services/<name>/<version>/`, one new experiment file under `experiments/`, and
the results it produces. Never edit an existing service version, `src/`, `tests/` or the `justfile`.
Verification refuses a service if anything else changed.

## Before you start

- `just services` must show every existing service as `verified`.
- Nothing else may be running: `docker ps` shows no `dsg-` containers and `tmux ls` shows no `campaign`
  session. Experiments share the machine's ports and CPUs.
- `git status` shows no uncommitted changes under `src/` or `tests/`.

## Step 1 — Interview

Ask these five questions, one at a time, each with your own suggestion so the person can say yes or correct it.

1. **What does the application do, end to end?** One or two sentences. For example "processes camera frames
   from a vehicle: reads codes, detects objects, blurs faces, and indexes the result".
2. **What are its stages, and what flows between them?** Propose the stages yourself from the answer to
   question 1, in order or as a graph, and say for each what it receives and what it produces, in the
   application's terms. Three to six stages is a good size.
3. **Which stages already exist?** Look at `just services` and the `brief.yaml` of each service. Propose which
   existing services fit which stage and which stages are new. Plain processing stages are as good as models.
4. **How should the stages be chained?** `requests` follows every request from the first stage to the last and
   gives end-to-end times; `rates` is the elastic-workbench way and gives per-service numbers only. Suggest
   `requests` unless the person has a reason.
5. **How much machine time may the exploration take?** Give the arithmetic: runs times about 90 seconds, plus
   about a minute per run for every stage that loads a model.

Write the answers as the application description and show it:

```yaml
name: vehicle-camera
purpose: Processes camera frames from a vehicle and indexes what was seen.
stages:
  - {name: codes, does: reads QR codes in the frame, receives: a frame, produces: decoded texts, service: qr-detector v1}
  - {name: objects, does: detects objects in the frame, receives: a frame, produces: boxes with labels, service: cv-analyzer v1}
  - {name: blur, does: blurs every face in the frame, receives: a frame with face boxes, produces: a blurred frame, service: new}
  - {name: index, does: indexes the labels and texts for search, receives: labels and texts, produces: an index record, service: new}
edges: [codes -> objects, objects -> blur, blur -> index]
link: requests
budget_minutes: 90
```

Ask: "Is this the application?" Change it until the answer is yes.

## Step 2 — Briefs for the new stages, shown once

For every stage marked `new`, write a brief in the format of `GENERATE_SERVICE.md`, yourself: task, data,
knobs, limits. The task must say what the stage receives and produces in the application's terms. Reuse sample
data already in the repository where the stage works on the same kind of input; name the source service.
Give each new service a name that says what it does, not the application name.

Show all briefs together, once, and ask: "Shall I build these?" This is the last question. Take corrections,
then continue without the person.

## Step 3 — Generate the new stages, one at a time

For each new stage, in pipeline order:

1. `just new-service <name>` and replace its `brief.yaml` with the brief from step 2.
2. Follow `GENERATE_SERVICE.md` from its step 3: write, build, check, `just verify`, fix, up to 8 verify runs.
3. Do not start the next stage before this one is `verified`.

If a stage cannot be verified honestly, stop. Report which stage failed and why, leave its folder as it is,
and do not build the experiment. An application with a missing stage is not an application.

## Step 4 — The experiment file

Write `experiments/<application name>.yaml`:

- `nodes`: one per stage, named as in the description, `service: <name> <version>`.
- `edges` and `link` from the description.
- `cores`: for each stage one more than its largest `parallelism`.
- `load.rps`: three levels for the first stage. Read each stage's `verification_report.json`; the pipeline's
  capacity is the smallest `safe_rate_per_second` along it. Use about a quarter, a half and the whole of that.
- The space: two or three settings per stage that matter for it, two or three values each: `cores`,
  `parallelism`, and its own knobs. Do not vary `memory`.
- `run`: `warmup_seconds: 10`, `measure_seconds: 60`, `runs: N`, `seed: 1`. Choose N from the budget:
  one run is about 90 seconds plus a minute per stage that loads a model.

Check it before running: `python -c "from dsg.experiment.plan import *; from dsg.node import *; from dsg.repository import NODE_FILE; print(len(run_plans(load_experiment('experiments/<name>.yaml'), load_node_settings(NODE_FILE).workload_cpu_count())))"`
must print N without an error.

## Step 5 — Smoke run

Copy the file to `experiments/<application name>-smoke.yaml` with `runs: 1` and `measure_seconds: 20`, and
run it: `just run experiments/<application name>-smoke.yaml`. It takes two or three minutes. Check in its
`summary.json`: `outcome.valid` is 1, every stage has `items` close to the requests that entered, and with
`link: requests` every trace passed all stages. If not, find out why before spending the budget: a stage that
cannot keep up at the lowest load needs a lower `load.rps`; a stage that fails needs fixing as in step 3.
Delete the smoke file and its results folder when it passed.

## Step 6 — Exploration

```bash
tmux new -s campaign
just run experiments/<application name>.yaml
```

Detach and wait. `results/<application name>/<time>/summary.json` appears at the end.

## Step 7 — Report

Tell the person, in plain words:

- the application and its stages, which were reused and which were generated, with tool and model;
- for each generated stage: verified or failed, processing time at default settings;
- from `summary.json`: runs, valid and invalid with their flags, end-to-end mean and 99th percentile across
  valid runs, and the one or two settings that moved the time most;
- the paths: the experiment file, the results folder, the `summary.json`.

Leave everything as it is. A later change to a stage is a new version folder; a later experiment is a new file.
