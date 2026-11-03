import json

from dsg.service_runtime.contract import service_spec_from_mapping
from dsg.service_verifier.trials import (
    seconds_to_measure,
    HIGHER_IS_FASTER,
    HIGHER_TAKES_LONGER,
    NO_EFFECT_ON_TIME,
    behaviour_of,
    effect_seen,
    lowest_and_highest,
    safe_rate_per_second,
)

MILLISECOND_NS = 1_000_000
SPEC = service_spec_from_mapping(
    {
        "name": "toy",
        "version": "v1",
        "service_type": "toy",
        "input": "any",
        "output": "bytes",
        "knobs": {
            "data_quality": {"type": "int", "min": 100, "max": 1000, "default": 500},
            "mode": {"type": "choice", "values": ["fast", "exact"], "default": "fast"},
        },
    }
)


class FakeService:
    def __init__(self, processing_ms_of, cpu_factor=1.0, breaks_in=()):
        self.processing_ms_of = processing_ms_of
        self.cpu_factor = cpu_factor
        self.breaks_in = breaks_in
        self.plans = []

    def run_trial(self, plan, directory):
        self.plans.append(plan)
        if plan.run_id in self.breaks_in:
            return {"problems": ["container_exited"], "flags": []}
        processing_ns = round(self.processing_ms_of(plan.nodes[0].knobs) * MILLISECOND_NS)
        items = 20
        rows = ["admission_phase,outcome,arrived_at_ns,started_at_ns,finished_at_ns"]
        for position in range(items):
            started = 1_000_000_000 + position * 50 * MILLISECOND_NS
            rows.append(f"measure,completed,{started},{started},{started + processing_ns}")
        (directory / "toy").mkdir(parents=True)
        (directory / "toy" / "records.csv").write_text("\n".join(rows) + "\n")
        (directory / "toy" / "run_summary.json").write_text(
            json.dumps(
                {
                    "counts": {"unresolved": 0},
                    "achieved_rate_per_second": plan.rps,
                    "lifecycle_entered_at_ns": {"measuring": 0, "draining": 10_000_000_000},
                }
            )
        )
        cpu_micros = round(items * processing_ns / 1000 * self.cpu_factor)
        measured_container = {
            "memory_bytes_under_load": 250_000_000,
            "cpu_stat": {"before": {"usage_usec": 0}, "after": {"usage_usec": cpu_micros}},
        }
        return {"problems": [], "flags": [], "nodes": {"toy": measured_container}}


def grows_with_quality(knobs):
    return 10 * knobs.get("data_quality", 500) / 500


def test_safe_rate_uses_half_of_what_the_workers_can_do_within_limits():
    assert safe_rate_per_second(processing_mean_ms=10, workers=1) == 50
    assert safe_rate_per_second(processing_mean_ms=10, workers=4) == 200
    assert safe_rate_per_second(processing_mean_ms=5000, workers=1) == 1
    assert safe_rate_per_second(processing_mean_ms=0.01, workers=1) == 200


def test_knob_is_tried_at_its_two_ends():
    assert lowest_and_highest(SPEC.application_knobs["data_quality"]) == [100, 1000]
    assert lowest_and_highest(SPEC.application_knobs["mode"]) == ["fast", "exact"]


def test_effect_needs_a_clear_difference():
    assert effect_seen(10, 20) == HIGHER_TAKES_LONGER
    assert effect_seen(20, 10) == HIGHER_IS_FASTER
    assert effect_seen(10, 10.5) == NO_EFFECT_ON_TIME
    assert effect_seen(0.001, 0.003) == NO_EFFECT_ON_TIME


