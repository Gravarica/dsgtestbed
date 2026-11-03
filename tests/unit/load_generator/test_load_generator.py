import pytest

from dsg.load_generator.arrival_schedule import ArrivalSchedule
from dsg.load_generator.item_source import ItemSource
from dsg.load_generator.rate_pattern import Bursts, PatternUnknown, RatePattern, RateSetter, available_patterns
from tests.support import FakeClock

SECOND_NS = 1_000_000_000


def build_source(clock, sample_count=3):
    admitted = []
    source = ItemSource(
        ArrivalSchedule("deterministic", seed=0),
        lambda sample_index, scheduled_at_ns: admitted.append((sample_index, scheduled_at_ns)),
        clock.monotonic_ns,
        sample_count,
    )
    return source, admitted


def test_deterministic_schedule_spaces_deadlines_evenly_whatever_the_emission_time():
    schedule = ArrivalSchedule("deterministic", seed=0)
    schedule.change_rate(10, now_ns=0)
    deadlines = []
    for _ in range(3):
        deadlines.append(schedule.next_deadline_ns())
        schedule.advance()
    assert deadlines == [100_000_000, 200_000_000, 300_000_000]


def test_zero_rate_means_no_deadline():
    schedule = ArrivalSchedule("deterministic", seed=0)
    schedule.change_rate(0, now_ns=0)
    assert schedule.next_deadline_ns() is None


