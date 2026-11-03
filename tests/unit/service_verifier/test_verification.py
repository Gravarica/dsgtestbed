import json

import pytest
import yaml

from dsg.service_generator.builder import new_service
from dsg.service_verifier import verification
from dsg.service_verifier.trials import Behaviour
from dsg.service_verifier.verification import FAILED, NOT_VERIFIED, VERIFIED, VerifierTools, static_failures


@pytest.fixture
def service_folder(tmp_path, monkeypatch):
    services = tmp_path / "services"
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    directory = new_service("toy", services_directory=services)
    monkeypatch.setattr(verification, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(verification, "EXPERIMENTS_DIRECTORY", experiments)
    monkeypatch.setattr(verification, "RESULTS_DIRECTORY", tmp_path / "results")
    monkeypatch.setattr(verification, "service_directory", lambda service, version: services / service / version)
    return directory


def working_behaviour():
    return Behaviour(
        at_default={"processing_ms": {"mean": 4.0, "median": 4.0, "p99": 5.0}, "memory_mb_one_worker": 120, "measured_items": 40},
        safe_rate_per_second=125.0,
    )


def tools(builds=True, tests_pass=True, behaviour=None, changed=()):
    def prepare_and_build(service, version):
        if not builds:
            raise RuntimeError("pip could not find package xyz")
        return "sha256:abc"

    return VerifierTools(
        prepare_and_build=prepare_and_build,
        own_tests_pass=lambda service, version: tests_pass,
        describe_behaviour=lambda spec, memory_limit, workspace: behaviour or working_behaviour(),
        changed_paths=lambda: list(changed),
    )


def checks_that_failed(report):
    return [failure["check"] for failure in report["failures"]]


def test_the_skeleton_made_by_new_service_passes_the_static_checks(service_folder):
    assert static_failures(service_folder, changed_paths=["services/toy/v1/service.py"]) == []


def test_a_good_service_is_verified_and_gets_a_report_and_a_starter_experiment(service_folder, tmp_path):
    report = verification.verify("toy", "v1", tools())
    assert report["status"] == VERIFIED
    assert report["image_id"] == "sha256:abc"
    assert report["proof"] is None
    assert json.loads((service_folder / "verification_report.json").read_text())["status"] == VERIFIED
    starter = yaml.safe_load((tmp_path / "experiments" / "toy-single.yaml").read_text())
    assert starter["nodes"]["toy"] == {"service": "toy v1", "cores": 2, "parallelism": 1, "knobs": {"work_size": 100}}
    assert starter["load"] == {"rps": 125.0}
    assert verification.status_of("toy", "v1") == VERIFIED


def test_a_service_nobody_verified_says_so(service_folder):
    assert verification.status_of("toy", "v1") == NOT_VERIFIED


def test_missing_file_fails_before_anything_is_built(service_folder):
    (service_folder / "test_service.py").unlink()
    report = verification.verify("toy", "v1", tools(builds=False))
    assert checks_that_failed(report) == ["the folder is complete"]


def test_spec_must_have_exactly_the_knobs_of_the_brief(service_folder):
    spec = yaml.safe_load((service_folder / "spec.yaml").read_text())
    spec["knobs"]["surprise"] = {"type": "int", "min": 1, "max": 2, "default": 1}
    (service_folder / "spec.yaml").write_text(yaml.safe_dump(spec))
    assert checks_that_failed(verification.verify("toy", "v1", tools())) == ["spec has the knobs the brief asks for"]


def test_knob_range_must_be_the_one_the_brief_asks_for(service_folder):
    spec = yaml.safe_load((service_folder / "spec.yaml").read_text())
    spec["knobs"]["work_size"]["max"] = 5000
    (service_folder / "spec.yaml").write_text(yaml.safe_dump(spec))
    assert checks_that_failed(verification.verify("toy", "v1", tools())) == ["knob work_size has the range the brief asks for"]


def test_the_proof_must_be_a_test(service_folder):
    test_file = service_folder / "test_service.py"
    test_file.write_text(test_file.read_text().replace("def test_proof(", "def test_something("))
    assert checks_that_failed(verification.verify("toy", "v1", tools())) == ["the proof is a test"]


def test_changes_outside_the_service_folder_are_refused(service_folder):
    changed = ["services/toy/v1/service.py", "src/dsg/service_verifier/verification.py", "services/other/v1/spec.yaml", "experiments/toy-single.yaml"]
    report = verification.verify("toy", "v1", tools(changed=changed))
    assert checks_that_failed(report) == ["only the service folder was changed"]
    assert "src/dsg/service_verifier/verification.py" in report["failures"][0]["seen"]
    assert "experiments/toy-single.yaml" not in report["failures"][0]["seen"]


def test_reports_the_verifier_wrote_for_other_services_are_not_changes_by_the_author(service_folder):
    changed = ["services/other/v1/verification_report.json", "experiments/other-single.yaml"]
    assert verification.verify("toy", "v1", tools(changed=changed))["status"] == VERIFIED


def test_build_failure_and_failing_own_tests_are_reported_in_plain_words(service_folder):
    assert checks_that_failed(verification.verify("toy", "v1", tools(builds=False))) == ["the image builds"]
    report = verification.verify("toy", "v1", tools(tests_pass=False))
    assert checks_that_failed(report) == ["the service's own tests pass inside the image"]
    assert report["verify_runs"] == 2
    assert "FAILED" in verification.report_in_plain_words(report)


def test_a_failed_run_at_default_settings_fails_the_service_but_flags_do_not(service_folder):
    broken = Behaviour(default_trial_failures=["3 items failed, 0 never finished"])
    report = verification.verify("toy", "v1", tools(behaviour=broken))
    assert report["status"] == FAILED
    flagged = working_behaviour()
    flagged.flags.append("more_cpu_than_the_workers_explain")
    assert verification.verify("toy", "v1", tools(behaviour=flagged))["status"] == VERIFIED


def test_who_generated_the_service_and_its_proof_are_part_of_the_report(service_folder):
    (service_folder / "generation.yaml").write_text("tool: Codex\nmodel: some-model\nmode: autonomous\nproof: returns work_size bytes\n")
    report = verification.verify("toy", "v1", tools())
    assert report["generation"]["tool"] == "Codex"
    assert report["proof"] == "returns work_size bytes"


def test_older_briefs_that_still_state_a_proof_or_an_expectation_stay_valid(service_folder):
    brief = yaml.safe_load((service_folder / "brief.yaml").read_text())
    brief["proof"] = "stated in the brief"
    brief["knobs"][0]["expect"] = "higher takes longer"
    (service_folder / "brief.yaml").write_text(yaml.safe_dump(brief))
    report = verification.verify("toy", "v1", tools())
    assert report["status"] == VERIFIED
    assert report["proof"] == "stated in the brief"


def test_the_report_keeps_the_outcome_of_every_verify_run(service_folder):
    verification.verify("toy", "v1", tools(tests_pass=False))
    verification.verify("toy", "v1", tools(builds=False))
    report = verification.verify("toy", "v1", tools())
    assert [run["status"] for run in report["runs"]] == [FAILED, FAILED, VERIFIED]
    assert report["runs"][0]["failed_checks"] == ["the service's own tests pass inside the image"]
    assert report["verify_runs"] == 3
    assert "earlier runs: failed, failed" in verification.report_in_plain_words(report)


def test_a_report_from_before_run_history_existed_is_carried_over_honestly(service_folder):
    (service_folder / "verification_report.json").write_text(json.dumps({"status": VERIFIED, "verify_runs": 2}))
    report = verification.verify("toy", "v1", tools())
    assert [run["status"] for run in report["runs"]] == ["not recorded", "not recorded", VERIFIED]
