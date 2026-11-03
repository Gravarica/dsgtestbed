from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from dsg.docker_host import DockerHost
from dsg.experiment.provenance import paths_changed_since_last_commit
from dsg.experiment.run import PipelineRun
from dsg.node import load_node_settings
from dsg.repository import EXPERIMENTS_DIRECTORY, NODE_FILE, REPOSITORY_ROOT, RESULTS_DIRECTORY
from dsg.service_generator import builder
from dsg.service_generator.catalog import image_name, service_directory
from dsg.service_runtime.contract import ServiceSpec, load_service_spec
from dsg.service_runtime.control_client import ControlClient
from dsg.service_verifier.trials import Behaviour, behaviour_of

REPORT_FILE = "verification_report.json"
VERIFIED = "verified"
FAILED = "failed"
NOT_VERIFIED = "not verified"
REQUIRED_FILES = ("brief.yaml", "spec.yaml", "service.py", "test_service.py", "requirements.txt")
REQUIRED_BRIEF_FIELDS = ("name", "task", "knobs")
PROOF_TEST = "def test_proof("
PROTECTED_PATHS = ("src/", "tests/", "justfile", "pyproject.toml", "node.yaml")
DEFAULT_MEMORY_LIMIT = "8g"


@dataclass(frozen=True)
class Failure:
    check: str
    expected: str
    seen: str


@dataclass
class VerifierTools:
    prepare_and_build: Callable[[str, str], str]
    own_tests_pass: Callable[[str, str], bool]
    describe_behaviour: Callable[[ServiceSpec, str, Path], Behaviour]
    changed_paths: Callable[[], List[str]]


def status_of(service: str, version: str) -> str:
    report_file = service_directory(service, version) / REPORT_FILE
    return json.loads(report_file.read_text())["status"] if report_file.exists() else NOT_VERIFIED


def verify(service: str, version: str, tools: Optional[VerifierTools] = None) -> Dict[str, Any]:
    tools = tools or real_tools()
    directory = service_directory(service, version)
    report = new_report(service, version, directory)
    failures, behaviour = failures_and_behaviour(service, version, directory, tools, report)
    report["status"] = FAILED if failures else VERIFIED
    report["failures"] = [failure.__dict__ for failure in failures]
    report["runs"].append(
        {"at": report["verified_at"], "status": report["status"], "failed_checks": [failure.check for failure in failures]}
    )
    report["verify_runs"] = len(report["runs"])
    report["behaviour"] = behaviour.as_dict() if behaviour else None
    (directory / REPORT_FILE).write_text(json.dumps(report, indent=2))
    if not failures:
        write_starter_experiment(service, version, behaviour)
    return report


def failures_and_behaviour(service, version, directory: Path, tools: VerifierTools, report: Dict[str, Any]):
    failures = static_failures(directory, tools.changed_paths())
    if failures:
        return failures, None
    try:
        report["image_id"] = tools.prepare_and_build(service, version)
    except Exception as error:
        return [Failure("the image builds", "prepare and build succeed", str(error)[-400:])], None
    if not tools.own_tests_pass(service, version):
        return [Failure("the service's own tests pass inside the image", "all tests pass", "at least one failed; run just check")], None
    brief = yaml.safe_load((directory / "brief.yaml").read_text())
    workspace = RESULTS_DIRECTORY / "verification" / f"{service}-{version}" / time.strftime("%Y%m%d-%H%M%S")
    behaviour = tools.describe_behaviour(load_service_spec(directory), memory_limit_of(brief), workspace)
    if behaviour.default_trial_failures:
        seen = "; ".join(behaviour.default_trial_failures)
        return [Failure("a short real run without network completes every item", "valid run, no failed items", seen)], behaviour
    return [], behaviour


def static_failures(directory: Path, changed_paths: List[str]) -> List[Failure]:
    missing = [name for name in REQUIRED_FILES if not (directory / name).exists()]
    if not (directory / "data").is_dir():
        missing.append("data/")
    if missing:
        return [Failure("the folder is complete", "all required files", f"missing {missing}")]
    failures = brief_and_spec_failures(directory)
    if PROOF_TEST not in (directory / "test_service.py").read_text():
        failures.append(Failure("the proof is a test", "a test named test_proof in test_service.py", "no such test"))
    own_folder = str(directory.relative_to(REPOSITORY_ROOT)) + "/"
    touched = [path for path in changed_paths if path.startswith(PROTECTED_PATHS) or changed_another_service(path, own_folder)]
    if touched:
        failures.append(Failure("only the service folder was changed", "no uncommitted change outside it", f"changed: {touched[:8]}"))
    return failures


def changed_another_service(path: str, own_folder: str) -> bool:
    written_by_the_verifier = path.endswith("/" + REPORT_FILE)
    return path.startswith("services/") and not path.startswith(own_folder) and not written_by_the_verifier


def brief_and_spec_failures(directory: Path) -> List[Failure]:
    try:
        spec = load_service_spec(directory)
    except Exception as error:
        return [Failure("spec.yaml can be read", "a valid spec", str(error))]
    brief = yaml.safe_load((directory / "brief.yaml").read_text()) or {}
    missing = [name for name in REQUIRED_BRIEF_FIELDS if not brief.get(name)]
    if missing:
        return [Failure("brief.yaml is complete", f"fields {list(REQUIRED_BRIEF_FIELDS)}", f"missing or empty: {missing}")]
    failures = []
    if brief["name"] != spec.name:
        failures.append(Failure("brief and spec name the same service", brief["name"], spec.name))
    asked = {knob["name"]: knob for knob in brief["knobs"]}
    if set(asked) != set(spec.application_knobs):
        failures.append(Failure("spec has the knobs the brief asks for", str(sorted(asked)), str(sorted(spec.application_knobs))))
        return failures
    for name, knob in spec.application_knobs.items():
        if not same_range(asked[name], knob):
            failures.append(Failure(f"knob {name} has the range the brief asks for", str(asked[name]), str(knob)))
    return failures


