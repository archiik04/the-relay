"""Ask one question through the full system (pipeline + gateway) and see the checked reply.

Usage:
  uv run python scripts/ask.py "How many attention heads does the Moshi Depth Transformer use?"
  uv run python scripts/ask.py --standin "..."          # no Groq quota used (synthetic reply)
  uv run python scripts/ask.py --mode bm25 "..."        # another retrieval setting
"""

import argparse
import asyncio
import json
import sys

from relay.gateway import Gateway
from relay.llm import GroqClient
from relay.pipeline import Pipeline
from relay.retrieval import RetrievalConfig, Retriever
from relay.standin import StandIn


async def main(args) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    retriever = Retriever(RetrievalConfig(chunks="t384-o32", mode=args.mode, top_k=4))
    retriever.warm_up()
    provider = StandIn() if args.standin else GroqClient(args.model)
    pipeline = Pipeline(Gateway(provider), retriever)

    async def show_progress():  # D1: progress updates while the checked reply is prepared
        for msg in ("searching the papers…", "writing a cited answer…", "checking every quote…"):
            print(f"  [{msg}]", flush=True)
            await asyncio.sleep(0.4)

    progress = asyncio.create_task(show_progress())
    res = await pipeline.run(args.question)
    progress.cancel()
    print("\n" + res.reply + "\n")
    print(json.dumps({k: getattr(res, k) for k in (
        "final_status", "model_first_token_ms", "model_last_token_ms", "first_token_ms", "total_ms", "queue_ms",
        "retries", "model_calls", "redrafts", "tokens_in", "tokens_out")}, indent=1))
    if not args.standin:
        await provider.aclose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("question")
    p.add_argument("--standin", action="store_true")
    p.add_argument("--mode", default="hybrid", choices=["bm25", "dense", "hybrid"])
    p.add_argument("--model", default="openai/gpt-oss-20b")
    asyncio.run(main(p.parse_args()))
