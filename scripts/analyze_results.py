"""Compute Tables 2a, 2b and 3 from results/results.csv ONLY (the brief: reviewers recompute them).

Conventions (stated in the report):
  - percentiles are nearest-rank, over the rows named in each column;
  - first-token and total time percentiles use requests that got a checked reply
    (status ok), plus degraded passages-only replies, which are still a reply;
    every row counts in the outcome percentages;
  - time is in ms; percentages have one decimal;
  - cost uses Groq's published gpt-oss-20b price ($0.075 / 1M input, $0.30 / 1M output), and is $0 on
    the free tier we actually used.

Usage: uv run python scripts/analyze_results.py [--csv results/results.csv] [--md docs/TABLES.md]
"""

import argparse
import csv
import math
from collections import defaultdict
from datetime import datetime

from relay.config import get_settings

PRICE_IN, PRICE_OUT = 0.075 / 1e6, 0.30 / 1e6


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return v[max(0, math.ceil(p / 100 * len(v)) - 1)]


def fmt(x, nd=0) -> str:
    return "not measured" if x is None else (f"{x:.{nd}f}" if nd else f"{round(x):,}")


def triple(vals: list[float]) -> str:
    return " / ".join(fmt(pct(vals, p)) for p in (50, 95, 99)) + f" (n={len(vals)})"


def share(rows, pred) -> str:
    return f"{100 * sum(1 for r in rows if pred(r)) / len(rows):.1f}%" if rows else "not measured"


def num(r, k) -> float | None:
    return float(r[k]) if r.get(k) not in (None, "") else None


def _ts(r) -> float:
    return datetime.fromisoformat(r["start_time"]).timestamp()


def _recovery(rs: list[dict]) -> tuple[int, float | None, float | None]:
    """(successes before the first 429, seconds from that 429 to the next success, 429 response ms)."""
    rs = sorted(rs, key=_ts)
    first = next((i for i, r in enumerate(rs) if r["status"] == "rate_limited"), None)
    if first is None:
        return len(rs), None, None
    # Same model only: the RPM probe also sends one call to another model (limits are per model).
    model = rs[first]["model"]
    nxt = next((r for r in rs[first + 1:] if r["status"] == "ok" and r["model"] == model), None)
    return first, (_ts(nxt) - _ts(rs[first])) if nxt else None, float(rs[first]["total_ms"])


def table1(groups) -> list[str]:
    """Table 1 from the probe rows (scenario probe-*), i.e. from results.csv like every other table."""
    probes = [r for (sc, _), rs in groups.items() if sc.startswith("probe-") for r in rs]
    if not probes:
        return []
    by = {sc: rs for (sc, _), rs in groups.items()}
    def mode(col):
        vals = [r[col] for r in probes if r[col]]
        return max(set(vals), key=vals.count) if vals else None
    rpm_ok, rpm_rec, r429_ms = _recovery(by.get("probe-rpm", []))
    tpm_ok, tpm_rec, _ = _recovery(by.get("probe-tpm", []))
    conc = by.get("probe-concurrency", [])
    conc_ok = sum(1 for r in conc if r["status"] == "ok")
    conc_ms = [float(r["total_ms"]) for r in conc]
    ras = sorted({r["retry_after_s"] for r in probes if r["status"] == "rate_limited" and r["retry_after_s"]}, key=float)
    n429 = sum(1 for r in probes if r["status"] == "rate_limited")
    return [
        "## Table 1: Limits found in the real service (computed from probe-* rows)", "",
        "| Limit | Value found | How found | Confidence |", "|---|---|---|---|",
        f"| Requests per minute | {rpm_ok} OK, then a 429 | probe-rpm: tiny calls back to back until the first 429 | high |",
        f"| Tokens per minute | {mode('rl_limit_tokens')} (header); 429 after {tpm_ok} large calls | "
        "x-ratelimit-limit-tokens on every response + probe-tpm | high |",
        f"| Requests per day | {mode('rl_limit_requests')} (header) | x-ratelimit-limit-requests; remaining drops by 1 per call | high |",
        "| Tokens per day | not observed (documented 200K) | never reached; no header reports it | low |",
        f"| Requests in flight at once | {conc_ok} of {len(conc)} succeeded at once ({fmt(min(conc_ms) if conc_ms else None)}–"
        f"{fmt(max(conc_ms) if conc_ms else None)} ms) | probe-concurrency | medium (only 10 tried) |",
        f"| What it returns at a limit | HTTP 429 in {fmt(r429_ms)} ms, retry-after {', '.join(ras)} s ({n429} 429s seen) | "
        "probe rows with status rate_limited | high |",
        f"| Time until it recovers | {tpm_rec if tpm_rec is None else round(tpm_rec * 1000):,} ms (TPM), "
        f"{rpm_rec if rpm_rec is None else round(rpm_rec * 1000):,} ms (RPM) after the first 429 | "
        "next successful call after the 429 | medium (one episode each) |", ""]


