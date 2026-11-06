"""Error budget burn rates and multi-window alerting.

The alert thresholds follow the multiwindow, multi-burn-rate approach described
in the Google SRE Workbook, chapter "Alerting on SLOs". A burn rate of 1 spends
the whole error budget in exactly one SLO period.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertRule:
    severity: str
    long_window: str
    short_window: str
    burn_rate: float
    budget_spent: float  # share of the period's budget spent when the long window fires


# Defaults for a 30 day SLO period.
DEFAULT_RULES = (
    AlertRule("page", "1h", "5m", 14.4, 0.02),
    AlertRule("page", "6h", "30m", 6.0, 0.05),
    AlertRule("ticket", "3d", "6h", 1.0, 0.10),
)


@dataclass(frozen=True)
class BurnResult:
    target: float
    good: int
    total: int
    window_seconds: int
    period_seconds: int

    @property
    def error_rate(self) -> float:
        return 1 - self.good / self.total if self.total else 0.0

    @property
    def burn_rate(self) -> float:
        return self.error_rate / (1 - self.target)

    @property
    def budget_spent(self) -> float:
        """Share of the full period's error budget spent during this window."""
        return self.burn_rate * self.window_seconds / self.period_seconds

    @property
    def time_to_exhaustion_seconds(self) -> float | None:
        """How long a full budget would last at this burn rate. None if not burning."""
        return self.period_seconds / self.burn_rate if self.burn_rate > 0 else None


def burn(target: float, good: int, total: int, window_seconds: int, period_seconds: int) -> BurnResult:
    if total <= 0:
        raise ValueError("Total events must be positive.")
    if not 0 <= good <= total:
        raise ValueError("Good events must be between 0 and total.")
    if not 0 < target < 1:
        raise ValueError("The SLO target must be below 100 percent, or there is no budget to burn.")
    if window_seconds <= 0 or period_seconds <= 0:
        raise ValueError("Windows must be positive.")
    return BurnResult(target, good, total, window_seconds, period_seconds)


def evaluate_alerts(burn_rates: dict[str, float], rules=DEFAULT_RULES) -> list[AlertRule]:
    """Return the rules that fire.

    `burn_rates` maps a window name like '1h' or '5m' to the burn rate observed
    over that window. A rule fires only when both its long and short window
    exceed the threshold. The short window makes the alert reset quickly once
    the problem is fixed.
    """
    fired = []
    for rule in rules:
        long_rate = burn_rates.get(rule.long_window)
        short_rate = burn_rates.get(rule.short_window)
        if long_rate is None or short_rate is None:
            continue
        if long_rate > rule.burn_rate and short_rate > rule.burn_rate:
            fired.append(rule)
    return fired


def burn_rate_for_budget(budget_share: float, window_seconds: int, period_seconds: int) -> float:
    """Burn rate that spends `budget_share` of the budget within `window_seconds`.

    This is how the default thresholds are derived, for example 2% of a 30 day
    budget in 1 hour gives 0.02 * 720 = 14.4.
    """
    return budget_share * period_seconds / window_seconds
