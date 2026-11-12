"""M7: open-loop load generator. Runs the pipeline (through the gateway) under a load shape.

Open loop: every request starts at its scheduled time whatever happened to earlier ones,
and its times are measured FROM THE SCHEDULED TIME. A closed loop (send the next request
when the last one returns) would slow down exactly when the system does, and hide the
wait: coordinated omission.

Each simulated person has a patience: if no checked reply has started by then, they give
up (status timeout, gave_up=1), and their request is cancelled, leaving the queue.

Usage (examples; the scenario names are what results.csv uses):
  uv run python scripts/run_load.py steady   --source real    --rate 2  --duration 300
  uv run python scripts/run_load.py burst    --source real    --burst 12
  uv run python scripts/run_load.py overload --source standin --rate 20 --duration 300
  uv run python scripts/run_load.py rpm_halved --source standin --rate 8 --duration 300 --halve-rpm-at 60
  uv run python scripts/run_load.py daily_exhausted --source standin --rate 6 --duration 180 --rpd-remaining 5

Writes results/load/<scenario>-<source>-<utc>.jsonl (one full record per request).
"""

import argparse
import asyncio
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone

from relay.benchmark import load
from relay.config import get_settings
from relay.gateway import Gateway, Limits, NaiveRetryClient
from relay.grader import grade
from relay.llm import GroqClient
from relay.pipeline import Pipeline
from relay.retrieval import RetrievalConfig, Retriever
from relay.standin import StandIn, StandInConfig


def schedule(args, rng: random.Random) -> list[float]:
    """Arrival offsets in seconds: a burst at t=0 plus Poisson arrivals at `rate` per minute."""
    t = [0.0] * args.burst
    if args.rate > 0:
        s = 0.0
        while True:
            s += rng.expovariate(args.rate / 60)
            if s > args.duration:
                break
            t.append(s)
    return sorted(t)


async def main(args) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    rng = random.Random(args.seed)
    questions = load()
    cfg = RetrievalConfig(chunks="t384-o32", mode=args.mode, top_k=4)
    retriever = Retriever(cfg)
    retriever.warm_up()
    standin = None
    if args.source == "real":
        provider = GroqClient(args.model)
    else:
        standin = StandIn(StandInConfig(rpd_remaining=args.rpd_remaining, seed=args.seed))
        provider = standin
    if args.naive_retries:  # retry experiment: no gateway, retry every 429 after 1 s (report section 6)
        gateway = NaiveRetryClient(provider)
        gateway.peak_queue = gateway.shed = 0
    else:
        gateway = Gateway(provider, Limits(), deadline_s=args.deadline, max_queue=args.max_queue)
    pipeline = Pipeline(gateway, retriever)

    offsets = schedule(args, rng)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = get_settings().results_dir / "load" / f"{args.scenario}-{args.source}-{stamp}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"{args.scenario} ({args.source}): {len(offsets)} requests over {offsets[-1] if offsets else 0:.0f}s -> {out}")

    t0_wall = datetime.now(timezone.utc) + timedelta(seconds=1)
    t0 = time.perf_counter() + 1.0
    records: list[dict] = []

    async def one(i: int, offset: float) -> None:
        q = questions[i % len(questions)]
        await asyncio.sleep(max(0.0, t0 + offset - time.perf_counter()))
        scheduled = t0 + offset
        rec = {"request_id": f"{args.scenario}-{args.source}-{stamp}-{i:04d}", "scenario": args.scenario,
               "source": "real" if args.source == "real" else "stand-in",
               "start_utc": (t0_wall + timedelta(seconds=offset)).isoformat(timespec="milliseconds"),
               "offset_s": round(offset, 3), "question_id": q.id, "retrieval_setting": cfg.name,
               "start_lag_ms": round((time.perf_counter() - scheduled) * 1000, 1)}
        try:
            res = await asyncio.wait_for(pipeline.run(q.question), timeout=args.patience)
            d = res.to_dict()
            lag = rec["start_lag_ms"]
            # Times from the SCHEDULED start (open loop): add the lag before the task actually ran.
            for k in ("first_token_ms", "total_ms", "model_first_token_ms", "model_last_token_ms"):
                if d.get(k) is not None:
                    d[k] = round(d[k] + lag, 1)
            rec.update(d)
            rec["gave_up"] = False
            if args.source == "real":
                g = grade(q, d)
                rec["grade"] = g.grade
        except asyncio.TimeoutError:
            rec.update({"final_status": "gave_up", "gave_up": True, "total_ms": round(args.patience * 1000, 1),
                        "first_token_ms": None, "model": gateway.name})
        records.append(rec)
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"  {i:4d} +{offset:6.1f}s {q.id} {rec['final_status']:<18} first={rec.get('first_token_ms')} "
              f"queue={rec.get('queue_ms')} retries={rec.get('retries')}", flush=True)

    async def halve_rpm() -> None:
        await asyncio.sleep(max(0.0, t0 + args.halve_rpm_at - time.perf_counter()))
        standin.scale_per_minute(0.5)  # the provider changes its limits; nobody tells the gateway
        print(f"  -- provider per-minute limits halved (RPM {standin.rpm.capacity:.0f}, TPM {standin.tpm.capacity:.0f}) "
              f"at +{args.halve_rpm_at}s (gateway not told)", flush=True)

    try:
        tasks = [asyncio.create_task(one(i, o)) for i, o in enumerate(offsets)]
        if args.halve_rpm_at is not None and standin is not None:
            tasks.append(asyncio.create_task(halve_rpm()))
        await asyncio.gather(*tasks)
    finally:
        if args.source == "real":
            await provider.aclose()
    by: dict = {}
    for r in records:
        by[r["final_status"]] = by.get(r["final_status"], 0) + 1
    print(f"done: {by} peak_queue={gateway.peak_queue} shed={gateway.shed} gateway_retries={gateway.retries}"
          + (f" provider_calls={gateway.provider_calls}" if args.naive_retries else "")
          + (f" provider_calls={standin.calls}" if standin is not None else ""))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("scenario")
    p.add_argument("--source", choices=["real", "standin"], required=True)
    p.add_argument("--rate", type=float, default=0.0, help="Poisson arrivals per minute")
    p.add_argument("--duration", type=float, default=0.0, help="seconds of Poisson arrivals")
    p.add_argument("--burst", type=int, default=0, help="requests all at t=0")
    p.add_argument("--patience", type=float, default=30.0, help="seconds a person waits for the reply to start")
    p.add_argument("--deadline", type=float, default=10.0, help="gateway policy deadline (D5, D8: 10 s)")
    p.add_argument("--max-queue", type=int, default=30)
    p.add_argument("--halve-rpm-at", type=float, default=None,
                   help="stand-in: halve its per-minute limits (RPM and TPM) at this second")
    p.add_argument("--rpd-remaining", type=float, default=None, help="stand-in: requests left today at start")
    p.add_argument("--mode", default="hybrid", choices=["bm25", "dense", "hybrid"])
    p.add_argument("--model", default="openai/gpt-oss-20b")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--naive-retries", action="store_true", help="experiment: bypass the gateway, retry 429s blindly")
    asyncio.run(main(p.parse_args()))
