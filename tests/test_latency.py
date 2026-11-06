import pytest

from slacalc.latency import LatencySlo, analyze, load_samples, log_histogram, percentile


def test_percentile_matches_numpy_linear():
    data = [1, 2, 3, 4]
    assert percentile(data, 50) == 2.5
    assert percentile(data, 0) == 1
    assert percentile(data, 100) == 4
    assert percentile(list(range(1, 101)), 99) == pytest.approx(99.01)


def test_percentile_errors():
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile([1], 101)


@pytest.mark.parametrize(
    "text, p, ms",
    [("p99<=300", 99, 300), ("p99=300ms", 99, 300), ("p99.9 < 1s", 99.9, 1000), ("P50<=80MS", 50, 80)],
)
def test_parse_latency_slo(text, p, ms):
    slo = LatencySlo.parse(text)
    assert (slo.percentile, slo.threshold_ms) == (p, ms)


def test_parse_latency_slo_rejects_junk():
    with pytest.raises(ValueError):
        LatencySlo.parse("fast please")


def test_analyze_reports_met_and_missed():
    values = list(range(1, 1001))
    report = analyze(values, [LatencySlo(50, 600), LatencySlo(99, 900)])
    met, missed = report.slo_results
    assert met.met and met.headroom_pct > 0
    assert not missed.met and missed.headroom_pct < 0
    assert not report.all_met
    assert report.count == 1000
    assert report.mean_ms == pytest.approx(500.5)
    assert 99.9 in report.percentiles


def test_analyze_rejects_negative_and_empty():
    with pytest.raises(ValueError):
        analyze([])
    with pytest.raises(ValueError):
        analyze([-1, 2])


def test_histogram_counts_every_sample():
    data = sorted([1, 5, 10, 50, 100, 500, 1000, 1000])
    hist = log_histogram(data)
    assert sum(c for *_, c in hist) == len(data)
    assert hist[0][0] <= 1 and hist[-1][1] > 1000


def test_load_samples_with_status(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("latency_ms,status\n10,200\n20,503\n30,timeout\n40,404\n,200\n")
    values, errors = load_samples(f)
    assert values == [10, 20, 30, 40]
    assert errors == 2


def test_load_samples_single_column(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("12.5\n13\n")
    assert load_samples(f) == ([12.5, 13.0], 0)


def test_load_samples_needs_latency_column(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("duration,status\n10,200\n")
    with pytest.raises(ValueError, match="latency_ms"):
        load_samples(f)
