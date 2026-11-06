import math

import pytest

from slacalc.availability import (
    Budget,
    composite,
    downtime_table,
    format_duration,
    parse_duration,
    parse_percent,
    weakest_links,
)


@pytest.mark.parametrize(
    "text, seconds",
    [("30d", 2_592_000), ("1h", 3600), ("90m", 5400), ("1h30m", 5400), ("2w", 1_209_600), ("45s", 45)],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("bad", ["", "30", "1x", "1h junk", "h"])
def test_parse_duration_rejects_junk(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)


def test_format_duration():
    assert format_duration(43) == "43s"
    assert format_duration(2592) == "43m 12s"
    assert format_duration(90061) == "1d 1h"


@pytest.mark.parametrize("value, frac", [(99.9, 0.999), ("99.95%", 0.9995), (0.999, 0.999), ("100", 1.0)])
def test_parse_percent(value, frac):
    assert parse_percent(value) == pytest.approx(frac)


@pytest.mark.parametrize("bad", ["0", "-5", "101", "abc"])
def test_parse_percent_rejects_out_of_range(bad):
    with pytest.raises(ValueError):
        parse_percent(bad)


def test_three_nines_budget():
    b = Budget(0.999, 30 * 86400)
    assert b.allowed_downtime == pytest.approx(2592)  # 43m 12s
    assert b.nines == pytest.approx(3)
    assert Budget(1.0, 86400).nines == math.inf


def test_downtime_table_year_for_four_nines():
    assert downtime_table(0.9999)["year"] == pytest.approx(3153.6)


def test_series_multiplies():
    assert composite("a * b", {"a": 0.99, "b": 0.99}) == pytest.approx(0.9801)


def test_parallel_combines_failures():
    assert composite("a | a", {"a": 0.99}) == pytest.approx(0.9999)


def test_literals_and_grouping():
    assert composite("99.99 * (99 | 99)") == pytest.approx(0.9999 * 0.9999)


def test_parallel_binds_tighter_than_series():
    values = {"lb": 0.9999, "app": 0.999, "db": 0.9995}
    assert composite("lb * app | app * db", values) == pytest.approx(composite("lb * (app | app) * db", values))


@pytest.mark.parametrize(
    "expr, message",
    [("a *", "ended early"), ("(a * a", "closing"), ("a a", "after the end"), ("a $ a", "Unexpected character"), ("x", "No availability")],
)
def test_composite_errors(expr, message):
    with pytest.raises(ValueError, match=message):
        composite(expr, {"a": 0.99})


def test_weakest_link_is_the_single_point_of_failure():
    values = {"lb": 0.9999, "app": 0.999, "db": 0.9995}
    ranking = weakest_links("lb * (app | app) * db", values)
    assert [name for name, _ in ranking] == ["db", "lb", "app"]
    assert all(gain > 0 for _, gain in ranking)


def test_weakest_links_skips_unused_components():
    ranking = weakest_links("a * b", {"a": 0.99, "b": 0.99, "ab": 0.5})
    assert {name for name, _ in ranking} == {"a", "b"}
