# service_verifier

The testbed's own judgement of a service. Whoever wrote the service, a person or an assistant, does not grade
their own work: `just verify <service> <version>` does.

**Used from outside**
- `verify(service, version)` — runs everything below, writes `verification_report.json` into the service folder,
  returns the report. The report keeps the outcome of every earlier verify run. On success it also writes
  `experiments/<service>-single.yaml` with a fitting arrival rate and one CPU core more than workers.
- `status_of(service, version)` — `verified`, `failed`, or `not verified`.
- `report_in_plain_words(report)` — the text `just verify` prints.

**`verification.py` knows what makes a service acceptable.** These fail a service:
the folder is incomplete; `spec.yaml` or `brief.yaml` cannot be read; the spec's knobs are not the ones the brief
asks for; `test_service.py` has no test named `test_proof`; something outside the service folder was changed
(`src/`, `tests/`, `justfile`, another service); prepare or build fails; the service's own tests fail inside the
image; a short real run on a closed network does not complete every item.

**`trials.py` knows how to try a service out and describe its behaviour.** It first probes how long one item
takes, picks an arrival rate the service can keep up with, and then runs the service for a few seconds at default
settings, at the lowest and highest value of every knob, and with several workers. Every trial runs without
network and with one CPU core more than it has workers, so the CPU quota does not pause the service in the
middle of an item and the numbers describe the service itself. Nothing here fails a service except the run at default settings. A trial lasts until
about 30 items have arrived, up to a minute, so slow services are described from enough items. It records
processing time, its spread, memory and the effect of each knob. It notes a knob that has no effect on the time
and flags more CPU use than the workers explain. Nobody is asked to predict any of this.

Trial runs are kept in `results/verification/<service>-<version>/<time>/`.
