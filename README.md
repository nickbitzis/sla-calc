# slacalc

A small command line tool for the reliability math that comes up in design reviews and incident retros: downtime budgets, the availability of a system built from parts, latency percentiles against an SLO, and error budget burn rates.

Pure Python, no runtime dependencies, 62 tests.

## Why

The questions are simple, but people still do them on a whiteboard and get them wrong. "Three nines" is 43 minutes a month, not an hour. Two 99.9% services in series are not 99.9%. A p99 from an average of averages is meaningless. This tool gives fast, checkable answers and prints JSON when you want to feed them into something else.

## Install

With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install .
```

Or run it in place with `uv run slacalc ...`.

## Commands

### `budget`: how much downtime a target allows

```
$ slacalc budget 99.95
SLO 99.95% over 30d allows 21m 36s of downtime (3.30 nines).

Window   Allowed downtime
-------  ----------------
day                   43s
week                5m 2s
30 days           21m 36s
quarter             1h 5m
year               4h 22m
```

### `compose`: availability of a whole system

Describe the topology with `*` for parts in series (all must be up) and `|` for redundant parts (any one is enough). `|` binds tighter than `*`, and parentheses work as usual.

```
$ slacalc compose "lb * (app | app) * db" --set lb=99.99 app=99.9 db=99.95
System availability: 99.9399%
Expected downtime:   25m 58s per 30 days

Component  Availability  Gain if its downtime halves
---------  ------------  ---------------------------
db               99.95%                  +0.0250 pts
lb               99.99%                  +0.0050 pts
app               99.9%                  +0.0001 pts

Fix db first. It moves the system number the most.
```

The ranking shows the classic result: once the app tier is redundant, the single database is what limits the system.

### `latency`: percentiles and latency SLOs from raw samples

Takes a CSV with a `latency_ms` column and an optional `status` column. Status 500 and up, or `error`/`fail`/`timeout`, counts as an error. The exit code is 1 when any SLO is missed, so it works as a CI gate for load tests.

```
$ slacalc latency examples/api_latency.csv --slo "p50<=100ms" --slo "p99<=400ms"
5,000 samples, 16 errors (0.32%), mean 86.2 ms, max 1269.6 ms

Percentile   Latency
----------  --------
p50          74.7 ms
p90         119.0 ms
p95         138.3 ms
p99         449.0 ms
p99.9       746.8 ms

Distribution (log buckets)
      10.0 - 17.8     ms       1 #
      17.8 - 31.6     ms      25 #
      31.6 - 56.2     ms   1,035 ##############
      56.2 - 100.0    ms   2,929 ########################################
     100.0 - 177.8    ms     889 ############
     177.8 - 316.2    ms      35 #
     316.2 - 562.3    ms      57 #
     562.3 - 1000.0   ms      28 #
    1000.0 - 1778.3   ms       1 #

SLO            Observed  Headroom  Result
-------------  --------  --------  ------
p50 <= 100 ms   74.7 ms    +25.3%  met
p99 <= 400 ms  449.0 ms    -12.3%  MISSED
```

The median looks healthy, but a 2% slow tail breaks the p99 target. That is the point of tracking tail latency.

### `burn`: how fast the error budget is going

```
$ slacalc burn --slo 99.9 --good 98200 --total 100000 --window 1h
Error rate 1.8% against a budget of 0.1%.
Burn rate 18.00x. This window spent 2.5% of the 30d budget.
At this rate a full budget lasts 1d 16h.
Alert: page (1h burn rate above 14.4, confirm with the 5m window).
```

Alert thresholds follow the multiwindow, multi-burn-rate approach from the Google SRE Workbook chapter "Alerting on SLOs": page at 14.4x over 1 hour or 6x over 6 hours, open a ticket at 1x over 3 days. `slacalc.burn.evaluate_alerts` checks both the long and short window for each rule.

Every command accepts `--json`.

## Use it as a library

```python
from slacalc.availability import composite
from slacalc.latency import LatencySlo, analyze

composite("lb * (app | app) * db", {"lb": 0.9999, "app": 0.999, "db": 0.9995})
analyze([12, 15, 18, 240], [LatencySlo.parse("p99<=200ms")]).all_met
```

## Tests

```bash
uv run --group dev pytest
```

The sample data in `examples/api_latency.csv` is synthetic. `examples/make_samples.py` regenerates it with a fixed seed.

## License

MIT. See [LICENSE](LICENSE).
