"""Availability math: downtime budgets and composite availability of a system."""

from __future__ import annotations

import re
from dataclasses import dataclass

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str) -> int:
    """Parse durations like '30d', '1h', '90m', or '1h30m' into seconds."""
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*([smhdw])", text.strip().lower())
    if not parts or "".join(n + u for n, u in parts) != re.sub(r"\s+", "", text.strip().lower()):
        raise ValueError(f"Can't read duration {text!r}. Use forms like 30d, 12h, 90m, or 1h30m.")
    return int(sum(float(n) * _UNITS[u] for n, u in parts))


def format_duration(seconds: float) -> str:
    """Render seconds as a short human string, e.g. '43m 12s' or '8h 45m'."""
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds}s"
    out = []
    for name, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        qty, seconds = divmod(seconds, size)
        if qty:
            out.append(f"{qty}{name}")
    return " ".join(out[:2])


def parse_percent(value: str | float) -> float:
    """Accept 99.9, '99.9', '99.9%', or 0.999 and return a fraction in (0, 1]."""
    v = float(str(value).strip().rstrip("%"))
    frac = v / 100 if v > 1 else v
    if not 0 < frac <= 1:
        raise ValueError(f"Availability must be between 0 and 100 percent, got {value!r}.")
    return frac


@dataclass(frozen=True)
class Budget:
    target: float
    period_seconds: int

    @property
    def allowed_downtime(self) -> float:
        return (1 - self.target) * self.period_seconds

    @property
    def nines(self) -> float:
        import math

        return math.inf if self.target == 1 else -math.log10(1 - self.target)


def downtime_table(target: float) -> dict[str, float]:
    """Allowed downtime in seconds per common reporting window."""
    windows = {"day": 86400, "week": 604800, "30 days": 30 * 86400, "quarter": 91 * 86400, "year": 365 * 86400}
    return {name: (1 - target) * secs for name, secs in windows.items()}


# ---------------------------------------------------------------------------
# Composite availability.
#
# A topology is a small expression language:
#   a * b     components in series, all must be up       A = a * b
#   a | b     redundant components, any one is enough    A = 1 - (1-a)(1-b)
#   (...)     grouping
#   name      a component whose availability comes from a mapping
#   99.95     a literal availability in percent
# `|` binds tighter than `*`, so "lb * app | app * db" means lb * (app | app) * db.
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?%?)|([A-Za-z_][\w.-]*)|(\*|\||\(|\)))")


def _tokenize(expr: str) -> list[str]:
    tokens, pos = [], 0
    expr = expr.rstrip()
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m or m.end() == pos:
            raise ValueError(f"Unexpected character at position {pos} in {expr!r}.")
        tokens.append(m.group(m.lastindex))
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[str], values: dict[str, float]):
        self.tokens = tokens
        self.i = 0
        self.values = values
        self.used: set[str] = set()

    def peek(self) -> str | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> str:
        tok = self.peek()
        if tok is None:
            raise ValueError("Expression ended early.")
        self.i += 1
        return tok

    def series(self) -> float:
        a = self.parallel()
        while self.peek() == "*":
            self.take()
            a *= self.parallel()
        return a

    def parallel(self) -> float:
        down = 1 - self.atom()
        while self.peek() == "|":
            self.take()
            down *= 1 - self.atom()
        return 1 - down

    def atom(self) -> float:
        tok = self.take()
        if tok == "(":
            v = self.series()
            if self.peek() != ")":
                raise ValueError("Missing closing parenthesis.")
            self.take()
            return v
        if tok in {")", "*", "|"}:
            raise ValueError(f"Unexpected {tok!r}.")
        if tok[0].isdigit():
            return parse_percent(tok)
        if tok not in self.values:
            raise ValueError(f"No availability given for component {tok!r}.")
        self.used.add(tok)
        return self.values[tok]


def composite(expr: str, values: dict[str, float] | None = None) -> float:
    """Evaluate a topology expression and return its availability as a fraction."""
    parser = _Parser(_tokenize(expr), values or {})
    result = parser.series()
    if parser.peek() is not None:
        raise ValueError(f"Unexpected {parser.peek()!r} after the end of the expression.")
    return result


def weakest_links(expr: str, values: dict[str, float]) -> list[tuple[str, float]]:
    """Rank components by how much the whole system improves if that one gets better.

    For each component, its downtime is cut in half and the gain in system
    availability is reported. This points at the part worth investing in first.
    """
    base = composite(expr, values)
    gains = []
    for name in sorted(values):
        if not re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])", expr):
            continue
        better = {**values, name: values[name] + (1 - values[name]) / 2}
        gains.append((name, composite(expr, better) - base))
    return sorted(gains, key=lambda g: g[1], reverse=True)
