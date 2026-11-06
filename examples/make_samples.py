"""Generate synthetic latency samples for the README examples.

Latency is log-normal with a small slow tail and a few 5xx errors.
The seed is fixed, so the output is the same on every run.
"""

import random
from pathlib import Path

random.seed(42)
rows = ["latency_ms,status"]
for _ in range(5000):
    slow = random.random() < 0.02
    ms = random.lognormvariate(4.3, 0.35) * (6 if slow else 1)
    status = 503 if random.random() < 0.004 else 200
    rows.append(f"{ms:.1f},{status}")
Path(__file__).with_name("api_latency.csv").write_text("\n".join(rows) + "\n")
print(f"wrote {len(rows) - 1} samples")
