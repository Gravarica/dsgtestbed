# Generate many services

> State: the procedure is agreed, the command `just generate-batch` is not built yet. Until it is, step 2 is
> done by hand: one session per brief, each following `GENERATE_SERVICE.md`.

Interview once, review the list, then generate with nobody watching. Every service in a batch is made with the
same procedure and judged by the same `just verify` as a single one.

## Step 1 — Plan the batch (with a person)

Ask, one question at a time, with a suggestion each:

1. **What family of services?** For example "image processing", "text", "audio", "point clouds", or a mix.
   Include plain processing, not only models. It often behaves differently, which is what makes a batch useful:

   | Kind of processing | Natural knob | What is interesting about it |
   |---|---|---|
   | image or general compression | quality, level, block size | time depends on the content; jumps between levels |
   | image filtering, resizing | kernel size, output size | grows with the square of the kernel |
   | sorting, grouping, joining tables | rows, groups | limited by memory, not by CPU |
   | parsing logs, JSON, CSV with patterns | number of patterns | depends heavily on the text |
   | hashing, encryption | algorithm, rounds | very steady, almost no spread |
   | audio filtering, spectrum analysis | window length | steady, scales with the window |
   | thinning or clustering point clouds | grid size, neighbours | depends on how dense the scene is |
2. **How many?**
3. **Along which lines must they differ?** Propose: kind of task, kind of data, how heavy the work is
   (from about 1 ms to about 1 s per item), kind of knobs (quality, model choice, thresholds). A batch whose
   services all look alike is of little use. `just services` and the verification reports show what already
   exists and how it behaves.
4. **Which data may be used?** What is in the repo, public downloads, generated samples.
5. **Limits for all of them?** Memory, forbidden packages, the largest download allowed.

Then write `briefs/<batch-name>.yaml`: a list of briefs in the same format as in `GENERATE_SERVICE.md`, each
with its own name, task, data, knobs and limits. Spread them along the lines from question 3 and
say in one line per brief where it sits, for example `position: heavy, image, model-choice knob`.

Show the list to the person. They remove, change or add briefs. Nothing is generated before they say the list
is final.

## Step 2 — Generate (without a person)

```bash
just generate-batch briefs/<batch-name>.yaml
```

For each brief, one after another, the testbed:

1. makes the service folder and puts the brief in it,
2. starts an assistant session with no person attached, using the command set in `generator.yaml`, with the
   prompt "Follow procedures/GENERATE_SERVICE.md for services/<name>/v1",
3. lets it work until it reports a result or its time limit is reached,
4. runs `just verify` itself and records the outcome.

One service at a time, because verification needs the machine's CPUs and ports to itself. A batch takes hours;
start it inside `tmux`. Briefs that already have a result are skipped, so a stopped batch can be started again.

## Step 3 — The report

`results/batches/<batch-name>/report.csv`, one row per brief: name, verified or failed, number of verify runs,
time taken, processing time at default settings, flagged knobs, and the tool and model that wrote it. Failed
attempts stay in their folders. How many briefs succeeded with no human help is itself a result.

## Rules

- The person shapes the list of briefs. After the list is final, no person is involved until the report.
- A failed brief is not retried silently. Trying again means a new brief or a new version, and it is recorded.
- The assistant's command line must limit it to the repo folder.
