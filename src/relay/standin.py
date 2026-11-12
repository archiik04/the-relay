"""The stand-in model service (M6): a ModelClient we control, calibrated from real Groq.

What the brief asks it to do, and how:
  - be slow:            first-token and generation times are resampled from 70 real calls
                        (results/standin_calibration.json), with a slow-success tail;
  - fail:               a 500-style error rate, and Groq's in-stream `json_validate_failed`
                        at the measured rate (1.25%);
  - refuse at a limit:  its own RPM / TPM / RPD buckets, refilling continuously like Groq's.
                        The TPM check uses prompt + max_tokens, as Groq's does. A 429 comes back
                        fast (measured ~65 ms) with an integer retry-after and x-ratelimit headers;
  - slow down under load: first-token time grows with the number of calls in flight;
  - stream:             the reply is sent in pieces, with the generation time spread over them.

Where it is least like the real thing (for the report):
  - it runs in-process, not over the network (no TLS, DNS or connection setup);
  - the slow-down-under-load curve is an ASSUMPTION: the only real data point is 10 concurrent
    calls, which showed little slowdown (626-787 ms);
  - its answers are synthetic (a quote from the first passage), so answer quality is not measured.
"""

import asyncio
import json
import math
import random
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from relay.config import get_settings
from relay.gateway import TokenBucket
from relay.llm import ModelRequest, ModelResponse

CHARS_PER_TOKEN = 4


@dataclass
class StandInConfig:
    rpm: float = 30
    tpm: float = 8000
    rpd: float = 1000
    rpd_remaining: float | None = None  # start with part of the day already used (daily-exhausted scenario)
    error_rate: float = 0.01  # assumption: no 5xx seen in ~150 real calls, so kept small
    json_reject_rate: float | None = None  # None = measured rate from calibration
    slow_rate: float = 0.03  # "succeeds slowly": first token x slow_factor
    slow_factor: tuple[float, float] = (4.0, 10.0)
    load_knee: int = 4  # calls in flight before it slows (assumption, see module doc)
    load_slope: float = 0.15  # +15% first-token time per call in flight above the knee
    pieces: int = 8
    seed: int | None = None