def main(args) -> None:
    rows = list(csv.DictReader(open(args.csv, encoding="utf-8")))
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["scenario"], r["source"])].append(r)
    load = {k: v for k, v in groups.items() if not k[0].startswith(("retrieval-", "probe-"))}
    retr = {k: v for k, v in groups.items() if k[0].startswith("retrieval-")}
    out: list[str] = table1(groups)

    def replied(r):
        return r["status"] == "ok" or r["degraded"] == "1"

    out += ["## Table 2a: Latency", "",
            "| Scenario | Real or stand-in | Requests sent | Duration (s) | Offered rate (per min) | "
            "First token p50 / p95 / p99 (ms) | Total time p50 / p95 / p99 (ms) |", "|---|---|---|---|---|---|---|"]
    for (sc, src), rs in sorted(load.items()):
        starts = sorted(datetime.fromisoformat(r["start_time"]) for r in rs)
        span = (starts[-1] - starts[0]).total_seconds()
        end = max(datetime.fromisoformat(r["start_time"]).timestamp() + float(r["total_ms"] or 0) / 1000 for r in rs)
        duration = end - starts[0].timestamp()
        rate = f"{len(rs)} at once" if span < 1 else f"{60 * len(rs) / span:.1f}"
        ft = [num(r, "first_token_ms") for r in rs if replied(r) and num(r, "first_token_ms") is not None]
        tt = [num(r, "total_ms") for r in rs if replied(r) and num(r, "total_ms") is not None]
        out.append(f"| {sc} | {src} | {len(rs)} | {duration:.0f} | {rate} | {triple(ft)} | {triple(tt)} |")

    out += ["", "## Table 2b: Outcomes", "",
            "| Scenario | Real or stand-in | Succeeded % | Rate-limited % | Timed out or given up % | Retries per request | "
            "Peak queue length | Tokens per answer | Cost per 1,000 answers |", "|---|---|---|---|---|---|---|---|---|"]
    for (sc, src), rs in sorted(load.items()):
        ok = [r for r in rs if r["status"] == "ok"]
        tok = [int(r["tokens_in"]) + int(r["tokens_out"]) for r in ok]
        cost = (sum(PRICE_IN * int(r["tokens_in"]) + PRICE_OUT * int(r["tokens_out"]) for r in ok) / len(ok) * 1000
                if ok else None)
        retries = sum(int(r["retries"]) for r in rs) / len(rs)
        peak = max(int(r["queue_depth"] or 0) for r in rs)
        out.append(f"| {sc} | {src} | {share(rs, lambda r: r['status'] == 'ok')} | "
                   f"{share(rs, lambda r: r['status'] == 'rate_limited')} | {share(rs, lambda r: r['status'] == 'timeout')} | "
                   f"{retries:.2f} | {peak} | {fmt(sum(tok) / len(tok)) if tok else 'not measured'} | "
                   f"{'$' + format(cost, '.2f') + ' at list price ($0 on free tier)' if cost is not None else 'not measured'} |")

    out += ["", "## Table 3: Retrieval settings", "",
            "| Setting (piece size, pieces fetched, re-rank) | Questions asked | Correct and cited % | Wrong % | "
            "Correctly refused % | Tokens per answer | First token p50 / p95 (ms) | Total time p50 / p95 (ms) |",
            "|---|---|---|---|---|---|---|---|"]
    for (sc, src), rs in sorted(retr.items()):
        setting = rs[0]["retrieval_setting"]
        size, mode, k, rr = setting.split("|")
        label = f"{size.split('-')[0][1:]} tokens, {k[1:]} pieces, {mode}, re-rank {'yes' if rr != 'norerank' else 'no'}"
        tok = [int(r["tokens_in"]) + int(r["tokens_out"]) for r in rs if r["status"] == "ok"]
        ft = [num(r, "first_token_ms") for r in rs if r["status"] == "ok"]
        tt = [num(r, "total_ms") for r in rs if r["status"] == "ok"]
        g = lambda name: share(rs, lambda r: r["answer_grade"] == name)  # noqa: E731
        out.append(f"| {label} | {len(rs)} | {g('correct')} | {g('wrong')} | {g('refused_correctly')} | "
                   f"{fmt(sum(tok) / len(tok)) if tok else 'not measured'} | "
                   f"{fmt(pct(ft, 50))} / {fmt(pct(ft, 95))} | {fmt(pct(tt, 50))} / {fmt(pct(tt, 95))} |")
    text = "\n".join(out)
    print(text)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write("# Results tables (generated by scripts/analyze_results.py from results/results.csv)\n\n" + text + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default=str(get_settings().results_dir / "results.csv"))
    p.add_argument("--md", default=None)
    main(p.parse_args())
