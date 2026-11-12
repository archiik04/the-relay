"""M3: measure how the real Groq service behaves, before designing around it.

Usage:
    uv run python scripts/probe_groq.py plan                 # no API calls; prints the budget
    uv run python scripts/probe_groq.py inspect              # 3 small calls: headers, usage, reasoning tokens
    uv run python scripts/probe_groq.py latency [--n 20] [--model M]
    uv run python scripts/probe_groq.py rpm                  # tiny calls until the first 429, then recovery
    uv run python scripts/probe_groq.py tpm                  # large-prompt calls until a 429, then recovery
    uv run python scripts/probe_groq.py concurrency [--k 10] # K tiny calls at once

Every request becomes one JSON line in results/probe/<phase>-<utc time>.jsonl.
That includes failures, response status, all rate-limit response headers, timings
(first chunk, first reasoning token, first answer token, last answer token, total)
and the usage Groq reports. Only RESPONSE headers are logged, so the API key
never reaches the log.

Nothing here assumes Groq's limits. The pacing defaults below are deliberately
under the documented Developer-plan numbers. The point of this script is to
find the real ones.
"""

import argparse
import asyncio
import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pymupdf

from relay.config import get_settings
from relay.papers import PAPERS

DEFAULT_MODEL = "openai/gpt-oss-20b"
LOGGED_HEADERS = ("x-ratelimit-", "retry-after", "x-request-id", "x-groq-region", "date")
ORG_ID = re.compile(r"org_[a-z0-9]{10,}")
CHARS_PER_TOKEN = 4  # rough estimate for the plan only; real counts come from `usage`

TINY = [{"role": "user", "content": "Reply with the single word: ok"}]
TINY_MAX_TOKENS = 64  # reasoning models may spend tokens thinking before "ok"


# ---------------------------------------------------------------- prompts from real paper text


def paper_excerpt(target_chars: int, rng: random.Random) -> str:
    """A contiguous run of real paper text, with page markers, from a random paper and page."""
    settings = get_settings()
    paper = rng.choice(PAPERS)
    with pymupdf.open(settings.papers_dir / paper.filename) as doc:
        start = rng.randrange(1, max(2, doc.page_count - 3))  # skip the title page
        parts, n = [], 0
        for i in range(start, doc.page_count):
            text = doc[i].get_text()
            parts.append(f"\n[{paper.key} p.{i + 1}]\n{text}")
            n += len(text)
            if n >= target_chars:
                break
    return "".join(parts)[:target_chars]


def rag_like_messages(excerpt: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": "Answer only from the excerpt. Cite pages like [moshi p.12]. "
            "If the excerpt does not say, reply exactly: The papers do not say.",
        },
        {
            "role": "user",
            "content": f"Excerpt:\n{excerpt}\n\nQuestion: What is the main point of this excerpt? "
            "Answer in two or three sentences with citations.",
        },
    ]


# ---------------------------------------------------------------- one logged request


class Log:
    def __init__(self, phase: str):
        out = get_settings().results_dir / "probe"
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.path = out / f"{phase}-{stamp}.jsonl"
        self.phase = phase

    def write(self, rec: dict) -> None:
        # 429 bodies name the Groq organisation; logs are submitted, so redact it.
        line = ORG_ID.sub("org_REDACTED", json.dumps(rec))
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