def test_behaviour_describes_default_knobs_and_workers(tmp_path):
    service = FakeService(grows_with_quality)
    behaviour = behaviour_of(SPEC, "8g", service.run_trial, tmp_path)
    assert behaviour.default_trial_failures == []
    assert behaviour.at_default["processing_ms"]["mean"] == 10
    assert behaviour.at_default["memory_mb_one_worker"] == 250
    assert behaviour.safe_rate_per_second == 50
    assert behaviour.knobs["data_quality"]["at_lowest_ms"] == 2
    assert behaviour.knobs["data_quality"]["at_highest_ms"] == 20
    assert behaviour.knobs["data_quality"]["seen"] == HIGHER_TAKES_LONGER
    assert behaviour.knobs["mode"]["seen"] == NO_EFFECT_ON_TIME
    assert behaviour.notes == ["knob mode has no effect on the processing time"]
    assert behaviour.flags == []
    assert behaviour.workers["kept_up"] is True


def test_every_trial_has_one_core_more_than_workers_so_the_quota_does_not_distort_it(tmp_path):
    service = FakeService(grows_with_quality)
    behaviour_of(SPEC, "8g", service.run_trial, tmp_path)
    assert [plan.run_id for plan in service.plans] == [
        "probe", "default", "data_quality-lowest", "data_quality-highest", "mode-lowest", "mode-highest", "several-workers",
    ]
    assert all(plan.nodes[0].cores == plan.nodes[0].knobs["parallelism"] + 1 for plan in service.plans)
    assert service.plans[0].rps == 2 and service.plans[0].nodes[0].knobs["discipline"] == "fifo"
    assert service.plans[-1].nodes[0].knobs["parallelism"] == 4
    assert all(plan.edges == () for plan in service.plans)


def test_a_trial_lasts_until_enough_items_arrived_but_not_longer_than_a_minute():
    assert seconds_to_measure(rate_per_second=100, at_least_seconds=8) == 8
    assert seconds_to_measure(rate_per_second=1, at_least_seconds=8) == 30
    assert seconds_to_measure(rate_per_second=0.1, at_least_seconds=8) == 60


def test_slow_services_get_longer_trials_so_the_numbers_rest_on_enough_items(tmp_path):
    def two_seconds_per_item(knobs):
        return 2000

    service = FakeService(two_seconds_per_item)
    behaviour_of(SPEC, "8g", service.run_trial, tmp_path)
    default_plan = service.plans[1]
    assert default_plan.rps == 1
    assert default_plan.measure_seconds == 30


def test_hidden_threads_show_up_as_more_cpu_than_the_workers_explain(tmp_path):
    behaviour = behaviour_of(SPEC, "8g", FakeService(grows_with_quality, cpu_factor=3.0).run_trial, tmp_path)
    assert "more_cpu_than_the_workers_explain" in behaviour.flags


def test_a_broken_default_run_stops_the_trials_and_is_reported(tmp_path):
    service = FakeService(grows_with_quality, breaks_in=("default",))
    behaviour = behaviour_of(SPEC, "8g", service.run_trial, tmp_path)
    assert behaviour.default_trial_failures == ["container_exited"]
    assert [plan.run_id for plan in service.plans] == ["probe", "default"]


def test_a_broken_knob_trial_is_recorded_but_does_not_stop_the_others(tmp_path):
    service = FakeService(grows_with_quality, breaks_in=("mode-highest",))
    behaviour = behaviour_of(SPEC, "8g", service.run_trial, tmp_path)
    assert behaviour.default_trial_failures == []
    assert behaviour.knobs["mode"]["seen"] == "trial failed"
    assert "kept_up" in behaviour.workers


def test_a_very_light_service_is_not_flagged_for_the_cost_of_the_harness(tmp_path):
    def nearly_instant(knobs):
        return 0.01

    service = FakeService(nearly_instant)
    original_run_trial = service.run_trial

    def with_harness_cpu(plan, directory):
        described = original_run_trial(plan, directory)
        described["nodes"]["toy"]["cpu_stat"] = {"before": {"usage_usec": 0}, "after": {"usage_usec": 15000}}
        return described

    behaviour = behaviour_of(SPEC, "8g", with_harness_cpu, tmp_path)
    assert "more_cpu_than_the_workers_explain" not in behaviour.flags
