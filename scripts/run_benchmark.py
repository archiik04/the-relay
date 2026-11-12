"""M4: run the frozen benchmark through the pipeline on the real model, and grade it.

Usage:
    uv run python scripts/run_benchmark.py                          # 18 questions, gpt-oss-20b, t384 hybrid
    uv run python scripts/run_benchmark.py --model openai/gpt-oss-120b
    uv run python scripts/run_benchmark.py --mode bm25 --ids Q01 Q04

Sequential and paced under the tokens-per-minute limit (this is a quality run, not a
load test). A 429 waits for retry-after and the question is retried; the retries are
counted. Every answer is saved in full to results/answers/<run>.jsonl, so it can be
read by hand and re-graded later if the grader changes (P5).
"""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone

from relay.benchmark import load
from relay.config import get_settings
from relay.grader import GRADER_VERSION, grade
from relay.llm import GroqClient
from relay.pipeline import Pipeline
from relay.retrieval import RetrievalConfig, Retriever

TPM_CEILING = 7000  # stay under the measured 8000 TPM
RESERVE_PER_CALL = 2600  # prompt (~2000, estimate) + max_tokens 512; replaced by the measured prompt size


async def main(args) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    questions = [q for q in load() if not args.ids or q.id in args.ids]
    cfg = RetrievalConfig(chunks=args.chunks, mode=args.mode, top_k=args.k)
    retriever = Retriever(cfg)
    retriever.warm_up()  # model loading must not count against the first request's tool timeout
    model = GroqClient(args.model)
    pipeline = Pipeline(model, retriever, max_tokens=args.max_tokens, reasoning_effort=args.reasoning_effort)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = get_settings().results_dir / "answers"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"answers-{args.model.split('/')[-1]}-{cfg.chunks}-{cfg.mode}-{stamp}.jsonl"

    window: list[tuple[float, int]] = []
    reserve = RESERVE_PER_CALL
    grades: Counter = Counter()
    try:
        for q in questions:
            retries = 0
            while True:
                while True:  # pace: the last 60 s of tokens + this call's reservation under the ceiling
                    now = time.monotonic()
                    window[:] = [(t, n) for t, n in window if now - t < 60]
                    if sum(n for _, n in window) + reserve <= TPM_CEILING:
                        break
                    await asyncio.sleep(1)
                start_utc = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
                res = await pipeline.run(q.question)
                window.append((time.monotonic(), res.tokens_in + res.tokens_out or reserve))
                if res.final_status == "model_rate_limited" and retries < 3:
                    retries += 1
                    wait = res.retry_after_s or 10
                    print(f"  {q.id}: 429, waiting {wait}s (retry {retries})")
                    await asyncio.sleep(wait)
                    continue
                break
            if res.model_calls:
                reserve = max(RESERVE_PER_CALL, res.tokens_in // res.model_calls + args.max_tokens)
            d = res.to_dict()
            g = grade(q, d)
            grades[g.grade] += 1
            rec = {"question_id": q.id, "category": q.category, "start_utc": start_utc, "retries": retries,
                   "retrieval_setting": cfg.name, "grade": g.grade, "grade_reason": g.reason,
                   "missing_facts": g.missing_facts, "gold_cited": g.gold_cited, "grader": GRADER_VERSION, **d}
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"{q.id} {q.category:<22} {res.final_status:<14} {str(g.grade):<18} "
                  f"calls={res.model_calls} redrafts={res.redrafts} tok={res.tokens_in}/{res.tokens_out} "
                  f"model_first={res.model_first_token_ms} model_last={res.model_last_token_ms} "
                  f"first_token={res.first_token_ms} :: {g.reason}")
    finally:
        await model.aclose()
    print(f"\ngrades: {dict(grades)}\nlog: {path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="openai/gpt-oss-20b")
    p.add_argument("--chunks", default="t384-o32")
    p.add_argument("--mode", default="hybrid", choices=["bm25", "dense", "hybrid"])
    p.add_argument("--k", type=int, default=4)
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--reasoning-effort", default="low", choices=["low", "medium", "high"])
    p.add_argument("--ids", nargs="*")
    asyncio.run(main(p.parse_args()))