async def call(
    client: httpx.AsyncClient,
    log: Log,
    *,
    model: str,
    messages: list[dict],
    max_tokens: int,
    stream: bool = True,
    reasoning_effort: str | None = None,
    label: str = "",
) -> dict:
    body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0}
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}

    rec: dict = {
        "phase": log.phase,
        "label": label,
        "model": model,
        "stream": stream,
        "reasoning_effort": reasoning_effort,
        "max_tokens": max_tokens,
        "prompt_chars": sum(len(m["content"]) for m in messages),
        "start_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }
    t0 = time.perf_counter()
    try:
        if stream:
            async with client.stream("POST", "/chat/completions", json=body) as r:
                rec["headers_ms"] = ms(t0)
                rec["status"] = r.status_code
                rec["headers"] = {k: v for k, v in r.headers.items() if k.lower().startswith(LOGGED_HEADERS)}
                if r.status_code != 200:
                    rec["error_body"] = (await r.aread()).decode(errors="replace")[:2000]
                else:
                    text, chunks = [], 0
                    async for line in r.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break
                        chunk = json.loads(data)
                        chunks += 1
                        rec.setdefault("first_chunk_ms", ms(t0))
                        for choice in chunk.get("choices", []):
                            delta = choice.get("delta", {})
                            if delta.get("reasoning"):
                                rec.setdefault("first_reasoning_ms", ms(t0))
                            if delta.get("content"):
                                rec.setdefault("first_content_ms", ms(t0))
                                rec["last_content_ms"] = ms(t0)
                                text.append(delta["content"])
                            if choice.get("finish_reason"):
                                rec["finish_reason"] = choice["finish_reason"]
                        usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage")
                        if usage:
                            rec["usage"] = usage
                    rec["chunks"] = chunks
                    rec["answer"] = "".join(text)[:1500]
        else:
            r = await client.post("/chat/completions", json=body)
            rec["status"] = r.status_code
            rec["headers"] = {k: v for k, v in r.headers.items() if k.lower().startswith(LOGGED_HEADERS)}
            if r.status_code != 200:
                rec["error_body"] = r.text[:2000]
            else:
                payload = r.json()
                rec["usage"] = payload.get("usage")
                msg = payload["choices"][0]["message"]
                rec["finish_reason"] = payload["choices"][0].get("finish_reason")
                rec["answer"] = (msg.get("content") or "")[:1500]
                rec["reasoning_chars"] = len(msg.get("reasoning") or "")
    except httpx.HTTPError as e:
        rec["status"] = None
        rec["exception"] = f"{type(e).__name__}: {e}"[:500]
    rec["total_ms"] = ms(t0)
    log.write(rec)
    print(summary(rec))
    return rec


def summary(rec: dict) -> str:
    u = rec.get("usage") or {}
    h = rec.get("headers") or {}
    return (
        f"{rec['label']:<14} status={rec.get('status')} total={rec['total_ms']}ms "
        f"first_content={rec.get('first_content_ms')} tokens={u.get('prompt_tokens')}/{u.get('completion_tokens')} "
        f"rem_req={h.get('x-ratelimit-remaining-requests')} rem_tok={h.get('x-ratelimit-remaining-tokens')} "
        f"retry_after={h.get('retry-after')}"
    )


def client() -> httpx.AsyncClient:
    s = get_settings()
    if not s.groq_api_key:
        raise SystemExit("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")
    return httpx.AsyncClient(
        base_url=s.groq_base_url,
        headers={"Authorization": f"Bearer {s.groq_api_key.get_secret_value()}"},
        timeout=httpx.Timeout(60.0, connect=10.0),
    )


async def until_recovered(c, log, *, model, messages, max_tokens, first_wait_s: float, max_probes: int = 20):
    """After a 429: wait as told, then retry the same kind of request until it succeeds.

    Logs how long recovery actually took, measured from the 429.
    """
    t_429 = time.perf_counter()
    await asyncio.sleep(first_wait_s)
    for i in range(max_probes):
        rec = await call(c, log, model=model, messages=messages, max_tokens=max_tokens,
                         stream=False, label=f"recover-{i}")
        if rec.get("status") == 200:
            print(f"recovered {ms(t_429)} ms after the 429")
            log.write({"phase": log.phase, "label": "recovery_summary", "recovered_after_ms": ms(t_429), "probes": i + 1})
            return
        await asyncio.sleep(2)
    print("did not recover within the probe cap")


def retry_after_s(rec: dict, default: float = 2.0) -> float:
    try:
        return float((rec.get("headers") or {}).get("retry-after", default))
    except ValueError:
        return default


# ---------------------------------------------------------------- phases


async def inspect(args):
    """3 calls: what do headers, usage and reasoning look like?"""
    log = Log("inspect")
    async with client() as c:
        await call(c, log, model=args.model, messages=TINY, max_tokens=TINY_MAX_TOKENS, stream=False, label="non-stream")
        await call(c, log, model=args.model, messages=TINY, max_tokens=TINY_MAX_TOKENS, label="stream-default")
        await call(c, log, model=args.model, messages=TINY, max_tokens=TINY_MAX_TOKENS,
                   reasoning_effort="low", label="stream-low")
    print(f"log: {log.path}")


async def latency(args):
    """N realistic RAG-sized streamed calls, sequential, paced under a token-per-minute ceiling."""
    log = Log(f"latency-{args.model.split('/')[-1]}")
    rng = random.Random(args.seed)
    window: list[tuple[float, int]] = []  # (time, tokens) over the last 60 s, for pacing
    async with client() as c:
        for i in range(args.n):
            excerpt = paper_excerpt(args.prompt_chars, rng)
            msgs = rag_like_messages(excerpt)
            est = sum(len(m["content"]) for m in msgs) // CHARS_PER_TOKEN + args.max_tokens
            while True:
                now = time.monotonic()
                window[:] = [(t, n) for t, n in window if now - t < 60]
                if sum(n for _, n in window) + est <= args.tpm_ceiling:
                    break
                await asyncio.sleep(1)
            rec = await call(c, log, model=args.model, messages=msgs, max_tokens=args.max_tokens,
                             reasoning_effort=args.reasoning_effort, label=f"lat-{i}")
            used = (rec.get("usage") or {}).get("total_tokens") or est
            window.append((time.monotonic(), used))
            if rec.get("status") == 429:
                await asyncio.sleep(retry_after_s(rec, 10))
    print(f"log: {log.path}")


async def rpm(args):
    """Tiny calls back to back until the first 429 (or --max). Then measure recovery."""
    log = Log("rpm")
    async with client() as c:
        if args.settle:
            print(f"settling {args.settle}s so the per-minute window starts empty")
            await asyncio.sleep(args.settle)
        t0 = time.perf_counter()
        for i in range(args.max):
            rec = await call(c, log, model=args.model, messages=TINY, max_tokens=TINY_MAX_TOKENS,
                             stream=False, label=f"rpm-{i}")
            if rec.get("status") == 429:
                print(f"first 429 after {i} successful requests in {ms(t0)} ms")
                if args.cross_model:
                    await call(c, log, model=args.cross_model, messages=TINY, max_tokens=TINY_MAX_TOKENS,
                               stream=False, label="cross-model")
                await until_recovered(c, log, model=args.model, messages=TINY, max_tokens=TINY_MAX_TOKENS,
                                      first_wait_s=retry_after_s(rec))
                break
        else:
            print(f"no 429 after {args.max} requests in {ms(t0)} ms")
    print(f"log: {log.path}")


async def tpm(args):
    """Large-prompt, short-answer calls back to back until a 429. The remaining-tokens header
    after each call shows how the token budget is charged and refilled."""
    log = Log("tpm")
    rng = random.Random(args.seed)
    big = rag_like_messages(paper_excerpt(args.prompt_chars, rng))
    async with client() as c:
        if args.settle:
            print(f"settling {args.settle}s")
            await asyncio.sleep(args.settle)
        for i in range(args.max):
            rec = await call(c, log, model=args.model, messages=big, max_tokens=16, stream=False, label=f"tpm-{i}")
            if rec.get("status") == 429:
                await until_recovered(c, log, model=args.model, messages=big, max_tokens=16,
                                      first_wait_s=retry_after_s(rec), max_probes=5)
                break
    print(f"log: {log.path}")


async def concurrency(args):
    """K tiny calls launched at the same instant: are any refused, and does latency spread?"""
    log = Log("concurrency")
    async with client() as c:
        if args.settle:
            await asyncio.sleep(args.settle)
        await asyncio.gather(*[
            call(c, log, model=args.model, messages=TINY, max_tokens=TINY_MAX_TOKENS, stream=False, label=f"conc-{i}")
            for i in range(args.k)
        ])
    print(f"log: {log.path}")


def plan(args):
    """No API calls. Estimated cost of every phase at current settings."""
    tiny_tok = 30 + TINY_MAX_TOKENS
    lat_tok = (args.prompt_chars + 400) // CHARS_PER_TOKEN + args.max_tokens
    big_tok = (args.prompt_chars + 400) // CHARS_PER_TOKEN + 16
    rows = [
        ("inspect", 3, 3 * tiny_tok, "headers, usage fields, reasoning tokens"),
        (f"latency (n={args.n})", args.n, args.n * lat_tok, "TTFT / total / first-to-last-token gap (D1)"),
        ("latency 120b A/B (n=5)", 5, 5 * lat_tok, "120b's quota (if limits are per model)"),
        (f"rpm (max={args.max})", args.max + 6, (args.max + 6) * tiny_tok, "RPM, 429 body, retry-after, recovery"),
        ("tpm (max=6)", 7, 7 * big_tok, "TPM, how tokens are charged, recovery"),
        (f"concurrency (k={args.k})", args.k, args.k * tiny_tok, "requests in flight"),
    ]
    print(f"{'phase':<26}{'requests':>9}{'~tokens':>10}  purpose")
    for name, r, t, why in rows:
        print(f"{name:<26}{r:>9}{t:>10,}  {why}")
    main_rows = [r for r in rows if "120b" not in r[0]]
    print(f"{'total on ' + args.model:<26}{sum(r[1] for r in main_rows):>9}{sum(r[2] for r in main_rows):>10,}")
    print("token figures are chars/4 estimates; the real numbers come back in `usage`")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["plan", "inspect", "latency", "rpm", "tpm", "concurrency"])
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--max", type=int, default=40)
    p.add_argument("--prompt-chars", type=int, default=8000, help="~2K tokens of real paper text")
    p.add_argument("--max-tokens", type=int, default=400)
    p.add_argument("--reasoning-effort", choices=["low", "medium", "high"], default=None)
    p.add_argument("--tpm-ceiling", type=int, default=6000, help="pacing for the latency phase")
    p.add_argument("--settle", type=int, default=65, help="idle seconds before limit probes")
    p.add_argument("--cross-model", default="openai/gpt-oss-120b",
                   help="after the RPM 429, try one call on this model (are limits per model?)")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()
    if args.phase == "plan":
        plan(args)
    else:
        asyncio.run({"inspect": inspect, "latency": latency, "rpm": rpm, "tpm": tpm,
                     "concurrency": concurrency}[args.phase](args))


if __name__ == "__main__":
    main()
