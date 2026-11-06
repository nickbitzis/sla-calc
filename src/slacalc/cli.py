"""Command line interface: `slacalc budget | compose | latency | burn`."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .availability import (
    Budget,
    composite,
    downtime_table,
    format_duration,
    parse_duration,
    parse_percent,
    weakest_links,
)
from .burn import DEFAULT_RULES, burn
from .latency import LatencySlo, analyze, load_samples


def pct(frac: float, digits: int = 4) -> str:
    text = f"{frac * 100:.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}%"


def table(rows: list[list[str]], align: str = "") -> str:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    out = []
    for n, row in enumerate(rows):
        cells = [c.rjust(w) if align[i:i + 1] == "r" else c.ljust(w) for i, (c, w) in enumerate(zip(row, widths))]
        out.append("  ".join(cells).rstrip())
        if n == 0:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out)


def cmd_budget(args) -> dict:
    target = parse_percent(args.target)
    period = parse_duration(args.period)
    b = Budget(target, period)
    data = {
        "target": target,
        "period_seconds": period,
        "allowed_downtime_seconds": b.allowed_downtime,
        "nines": b.nines,
        "per_window_seconds": downtime_table(target),
    }
    if not args.json:
        print(f"SLO {pct(target)} over {args.period} allows {format_duration(b.allowed_downtime)} of downtime ({b.nines:.2f} nines).\n")
        rows = [["Window", "Allowed downtime"]] + [[k, format_duration(v)] for k, v in data["per_window_seconds"].items()]
        print(table(rows, "lr"))
    return data


def parse_assignments(items: list[str]) -> dict[str, float]:
    values = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Use name=availability, got {item!r}.")
        name, val = item.split("=", 1)
        values[name.strip()] = parse_percent(val)
    return values


def cmd_compose(args) -> dict:
    values = parse_assignments(args.set or [])
    a = composite(args.expression, values)
    ranking = weakest_links(args.expression, values)
    data = {
        "expression": args.expression,
        "availability": a,
        "downtime_per_30_days_seconds": (1 - a) * 30 * 86400,
        "improvement_if_downtime_halved": dict(ranking),
    }
    if not args.json:
        print(f"System availability: {pct(a)}")
        print(f"Expected downtime:   {format_duration(data['downtime_per_30_days_seconds'])} per 30 days\n")
        if ranking:
            rows = [["Component", "Availability", "Gain if its downtime halves"]]
            rows += [[n, pct(values[n]), f"+{g * 100:.4f} pts"] for n, g in ranking]
            print(table(rows, "lrr"))
            print(f"\nFix {ranking[0][0]} first. It moves the system number the most.")
    return data


def cmd_latency(args) -> dict:
    values, errors = load_samples(args.file)
    slos = [LatencySlo.parse(s) for s in args.slo or []]
    r = analyze(values, slos, errors)
    data = {
        "count": r.count,
        "errors": r.errors,
        "error_rate": r.error_rate,
        "mean_ms": r.mean_ms,
        "max_ms": r.max_ms,
        "percentiles_ms": {f"p{p:g}": v for p, v in r.percentiles.items()},
        "slos": [{"slo": s.slo.label, "observed_ms": s.observed_ms, "met": s.met, "headroom_pct": s.headroom_pct} for s in r.slo_results],
        "all_met": r.all_met,
    }
    if not args.json:
        print(f"{r.count:,} samples, {r.errors:,} errors ({pct(r.error_rate, 2)}), mean {r.mean_ms:.1f} ms, max {r.max_ms:.1f} ms\n")
        print(table([["Percentile", "Latency"]] + [[f"p{p:g}", f"{v:.1f} ms"] for p, v in r.percentiles.items()], "lr"))
        if r.histogram:
            print("\nDistribution (log buckets)")
            peak = max(c for *_, c in r.histogram)
            for lo, hi, c in r.histogram:
                bar = "#" * max(1, round(40 * c / peak)) if c else ""
                print(f"  {lo:>8.1f} - {hi:<8.1f} ms {c:>7,} {bar}")
        if r.slo_results:
            print()
            rows = [["SLO", "Observed", "Headroom", "Result"]]
            rows += [[s.slo.label, f"{s.observed_ms:.1f} ms", f"{s.headroom_pct:+.1f}%", "met" if s.met else "MISSED"] for s in r.slo_results]
            print(table(rows, "lrrl"))
    return data


def cmd_burn(args) -> dict:
    target = parse_percent(args.slo)
    window = parse_duration(args.window)
    period = parse_duration(args.period)
    r = burn(target, args.good, args.total, window, period)
    tte = r.time_to_exhaustion_seconds
    fires = [rule for rule in DEFAULT_RULES if rule.long_window == args.window and r.burn_rate > rule.burn_rate]
    data = {
        "error_rate": r.error_rate,
        "burn_rate": r.burn_rate,
        "budget_spent_in_window": r.budget_spent,
        "time_to_exhaustion_seconds": tte,
        "matching_alert_rules": [f"{x.severity}: {x.long_window} burn > {x.burn_rate:g}" for x in fires],
    }
    if not args.json:
        print(f"Error rate {pct(r.error_rate, 3)} against a budget of {pct(1 - target, 3)}.")
        print(f"Burn rate {r.burn_rate:.2f}x. This window spent {pct(r.budget_spent, 2)} of the {args.period} budget.")
        if tte is not None:
            print(f"At this rate a full budget lasts {format_duration(tte)}.")
        if fires:
            for x in fires:
                print(f"Alert: {x.severity} ({x.long_window} burn rate above {x.burn_rate:g}, confirm with the {x.short_window} window).")
        elif any(rule.long_window == args.window for rule in DEFAULT_RULES):
            print("No alert rule for this window fires.")
    return data


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="slacalc", description="SLA, SLO, and error budget math for service owners.")
    p.add_argument("--version", action="version", version=f"slacalc {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, func, help_text):
        sp = sub.add_parser(name, help=help_text, description=help_text)
        sp.add_argument("--json", action="store_true", help="print machine-readable JSON")
        sp.set_defaults(func=func)
        return sp

    sp = add("budget", cmd_budget, "Downtime allowed by an availability target.")
    sp.add_argument("target", help="availability, e.g. 99.9 or 99.95%%")
    sp.add_argument("--period", default="30d", help="SLO period, default 30d")

    sp = add("compose", cmd_compose, "Availability of a system built from components.")
    sp.add_argument("expression", help="topology, e.g. 'lb * (app | app) * db'. '*' is series, '|' is redundant.")
    sp.add_argument("--set", nargs="+", metavar="NAME=PCT", help="component availabilities, e.g. lb=99.99 app=99.9")

    sp = add("latency", cmd_latency, "Percentiles and latency SLO checks from a CSV of samples.")
    sp.add_argument("file", help="CSV with a latency_ms column and an optional status column")
    sp.add_argument("--slo", action="append", metavar="pNN<=MS", help="latency SLO, e.g. p99<=300ms. Repeatable.")

    sp = add("burn", cmd_burn, "Error budget burn rate for one window.")
    sp.add_argument("--slo", required=True, help="availability target, e.g. 99.9")
    sp.add_argument("--good", type=int, required=True, help="good events in the window")
    sp.add_argument("--total", type=int, required=True, help="total events in the window")
    sp.add_argument("--window", default="1h", help="length of the measured window, default 1h")
    sp.add_argument("--period", default="30d", help="SLO period, default 30d")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = args.func(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(data, indent=2, default=lambda o: None))
    if args.command == "latency" and not data["all_met"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
