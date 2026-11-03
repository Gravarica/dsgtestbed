# What a service is

A service is one folder: `services/<name>/<version>/`. It can be anything that processes items: a model, or
plain processing such as compressing, filtering, parsing, sorting or converting. The testbed wraps it, feeds it items, measures every
item, and never looks inside it. This file is everything a service author needs to know.

## The files

| File | Required | Purpose |
|---|---|---|
| `brief.yaml` | yes | what was asked for: task, data, knobs, limits. Written before any code. Never changed afterwards. |
| `spec.yaml` | yes | name, version, data types, number of samples, knobs with ranges |
| `service.py` | yes | the two functions below |
| `test_service.py` | yes | proves the service does its job. Runs inside the image. |
| `requirements.txt` | yes | Python packages, each pinned to a version. May be empty. |
| `data/` | yes | the sample data the service works on |
| `prepare.sh` | no | downloads or creates what is too large for git. Runs on the host before the build. |
| `apt.txt` | no | system packages, one per line |
| other `.py` files | no | helpers. `service.py` imports them by name. |
| `generation.yaml` | yes | who and what wrote the service, and the proof in one sentence. Written at the end. |
| `verification_report.json` | never by you | written by `just verify` |

## `spec.yaml`

```yaml
name: text-recognizer            # same as the folder name
version: v1
service_type: text-recognizer    # label used in metrics
input: any                       # "any" means: the service works on its own sample data
output: text                     # a word for what comes out: image, text, json, bytes. Never "any".
sample_count: 60                 # how many samples init_worker loads
knobs:
  data_quality: {type: int, min: 100, max: 1000, default: 500}
  scale:        {type: float, min: 0.5, max: 2.0, default: 1.0}
  mode:         {type: choice, values: [fast, exact], default: fast}
```

These knob names belong to the testbed and may not be declared: `parallelism`, `discipline`, `window_ms`,
`batch_size`. Use the names `data_quality` and `model_size` when a knob means input quality or model choice,
because existing tools know these names.

## `service.py`

```python
def init_worker(cfg):
    ...
    return state

def process(item, cfg, state):
    ...
    return output
```

**`init_worker(cfg)`** runs once in every worker process, before any item. Load the samples here, and anything
else the work needs, for example a model or a lookup table, and return them. Whatever you return is handed to every `process` call as `state`.

**`process(item, cfg, state)`** runs once per item. This is the only code whose time is measured.

| Name | What it holds |
|---|---|
| `cfg.<knob name>` | the value of each knob for this run. Knobs never change during a run. |
| `cfg.service_directory` | path of the service folder inside the image. Find `data/` and models through it. |
| `cfg.native_threads_per_worker` | how many threads a library may use. Give it to libraries that manage their own threads, for example ONNX Runtime session options. OpenCV, NumPy and PyTorch are already limited for you. |
| `item.sample_index` | which sample to process, from 0 to `sample_count - 1` |
| `item.payload` | `None` for now. Later: data sent by another service. |

Return one output, or `None` for no output, or `Outputs([a, b, c])` for several
(`from dsg.service_runtime.contract import Outputs`). A plain list counts as one output.

## Rules for `init_worker` and `process`

1. **No threads and no processes of your own.** The testbed decides how much runs in parallel.
2. **No network.** Verification runs the service on a closed network. Only `prepare.sh` may download.
3. **No timing, no metrics, no printing per item, no writing files.** The testbed measures.
4. **Do not change the samples.** If you draw on an image, draw on a copy. The same sample is used many times.
5. **Same input, same work.** No randomness unless it has a fixed seed.
6. **Do the real work.** No shortcuts that skip the task, no cached results, no special cases for certain samples.
7. **Work that depends on a knob but not on the item belongs in `init_worker`.** Example: resize all samples to
   `cfg.data_quality` once, as the existing services do. Work per item belongs in `process`.

Every worker holds its own copy of `state`. Memory use is about `state size x parallelism`, and a run has a
memory limit. Keep `sample_count` and sample size reasonable.

## Data

Three sources, the brief says which:

- **Reuse:** copy the files you need from another service's `data/` into yours. Never point into another
  service's folder; only your own folder is copied into the image.
- **Download:** `prepare.sh` fetches public data. State the source and the licence in `data/README.md`.
- **Generate:** `prepare.sh` or a small script creates the samples, with a fixed seed.

Files up to about 10 MB may go into `data/` and into git. Anything larger must be fetched by `prepare.sh` into a
folder named `fetched/` inside the service, which git ignores. `prepare.sh` must do nothing when the files are
already there.

## `test_service.py`

It runs inside the image with `just check`. It must contain:

1. **The proof**, as a test named `test_proof`, on the real samples at default settings. You choose it. It must
   be a check that a service which does nothing would fail.
2. **One test per knob** showing the knob changes something that can be observed, for example the size of the
   processed frame or the number of results.
3. **A test that `process` returns the declared kind of output** for a sample.

Use the existing services' tests as a pattern. A test that would also pass for a service that does nothing is
not a proof.

## Versions

A version folder that was verified is never edited again. A change is a new folder, `v2`, next to it.