def same_range(asked: Dict[str, Any], knob) -> bool:
    if knob.kind == "choice":
        return list(asked.get("values", [])) == list(knob.choices) and asked.get("default") == knob.default
    return (asked.get("min"), asked.get("max"), asked.get("default")) == (knob.minimum, knob.maximum, knob.default)


def memory_limit_of(brief: Dict[str, Any]) -> str:
    return str((brief.get("limits") or {}).get("memory", DEFAULT_MEMORY_LIMIT))


def new_report(service: str, version: str, directory: Path) -> Dict[str, Any]:
    previous = json.loads((directory / REPORT_FILE).read_text()) if (directory / REPORT_FILE).exists() else {}
    generation = yaml_mapping(directory / "generation.yaml")
    return {
        "service": f"{service}:{version}",
        "status": FAILED,
        "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verify_runs": 0,
        "runs": earlier_runs(previous),
        "image_id": None,
        "proof": generation.get("proof") or yaml_mapping(directory / "brief.yaml").get("proof"),
        "generation": generation or "not stated",
    }


def yaml_mapping(yaml_file: Path) -> Dict[str, Any]:
    return (yaml.safe_load(yaml_file.read_text()) or {}) if yaml_file.exists() else {}


def earlier_runs(previous_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "runs" in previous_report:
        return list(previous_report["runs"])
    outcome_unknown = {"at": None, "status": "not recorded", "failed_checks": []}
    return [dict(outcome_unknown) for _ in range(previous_report.get("verify_runs", 0))]


def write_starter_experiment(service: str, version: str, behaviour: Behaviour) -> None:
    experiment_file = EXPERIMENTS_DIRECTORY / f"{service}-single.yaml"
    if experiment_file.exists():
        return
    spec = load_service_spec(service_directory(service, version))
    experiment = {
        "nodes": {
            service: {
                "service": f"{service} {version}",
                "cores": 2,
                "parallelism": 1,
                "knobs": {name: knob.default for name, knob in spec.application_knobs.items()},
            }
        },
        "load": {"rps": behaviour.safe_rate_per_second},
        "run": {"warmup_seconds": 5, "measure_seconds": 20},
    }
    experiment_file.write_text(yaml.safe_dump(experiment, sort_keys=False))


def real_tools() -> VerifierTools:
    docker = DockerHost()
    node = load_node_settings(NODE_FILE)

    def prepare_and_build(service: str, version: str) -> str:
        builder.prepare(service, version)
        builder.build(service, version, docker)
        return docker.image_id(image_name(service, version))

    def run_trial(plan, directory: Path) -> Dict[str, Any]:
        return PipelineRun(
            plan=plan,
            node_settings=node,
            project=f"dsg-verify-{plan.nodes[0].service}-{plan.run_id}".lower(),
            run_directory=directory,
            docker=docker,
            service_at=ControlClient,
            wait=time.sleep,
            without_network=True,
        ).execute()

    return VerifierTools(
        prepare_and_build=prepare_and_build,
        own_tests_pass=lambda service, version: builder.check(service, version, docker),
        describe_behaviour=lambda spec, memory_limit, workspace: behaviour_of(spec, memory_limit, run_trial, workspace),
        changed_paths=lambda: paths_changed_since_last_commit(REPOSITORY_ROOT),
    )


def report_in_plain_words(report: Dict[str, Any]) -> str:
    lines = [f"{report['service']}: {report['status'].upper()}  (verify run {report['verify_runs']})"]
    for failure in report["failures"]:
        lines.append(f"  FAILED  {failure['check']}")
        lines.append(f"          expected: {failure['expected']}")
        lines.append(f"          seen:     {failure['seen']}")
    behaviour = report.get("behaviour") or {}
    if behaviour.get("at_default"):
        processing = behaviour["at_default"]["processing_ms"]
        lines.append(
            f"  one item takes {processing['mean']} ms on average (median {processing['median']}, p99 {processing['p99']}), "
            f"from {behaviour['at_default']['measured_items']} items"
        )
        lines.append(f"  memory with one worker: {behaviour['at_default']['memory_mb_one_worker']} MB")
    for knob_name, effect in (behaviour.get("knobs") or {}).items():
        if "at_lowest_ms" in effect:
            lines.append(
                f"  knob {knob_name}: {effect['at_lowest_ms']} ms at {effect['lowest_value']}, "
                f"{effect['at_highest_ms']} ms at {effect['highest_value']} -> {effect['seen']}"
            )
    for note in behaviour.get("notes") or []:
        lines.append(f"  NOTE    {note}")
    for flag in behaviour.get("flags") or []:
        lines.append(f"  FLAG    {flag}")
    lines.append(f"  proof: {report['proof']}")
    lines.append("  earlier runs: " + ", ".join(run["status"] for run in report["runs"][:-1]) if len(report["runs"]) > 1 else "  first verify run")
    return "\n".join(lines)
