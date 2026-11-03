# Rules for this repo

This repo is the dsg testbed, a tool. It is not a research experiment repo. Research that uses the testbed lives
in a separate repo.

1. **No comments and no docstrings in code.** Names carry the meaning. What an interface comment would say goes
   into the `README.md` of the package.
2. **Names say what they do.** No abbreviations that need decoding.
3. **Modules follow knowledge, not the order of steps.** Two pieces that must change together belong together.
   **Deep modules.** A module has a small interface and hides a lot. Do not split a module only because it is
   long; split when two parts know different things. Do not add a class that only forwards calls.
4. **One fact lives in one place.** The window rule lives in `item_queue`. Endpoint names live in
   `service_runtime/endpoints.py`. Only `docker_host.py` calls Docker. Only `control_client.py` and
   `monitor/prometheus.py` make HTTP calls.
5. **Dependencies point one way:** `cli` → `service_verifier` → `experiment` → components → `docker_host`.
   `service_runtime` may use `load_generator` and `monitor`. Nothing imports `cli`.
6. **Every component is tested alone and together.** Unit tests need no Docker and no network. The integration
   test runs a real container. A component without a unit test is not done.
7. **Elastic-workbench compatibility is a feature.** Endpoint names, knob names, gauge names and labels, the
   `metrics.csv` columns, window batching and once-per-second rate updates stay as elastic-workbench has them.
8. **A service version folder is never edited after it was used.** Make a new version folder.
9. **Procedures for assistants live in `procedures/`**, plain markdown, tool-neutral; the code they call lives in
   `src/dsg/`. **Every command is in the `justfile`** and calls `dsg`. `ARCHITECTURE.md` changes in the same commit as the code.
