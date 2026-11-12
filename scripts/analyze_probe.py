"""Summarise a probe log: latency percentiles, the D1 gap, token usage.

Usage: uv run python scripts/analyze_probe.py results/probe/latency-gpt-oss-20b-<stamp>.jsonl

Percentiles use the nearest-rank method (the smallest value with at least p% of
samples at or below it), so every reported percentile is a value that was
actually observed. With n=20, p95 is the 19th value and p99 is the maximum.
Treat p99 from 20 samples as "the slowest one we saw", not a p99.
"""

import json
import math
import sys
from collections import Counter


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def row(name: str, values: list[float]) -> str:
    if not values:
        return f"{name:<34} n=0"
    q = [pct(values, p) for p in (50, 95, 99)]
    return (f"{name:<34} n={len(values):<3} p50={q[0]:>8.1f}  p95={q[1]:>8.1f}  "
            f"p99={q[2]:>8.1f}  min={min(values):>8.1f}  max={max(values):>8.1f}")


def main(path: str) -> None:
    recs = [json.loads(line) for line in open(path, encoding="utf-8")]
    calls = [r for r in recs if "status" in r]
    ok = [r for r in calls if r.get("status") == 200]
    print(f"{path}\nrequests={len(calls)} status={dict(Counter(r.get('status') for r in calls))} "
          f"finish={dict(Counter(r.get('finish_reason') for r in ok))}\n")

    def col(key):
        return [r[key] for r in ok if r.get(key) is not None]

    print("latency, ms (client-side, from request send)")
    print(row("first byte of response (headers)", col("headers_ms")))
    print(row("first reasoning token", col("first_reasoning_ms")))
    print(row("first ANSWER token (user-visible)", col("first_content_ms")))
    print(row("last answer token", col("last_content_ms")))
    print(row("total", col("total_ms")))

    gap = [r["last_content_ms"] - r["first_content_ms"] for r in ok
           if r.get("first_content_ms") is not None and r.get("last_content_ms") is not None]
    think = [r["first_content_ms"] - r["first_reasoning_ms"] for r in ok
             if r.get("first_content_ms") is not None and r.get("first_reasoning_ms") is not None]
    print("\nderived, ms")
    print(row("D1 gap: first->last answer token", gap))
    print(row("reasoning phase: 1st reason->1st ans", think))

    u = [r["usage"] for r in ok if r.get("usage")]
    print("\nprovider-reported (usage), Groq's own timings converted to ms")
    print(row("queue_time", [x["queue_time"] * 1000 for x in u if "queue_time" in x]))
    print(row("prompt_time", [x["prompt_time"] * 1000 for x in u if "prompt_time" in x]))
    print(row("completion_time", [x["completion_time"] * 1000 for x in u if "completion_time" in x]))

    print("\ntokens per call")
    print(row("prompt_tokens", [x["prompt_tokens"] for x in u]))
    print(row("completion_tokens", [x["completion_tokens"] for x in u]))
    reasoning = [(x.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) for x in u]
    print(row("  of which reasoning", reasoning))
    print(row("  visible answer", [x["completion_tokens"] - rt for x, rt in zip(u, reasoning)]))
    total = sum(x["total_tokens"] for x in u)
    print(f"\ntotal tokens this run: {total:,}")
    if gap:
        print(f"D1 rule (median gap <= 250 ms keeps buffering): median gap = {pct(gap, 50):.1f} ms")


if __name__ == "__main__":
    main(sys.argv[1])
