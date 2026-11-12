"""Compare retrieval settings on the benchmark. Uses no Groq quota.

Usage: uv run python scripts/eval_retrieval.py [--repeat 3]

Writes results/retrieval/retrieval-eval-<utc>.csv: one row per (setting, question,
repeat) with coverage, evidence signals and per-stage timings. The printed summary
is computed from those rows; the CSV is the source of truth.
"""

import argparse
import csv
import math
from datetime import datetime, timezone

from relay import benchmark
from relay.config import get_settings
from relay.retrieval import RetrievalConfig, Retriever
from relay.retrieval_eval import coverage, group

GRID = [
    RetrievalConfig(chunks=ch, mode=mode, top_k=4, rerank=rr)
    for ch in ("t256-o32", "t384-o32")
    for mode, rr in (("bm25", False), ("dense", False), ("hybrid", False), ("hybrid", True))
]
STAGES = ("bm25_ms", "embed_query_ms", "dense_ms", "fusion_ms", "rerank_ms", "total_ms")


def pct(xs, p):
    xs = sorted(x for x in xs if x is not None and x != "")
    return xs[max(0, math.ceil(p / 100 * len(xs)) - 1)] if xs else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3, help="repeat each query to get stable latency numbers")
    args = ap.parse_args()

    questions = benchmark.load()
    if not questions:
        raise SystemExit("benchmark/questions.yaml has no questions yet")

    out_dir = get_settings().results_dir / "retrieval"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"retrieval-eval-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv"
    rows = []
    for cfg in GRID:
        retriever = Retriever(cfg)
        for rep in range(args.repeat):
            for q in questions:
                res = retriever.search(q.question)
                cov = coverage(q, res)
                rows.append({
                    "setting": cfg.name, "question_id": q.id, "group": group(q), "category": q.category, "repeat": rep,
                    "recall_at_k": "" if cov is None else int(cov.any_hit),
                    "full_recall": "" if cov is None else int(cov.all_evidence),
                    "first_rank": "" if cov is None or cov.first_rank is None else cov.first_rank,
                    "max_bm25": res.max_bm25, "max_cosine": res.max_cosine, "max_rerank": res.max_rerank,
                    "rerank_skipped_long_query": int(res.rerank_skipped_long_query),
                    "top_hits": " ".join(f"{h.chunk.paper}:{h.chunk.page_start}-{h.chunk.page_end}" for h in res.hits),
                    **{s: res.timings_ms.get(s, "") for s in STAGES},
                })
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)\n")
    summarise(rows)


def summarise(rows: list[dict]) -> None:
    settings = list(dict.fromkeys(r["setting"] for r in rows))
    print("ANSWERABLE (repeat 0 only for quality; all repeats for latency)")
    print(f"{'setting':<40}{'n':>4}{'recall@k':>10}{'full':>7}{'MRR':>7}{'p50 ms':>9}{'p95 ms':>9}")
    for s in settings:
        a = [r for r in rows if r["setting"] == s and r["group"] == "answerable" and r["repeat"] == 0]
        lat = [r["total_ms"] for r in rows if r["setting"] == s]
        if not a:
            continue
        rec = sum(r["recall_at_k"] for r in a) / len(a)
        full = sum(r["full_recall"] for r in a) / len(a)
        mrr = sum(1 / r["first_rank"] for r in a if r["first_rank"] != "") / len(a)
        print(f"{s:<40}{len(a):>4}{100 * rec:>9.1f}%{100 * full:>6.1f}%{mrr:>7.3f}{pct(lat, 50):>9.1f}{pct(lat, 95):>9.1f}")

    print("\nEVIDENCE SIGNALS by group (median of the best score per question; repeat 0)")
    print(f"{'setting':<40}{'group':<15}{'n':>4}{'rerank':>9}{'cosine':>9}{'bm25':>9}")
    for s in settings:
        for g in ("answerable", "near_miss", "off_topic", "false_premise"):
            grp = [r for r in rows if r["setting"] == s and r["group"] == g and r["repeat"] == 0]
            if not grp:
                continue
            med = {k: pct([r[k] for r in grp], 50) for k in ("max_rerank", "max_cosine", "max_bm25")}
            fmt = lambda v: f"{v:>9.3f}" if v is not None else f"{'-':>9}"  # noqa: E731
            print(f"{s:<40}{g:<15}{len(grp):>4}{fmt(med['max_rerank'])}{fmt(med['max_cosine'])}{fmt(med['max_bm25'])}")
            if g == "false_premise":
                with_ev = [r for r in grp if r["recall_at_k"] != ""]
                if with_ev:
                    found = sum(r["recall_at_k"] for r in with_ev)
                    print(f"{'':<40}{'':<15}     contradicting passage retrieved: {found}/{len(with_ev)}")

    print("\nLATENCY by stage, ms (p50 / p95, all repeats)")
    for s in settings:
        rs = [r for r in rows if r["setting"] == s]
        parts = []
        for st in STAGES[:-1]:
            vals = [r[st] for r in rs if r[st] != ""]
            if vals:
                parts.append(f"{st[:-3]} {pct(vals, 50):.1f}/{pct(vals, 95):.1f}")
        print(f"{s:<40}" + "  ".join(parts))


if __name__ == "__main__":
    main()
