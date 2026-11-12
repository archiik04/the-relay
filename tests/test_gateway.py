"""M5/M6: gateway behaviour against the stand-in and scripted clients (no API calls)."""

import asyncio
import json
import time

from relay.gateway import Gateway, Limits, TokenBucket
from relay.llm import ModelRequest, ModelResponse
from relay.standin import StandIn, StandInConfig

PROMPT = [{"role": "system", "content": "s"},
          {"role": "user", "content": "Passages:\n\n[moshi-t384-0001] Moshi | 1 Intro | [moshi p.1]\n"
                                      "Moshi is a speech-text foundation model and full-duplex spoken dialogue framework."}]


def req(max_tokens=100):
    return ModelRequest(messages=PROMPT, max_tokens=max_tokens)


class Scripted:
    """Returns the given statuses in order; 'ok' or ('429', retry_after)."""

    name = "scripted"

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0

    async def complete(self, r):
        self.calls += 1
        s = self.script.pop(0) if self.script else "ok"
        t = time.perf_counter()
        if isinstance(s, tuple):
            return ModelResponse(status="rate_limited", retry_after_s=s[1], t_start=t, t_end=t)
        return ModelResponse(status="ok", text="{}", t_start=t, t_first_token=t, t_last_token=t, t_end=t,
                             prompt_tokens=10, completion_tokens=5, finish_reason="stop")


def test_bucket_refills_continuously():
    b = TokenBucket(60, 60, now=0.0)
    b.take(60, 0.0)
    assert abs(b.wait_for(1, 0.0) - 1.0) < 1e-9  # one per second
    assert b.wait_for(1, 1.0) == 0.0


def test_retry_after_429_then_success():
    async def go():
        g = Gateway(Scripted(("429", 0.05)), deadline_s=5)
        return await g.complete(req())
    r = asyncio.run(go())
    assert r.status == "ok" and r.retries == 1 and r.retry_sleep_ms >= 50


def test_retry_count_survives_when_the_retry_is_then_shed():
    async def go():
        g = Gateway(Scripted(("429", 0.05)), Limits(rpm=1000, tpm=600, rpd=1000), deadline_s=1, tpm_headroom=1.0)
        g.tpm.level = 600

        async def drain_after_429():  # after the 429 the provider's budget is empty: the retry gets shed
            await asyncio.sleep(0.01)
            g.tpm.level = 0
        asyncio.create_task(drain_after_429())
        return await g.complete(req())
    r = asyncio.run(go())
    assert r.error_code == "shed" and r.retries == 1 and r.retry_sleep_ms >= 50


def test_long_retry_after_means_daily_budget_and_no_more_calls():
    async def go():
        client = Scripted(("429", 3600))
        g = Gateway(client, deadline_s=5)
        first = await g.complete(req())
        second = await g.complete(req())
        return client.calls, first, second
    calls, first, second = asyncio.run(go())
    assert calls == 1, "after a daily-limit 429 the gateway must stop calling the provider"
    assert second.error_code == "daily_budget_exhausted" and second.retry_after_s > 3000


def test_empty_daily_counter_answers_at_once_instead_of_queueing():
    async def go():
        client = Scripted()
        g = Gateway(client, deadline_s=5)
        g.rpd.level = 0  # e.g. synced from x-ratelimit-remaining-requests: 0
        t = time.perf_counter()
        r = await g.complete(req())
        return client.calls, r, time.perf_counter() - t
    calls, r, took = asyncio.run(go())
    assert calls == 0 and r.error_code == "daily_budget_exhausted" and took < 0.1


def test_admission_sheds_immediately_when_wait_exceeds_deadline():
    async def go():
        g = Gateway(Scripted(), Limits(rpm=1000, tpm=600, rpd=1000), deadline_s=1, tpm_headroom=1.0)
        g.tpm.level = 0  # empty: the next ~100-token call needs ~10 s of refill
        t = time.perf_counter()
        r = await g.complete(req())
        return r, time.perf_counter() - t
    r, took = asyncio.run(go())
    assert r.error_code == "shed" and took < 0.1 and r.retry_after_s > 1


def test_queue_is_fifo_and_bounded():
    async def go():
        g = Gateway(Scripted(), Limits(rpm=60, tpm=10**6, rpd=1000), max_queue=3, deadline_s=10)
        g.rpm.level = 0  # one request per second from now
        tasks = [asyncio.create_task(g.complete(req())) for _ in range(5)]
        return await asyncio.gather(*tasks), g.peak_queue
    results, peak = asyncio.run(go())
    shed = [r for r in results if r.error_code == "shed"]
    assert len(shed) == 2 and peak == 3


def test_standin_429s_fast_with_headers_when_rpm_exhausted():
    async def go():
        s = StandIn(StandInConfig(rpm=2, error_rate=0, json_reject_rate=0, slow_rate=0, seed=1))
        return [await s.complete(req()) for _ in range(3)]
    a, b, c = asyncio.run(go())
    assert a.status == b.status == "ok"
    assert c.status == "rate_limited" and c.retry_after_s >= 1 and "retry-after" in c.headers
    assert a.t_first_token <= a.t_last_token and json.loads(a.text)["status"] == "answered"


def test_standin_streams_in_pieces():
    async def go():
        s = StandIn(StandInConfig(error_rate=0, json_reject_rate=0, slow_rate=0, seed=2))
        res = ModelResponse(status="ok")
        return [p async for p in s.stream(req(), res)]
    pieces = asyncio.run(go())
    assert len(pieces) > 1


def test_standin_halving_per_minute_limits_is_learned_by_the_gateway_from_429s():
    async def go():
        s = StandIn(StandInConfig(tpm=4000, error_rate=0, json_reject_rate=0, slow_rate=0, seed=4))
        s.scale_per_minute(0.5)  # provider now allows 2000 tokens/min; the gateway still believes 8000
        g = Gateway(s, deadline_s=3)
        first = await g.complete(req(max_tokens=1500))
        second = await g.complete(req(max_tokens=1500))  # provider has no room: 429, retry-after too long
        return s.tpm.capacity, first, second
    cap, first, second = asyncio.run(go())
    assert cap == 2000 and first.status == "ok"
    assert second.status in ("rate_limited", "timeout")


def test_standin_daily_limit_gives_long_retry_after():
    async def go():
        s = StandIn(StandInConfig(rpd_remaining=0, error_rate=0, seed=3))
        return await s.complete(req())
    r = asyncio.run(go())
    assert r.status == "rate_limited" and r.retry_after_s >= 60
