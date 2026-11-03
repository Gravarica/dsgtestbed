# Generate a new service

You are adding one new service to the dsg testbed. You may be an AI assistant or a person. Follow the steps in
order. First read `SERVICE_CONTRACT.md` in this folder. You may read the existing services in `services/` as
examples.

## What you may touch

Only the folder of the new service, `services/<name>/<version>/`. Never edit `src/`, `tests/`, the `justfile`,
other services, or any `verification_report.json`. Verification refuses the service if anything else changed.

## Step 1 — Is there already a brief?

If `services/<name>/<version>/brief.yaml` exists and its `task` does not start with the word `Skeleton`, go to
step 3. Someone has already decided what to build.

## Step 2 — Interview

Ask these four questions, one at a time. With each question give your own suggestion, so the person can say yes
or correct it. Use plain words. Ask what the service should do, never how to build it.

1. **What should the service do?** One sentence. It does not have to involve a model. Plain processing is just
   as welcome: compressing, filtering, parsing, sorting, hashing, converting.
2. **What data does it work on?** List what is already in the repo (look in `services/*/*/data/` and
   `services/*/*/fetched/`). Offer public data or generated samples as alternatives.
3. **What can be tuned?** Propose two or three knobs that fit the task, with ranges and defaults.
4. **Any limits?** Memory, packages that must not be used, the name of the service.

Do not ask the person how the service will be proven to work, and do not ask what a knob will do to the
processing time. The first is your job in step 3. The second is what `just verify` measures.

Write the answers as a brief and show it:

```yaml
name: text-recognizer
asked_by: <your name>
date: 2026-09-21
task: Read the text on each image and return it as a string.
data: {source: reuse, from: qr-detector/v1, files: [QR_Video.mp4]}
knobs:
  - {name: data_quality, type: int, min: 100, max: 1000, default: 500}
  - {name: mode, type: choice, values: [fast, exact], default: fast}
limits: {memory: 8g}
```

Ask: "Is this what you want?" Change it until the answer is yes. Then run `just new-service <name>` and replace
the `brief.yaml` in the new folder with this brief.

**From here on the person decides nothing about how the service is built.** Do not ask them. If you truly
cannot continue without them, for example the data cannot be obtained, ask, and record the mode as `assisted`
in step 6.

## Step 3 — Write the service

1. `spec.yaml` from the brief: the knobs exactly as agreed, same names, ranges and defaults.
2. The data: copy, or write `prepare.sh`, as the brief says. Write `data/README.md` with source and licence.
3. `service.py`: `init_worker` and `process`, following every rule in the contract.
4. `test_service.py`: the proof as `test_proof`, one test per knob, one test for the output. You decide what the
   proof is: one concrete check on the real samples at default settings that a do-nothing service would fail.
5. `requirements.txt` with pinned versions. `apt.txt` only if a system package is really needed.

## Step 4 — Build, check, verify

```bash
just prepare <name> <version>     # only if there is a prepare.sh
just build <name> <version>
just check <name> <version>       # your own tests, inside the image
just verify <name> <version>      # the testbed's judgement
```

Read what failed, fix it, run again. `just verify` tells you which check failed, what it expected and what it
saw. You have at most 8 runs of `just verify`; the report counts them.

`just verify` fails the service when: a required file is missing, the brief or the spec cannot be read, the
spec's knobs are not the ones the brief asks for, there is no test named `test_proof`, files outside the
service folder changed, the image does not build, your own tests fail, or a short real run on a closed network
does not complete every item.

`just verify` only records, and does not fail: how long an item takes, how much memory a worker needs, what
each knob does to the processing time, and whether the service uses more CPU than its workers explain. A knob
with no effect on the time is noted. That is fine for a knob like a threshold; for a knob that should change
the amount of work it means the knob is not wired up, so fix it.

## Step 5 — What you must never do to get a pass

- Weaken or remove the proof, or write a test that a do-nothing service would pass.
- Hide failures by catching exceptions.
- Return a constant or a cached result, or treat the samples used by the tests differently.
- Edit anything outside the service folder.

If the service cannot pass honestly, it has failed. That is a valid result and it is recorded.

## Step 6 — Finish

Write `generation.yaml` in the service folder:

```yaml
tool: Claude Code            # or Codex, or "by hand"
model: <the model you are>
mode: autonomous             # "assisted" if the person sent any message after confirming the brief
result: verified             # or "failed"
proof: <one sentence: what test_proof checks>
notes: <anything the next person should know, one or two sentences>
```

Run `just verify <name> <version>` one last time so the report includes it. Then tell the person, in a few
plain sentences: what the service does, whether it was verified, the processing time at default settings, and
anything that was flagged. A verified service also has a ready experiment file, `experiments/<name>-single.yaml`.
If it failed, say why. Leave the folder as it is. A later attempt is a new version folder.