def test_a_faster_rate_brings_the_next_arrival_closer():
    schedule = ArrivalSchedule("deterministic", seed=0)
    schedule.change_rate(1, now_ns=0)
    schedule.change_rate(100, now_ns=SECOND_NS // 2)
    assert schedule.next_deadline_ns() == SECOND_NS // 2 + SECOND_NS // 100


def test_a_small_rate_change_every_second_does_not_lose_the_arrival_already_planned():
    schedule = ArrivalSchedule("deterministic", seed=0)
    schedule.change_rate(20, now_ns=0)
    planned = schedule.next_deadline_ns()
    schedule.change_rate(21, now_ns=planned - 1_000_000)
    assert schedule.next_deadline_ns() == planned


def test_a_service_that_was_idle_starts_one_gap_after_it_gets_a_rate():
    schedule = ArrivalSchedule("deterministic", seed=0)
    schedule.change_rate(0, now_ns=0)
    schedule.change_rate(10, now_ns=3 * SECOND_NS)
    assert schedule.next_deadline_ns() == 3 * SECOND_NS + SECOND_NS // 10


def test_poisson_schedule_is_reproducible_and_has_the_requested_mean_rate():
    def deadlines(seed):
        schedule = ArrivalSchedule("poisson", seed=seed)
        schedule.change_rate(100, now_ns=0)
        collected = []
        for _ in range(5000):
            collected.append(schedule.next_deadline_ns())
            schedule.advance()
        return collected

    assert deadlines(7) == deadlines(7)
    assert deadlines(7)[-1] / SECOND_NS == pytest.approx(50, rel=0.05)


def test_unknown_arrival_process_is_refused():
    with pytest.raises(ValueError):
        ArrivalSchedule("bursty", seed=0)


def test_source_emits_every_due_item_with_its_planned_time_and_cycles_samples():
    clock = FakeClock()
    source, admitted = build_source(clock, sample_count=3)
    source.change_client_rate("C_1", 10)
    clock.advance_ms(530)
    assert source.emit_due_items() == 5
    assert [sample_index for sample_index, _ in admitted] == [0, 1, 2, 0, 1]
    assert admitted[0][1] == 100_000_000


def test_client_rates_add_up_like_in_elastic_workbench_and_changes_are_logged():
    clock = FakeClock()
    source, _ = build_source(clock)
    source.change_client_rate("C_1", 40)
    source.change_client_rate("C_2", 30)
    assert source.total_rate() == 70
    clock.advance_ms(1000)
    source.change_client_rate("C_1", 10)
    assert source.rate_changes() == [(0, 40), (0, 70), (SECOND_NS, 40)]


def test_elastic_workbench_traces_are_available_by_name():
    assert available_patterns() == ["constant", "bursty", "diurnal"]
    with pytest.raises(PatternUnknown):
        RatePattern("sawtooth", 100)


def test_trace_rate_is_the_normalized_value_times_the_peak_rounded():
    bursty = RatePattern("bursty", peak_rate=397)
    assert bursty.rate_at(0) == 157
    assert bursty.rate_at(1.9) == 158
    assert max(bursty.rate_at(second) for second in range(3600)) == 397


def test_pattern_can_start_later_in_the_trace_and_wraps_after_an_hour():
    shifted = RatePattern("bursty", peak_rate=397, start_second=1)
    assert shifted.rate_at(0) == 158
    assert RatePattern("bursty", 397).rate_at(3600) == 157


def test_rate_setter_pushes_a_new_rate_only_when_it_changes():
    pushed = []
    setter = RateSetter(RatePattern("constant", 40), pushed.append)
    for second in range(5):
        setter.apply(second)
    assert pushed == [40]
    pushed.clear()
    setter = RateSetter(RatePattern("bursty", 397), pushed.append)
    for second in range(3):
        setter.apply(second)
    assert pushed == [157, 158, 159]


@pytest.mark.parametrize("factor, seconds", [(2, 1), (4, 2), (8, 4), (3, 5)])
def test_bursts_carry_the_factor_and_keep_the_mean_rate_over_every_period(factor, seconds):
    bursts = Bursts(factor, seconds, seed=7)
    shares = [bursts.share_of_mean_at(second) for second in range(bursts.period_seconds)]
    assert shares.count(factor) == seconds
    assert sum(shares) / len(shares) == pytest.approx(1.0)
    assert min(shares) > 0


def test_bursts_start_at_a_seeded_second_and_repeat_every_period():
    first, again, other = Bursts(4, 2, seed=1), Bursts(4, 2, seed=1), Bursts(4, 2, seed=2)
    seconds = range(3 * first.period_seconds)
    assert [first.share_of_mean_at(s) for s in seconds] == [again.share_of_mean_at(s) for s in seconds]
    assert first.share_of_mean_at(0) == first.share_of_mean_at(first.period_seconds)
    assert any(first.share_of_mean_at(s) != other.share_of_mean_at(s) for s in seconds)


def test_a_burst_factor_of_one_is_a_constant_rate():
    assert {Bursts(1, 3, seed=0).share_of_mean_at(second) for second in range(10)} == {1.0}


def test_a_constant_rate_with_bursts_offers_the_mean_on_average():
    pattern = RatePattern("constant", 20, bursts=Bursts(4, 2, seed=3))
    period = Bursts(4, 2, seed=3).period_seconds
    rates = [pattern.rate_at(second) for second in range(period)]
    assert max(rates) == 80
    assert sum(rates) / period == pytest.approx(20, rel=0.01)


def test_a_faster_trace_moves_through_the_hour_that_many_times_faster():
    assert RatePattern("bursty", 397, speed=12).rate_at(1) == RatePattern("bursty", 397).rate_at(12)


def test_rate_setter_remembers_the_rate_offered_in_every_second():
    setter = RateSetter(RatePattern("bursty", 397), lambda rate: None)
    for second in range(3):
        setter.apply(second)
    assert setter.offered_rates == [157, 158, 159]


@pytest.mark.parametrize("variability", [0.3, 1.0, 2.0, 4.0])
def test_renewal_arrivals_keep_the_rate_and_have_the_variability_asked_for(variability):
    schedule = ArrivalSchedule("renewal", seed=11, variability=variability)
    schedule.change_rate(50, now_ns=0)
    deadlines = []
    for _ in range(40000):
        deadlines.append(schedule.next_deadline_ns())
        schedule.advance()
    gaps = [later - earlier for earlier, later in zip(deadlines, deadlines[1:])]
    mean = sum(gaps) / len(gaps)
    squared_coefficient_of_variation = sum((gap - mean) ** 2 for gap in gaps) / len(gaps) / mean**2
    assert mean == pytest.approx(SECOND_NS / 50, rel=0.03)
    assert squared_coefficient_of_variation == pytest.approx(variability, rel=0.1)


def test_renewal_arrivals_without_variability_are_evenly_spaced():
    schedule = ArrivalSchedule("renewal", seed=0, variability=0)
    schedule.change_rate(4, now_ns=0)
    first = schedule.next_deadline_ns()
    schedule.advance()
    assert schedule.next_deadline_ns() - first == SECOND_NS // 4


def test_a_constant_rate_below_one_per_second_is_not_rounded_away():
    assert RatePattern("constant", 0.35).rate_at(3) == 0.35
