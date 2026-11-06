"""Latency percentiles and latency SLO checks."""

from __future__ import annotations

import csv
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

STANDARD_PERCENTILES = (50, 90, 95, 99, 99.9)


def percentile(sorted_values: Sequence[float], p: float) -> float:
    """Percentile with linear interpolation between ranks (same as numpy's default).

    `sorted_values` must already be sorted ascending.
    """
    if not sorted_values:
        raise ValueError("No samples.")
    if not 0 <= p <= 100:
        raise ValueError(f"Percentile must be between 0 and 100, got {p}.")
    rank = (len(sorted_values) - 1) * p / 100
    lo, hi = math.floor(rank), math.ceil(rank)
    if lo == hi:
        return float(sorted_values[lo])
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (rank - lo)


@dataclass(frozen=True)
class LatencySlo:
    percentile: float
    threshold_ms: float

    @classmethod
    def parse(cls, text: str) -> LatencySlo:
        """Parse 'p99<=300', 'p99=300ms', or 'p99.9 < 1s'."""
        m = re.fullmatch(r"\s*p(\d+(?:\.\d+)?)\s*(?:<=|<|=)\s*(\d+(?:\.\d+)?)\s*(ms|s)?\s*", text, re.IGNORECASE)
        if not m:
            raise ValueError(f"Can't read latency SLO {text!r}. Use a form like p99<=300ms.")
        threshold = float(m.group(2)) * (1000 if (m.group(3) or "ms").lower() == "s" else 1)
        return cls(float(m.group(1)), threshold)

    @property
    def label(self) -> str:
        return f"p{self.percentile:g} <= {self.threshold_ms:g} ms"


@dataclass(frozen=True)
class SloResult:
    slo: LatencySlo
    observed_ms: float

    @property
    def met(self) -> bool:
        return self.observed_ms <= self.slo.threshold_ms

    @property
    def headroom_pct(self) -> float:
        """Positive means room to spare, negative means over the threshold."""
        return (self.slo.threshold_ms - self.observed_ms) / self.slo.threshold_ms * 100


@dataclass
class LatencyReport:
    count: int
    errors: int
    mean_ms: float
    max_ms: float
    percentiles: dict[float, float]
    slo_results: list[SloResult]
    histogram: list[tuple[float, float, int]]

    @property
    def error_rate(self) -> float:
        return self.errors / self.count if self.count else 0.0

    @property
    def all_met(self) -> bool:
        return all(r.met for r in self.slo_results)


def load_samples(path: str | Path) -> tuple[list[float], int]:
    """Read latencies from a CSV.

    The file needs a `latency_ms` column (or a single unnamed numeric column).
    An optional `status` column marks errors: any HTTP status of 500 or above,
    or the words error/fail/timeout, counts as an error.
    """
    text = Path(path).read_text().strip().splitlines()
    if not text:
        raise ValueError(f"{path} is empty.")
    first = [c.strip().lower() for c in text[0].split(",")]
    if "latency_ms" not in first:
        try:
            return [float(line.split(",")[0]) for line in text if line.strip()], 0
        except ValueError as exc:
            raise ValueError(f"{path} needs a latency_ms column.") from exc
    values, errors = [], 0
    for row in csv.DictReader(text):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        if not row.get("latency_ms"):
            continue
        values.append(float(row["latency_ms"]))
        status = row.get("status", "").lower()
        if status and (status in {"error", "fail", "failed", "timeout"} or (status.isdigit() and int(status) >= 500)):
            errors += 1
    return values, errors


def log_histogram(sorted_values: Sequence[float], buckets_per_decade: int = 4) -> list[tuple[float, float, int]]:
    """Count samples into log-spaced buckets, which suit long-tailed latency data."""
    positive = [v for v in sorted_values if v > 0]
    if not positive:
        return []
    lo = math.floor(math.log10(positive[0]) * buckets_per_decade)
    hi = math.floor(math.log10(positive[-1]) * buckets_per_decade)
    edges = [10 ** (i / buckets_per_decade) for i in range(lo, hi + 2)]
    counts = [0] * (len(edges) - 1)
    for v in positive:
        idx = min(len(counts) - 1, math.floor(math.log10(v) * buckets_per_decade) - lo)
        counts[idx] += 1
    return [(edges[i], edges[i + 1], c) for i, c in enumerate(counts)]


def analyze(values: Iterable[float], slos: Sequence[LatencySlo] = (), errors: int = 0) -> LatencyReport:
    data = sorted(float(v) for v in values)
    if not data:
        raise ValueError("No samples to analyze.")
    if data[0] < 0:
        raise ValueError("Latencies can't be negative.")
    wanted = sorted(set(STANDARD_PERCENTILES) | {s.percentile for s in slos})
    pct = {p: percentile(data, p) for p in wanted}
    return LatencyReport(
        count=len(data),
        errors=errors,
        mean_ms=sum(data) / len(data),
        max_ms=data[-1],
        percentiles=pct,
        slo_results=[SloResult(s, pct[s.percentile]) for s in slos],
        histogram=log_histogram(data),
    )
