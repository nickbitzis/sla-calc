import pytest

from slacalc.burn import DEFAULT_RULES, burn, burn_rate_for_budget, evaluate_alerts

DAY = 86400


def test_burn_rate_basics():
    r = burn(0.999, good=99_000, total=100_000, window_seconds=3600, period_seconds=30 * DAY)
    assert r.error_rate == pytest.approx(0.01)
    assert r.burn_rate == pytest.approx(10)
    assert r.budget_spent == pytest.approx(10 / 720)
    assert r.time_to_exhaustion_seconds == pytest.approx(3 * DAY)


def test_no_errors_means_no_exhaustion():
    r = burn(0.999, good=10, total=10, window_seconds=3600, period_seconds=30 * DAY)
    assert r.burn_rate == 0
    assert r.time_to_exhaustion_seconds is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target": 0.999, "good": 1, "total": 0},
        {"target": 0.999, "good": 11, "total": 10},
        {"target": 1.0, "good": 1, "total": 1},
        {"target": 0.999, "good": 1, "total": 1, "window_seconds": 0},
    ],
)
def test_burn_validates_inputs(kwargs):
    base = {"window_seconds": 3600, "period_seconds": 30 * DAY}
    with pytest.raises(ValueError):
        burn(**{**base, **kwargs})


def test_default_thresholds_come_from_budget_shares():
    for rule in DEFAULT_RULES:
        from slacalc.availability import parse_duration

        derived = burn_rate_for_budget(rule.budget_spent, parse_duration(rule.long_window), 30 * DAY)
        assert derived == pytest.approx(rule.burn_rate, rel=0.01)


def test_page_needs_both_windows():
    assert [r.severity for r in evaluate_alerts({"1h": 20, "5m": 20})] == ["page"]
    # Long window is hot but the problem has stopped: no page.
    assert evaluate_alerts({"1h": 20, "5m": 0.5}) == []


def test_slow_burn_opens_a_ticket():
    fired = evaluate_alerts({"3d": 1.5, "6h": 1.2, "1h": 1.5, "5m": 1.5, "30m": 1.2})
    assert [r.severity for r in fired] == ["ticket"]


def test_missing_windows_are_skipped():
    assert evaluate_alerts({"1h": 50}) == []