class StandIn:
    def __init__(self, config: StandInConfig = StandInConfig()):
        self.name = "stand-in"
        self.cfg = config
        cal = json.loads((get_settings().results_dir / "standin_calibration.json").read_text(encoding="utf-8"))
        self.ttft = cal["ttft_s"]
        self.gen = cal["gen_s"]
        self.comp = cal["completion_tokens"]
        self.r429_s = [x / 1000 for x in cal["r429_ms"]] or [0.065]
        self.json_reject_rate = (cal["provider_json_reject_rate"] if config.json_reject_rate is None
                                 else config.json_reject_rate)
        self.rng = random.Random(config.seed)
        now = time.monotonic()
        self.rpm = TokenBucket(config.rpm, 60, now)
        self.tpm = TokenBucket(config.tpm, 60, now)
        self.rpd = TokenBucket(config.rpd, 86400, now)
        if config.rpd_remaining is not None:
            self.rpd.level = config.rpd_remaining
        self.in_flight = 0
        self.calls = 0

    def scale_per_minute(self, factor: float) -> None:
        """Change BOTH per-minute limits without telling anyone (the 'limit halved' scenario).

        Halving RPM alone would show nothing: tokens per minute is the limit that binds
        (~3 answers/min under 8K TPM, far below 30 RPM).
        """
        now = time.monotonic()
        for name in ("rpm", "tpm"):
            old = getattr(self, name)
            old.refill(now)
            new = TokenBucket(old.capacity * factor, 60, now)
            new.level = min(old.level, new.capacity)
            setattr(self, name, new)

    async def complete(self, req: ModelRequest) -> ModelResponse:
        res = ModelResponse(status="ok", model=self.name, t_start=time.perf_counter())
        text: list[str] = []
        async for piece in self.stream(req, res):
            text.append(piece)
        res.text = "".join(text)
        res.t_end = time.perf_counter()
        return res

    async def stream(self, req: ModelRequest, res: ModelResponse) -> AsyncIterator[str]:
        """Yield the reply a piece at a time, filling timestamps and usage on `res`."""
        self.calls += 1
        prompt_tokens = sum(len(m["content"]) for m in req.messages) // CHARS_PER_TOKEN
        now = time.monotonic()
        limit = self._limit_hit(prompt_tokens + req.max_tokens, now)
        if limit:
            await asyncio.sleep(self.rng.choice(self.r429_s))
            res.status, res.http_status = "rate_limited", 429
            res.retry_after_s, res.error = limit
            res.headers = self._headers(limit[0])
            return
        self.rpm.take(1, now)
        self.tpm.take(prompt_tokens + req.max_tokens, now)
        self.rpd.take(1, now)
        self.in_flight += 1
        try:
            ttft = self.rng.choice(self.ttft) * (1 + self.cfg.load_slope * max(0, self.in_flight - self.cfg.load_knee))
            if self.rng.random() < self.cfg.slow_rate:
                ttft *= self.rng.uniform(*self.cfg.slow_factor)
            await asyncio.sleep(ttft)
            if self.rng.random() < self.cfg.error_rate:
                res.status, res.http_status, res.error = "error", 500, "stand-in: internal error"
                return
            res.http_status = 200
            res.headers = self._headers(None)
            gen = self.rng.choice(self.gen)
            if req.json_mode and self.rng.random() < self.json_reject_rate:
                await asyncio.sleep(gen)  # like Groq: it generates, then rejects, and sends nothing usable
                res.status, res.error_code = "error", "json_validate_failed"
                res.error = '{"code": "json_validate_failed", "failed_generation": ""}'
                return
            body = _synthetic_draft(req)
            parts = _split(body, self.cfg.pieces)
            for i, part in enumerate(parts):
                if i:
                    await asyncio.sleep(gen / max(1, len(parts) - 1))
                now_pc = time.perf_counter()
                if res.t_first_token is None:
                    res.t_first_token = now_pc
                res.t_last_token = now_pc
                yield part
            completion = self.rng.choice(self.comp)
            res.prompt_tokens, res.completion_tokens, res.finish_reason = prompt_tokens, completion, "stop"
            # Like Groq, the final charge is what was used; refund the unused reservation.
            self.tpm.give(max(0, req.max_tokens - completion))
        finally:
            self.in_flight -= 1

    def _limit_hit(self, tokens: int, now: float) -> tuple[float, str] | None:
        """(retry-after seconds, message) if a limit is hit, like Groq's 429."""
        for bucket, amount, name in ((self.rpd, 1, "requests per day (RPD)"), (self.rpm, 1, "requests per minute (RPM)"),
                                     (self.tpm, tokens, "tokens per minute (TPM)")):
            wait = bucket.wait_for(amount, now)
            if wait > 0:
                return float(max(1, math.ceil(wait))), f"Rate limit reached on {name}"
        return None

    def _headers(self, retry_after: float | None) -> dict:
        h = {"x-ratelimit-remaining-requests": str(int(self.rpd.level)),
             "x-ratelimit-remaining-tokens": str(int(max(0, self.tpm.level)))}
        if retry_after is not None:
            h["retry-after"] = str(int(retry_after))
        return h


def _synthetic_draft(req: ModelRequest) -> str:
    """A valid draft: one claim quoting the first passage verbatim. Not a real answer."""
    prompt = req.messages[-1]["content"] if req.messages else ""
    m = re.search(r"\[([\w-]+)\][^\n]*\n(.+)", prompt)
    if not m:
        return json.dumps({"status": "not_in_papers", "claims": [], "not_covered": None})
    cid, text = m.group(1), m.group(2)
    quote = " ".join(text.split()[:12])
    return json.dumps({"status": "answered", "not_covered": None,
                       "claims": [{"text": f"(stand-in) {quote}", "chunk_id": cid, "quote": quote}]})


def _split(s: str, n: int) -> list[str]:
    size = max(1, math.ceil(len(s) / n))
    return [s[i:i + size] for i in range(0, len(s), size)]
