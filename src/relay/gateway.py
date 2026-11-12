"""The model gateway (D0, D4, D5): every model call goes through it.

It is itself a ModelClient, so the pipeline doesn't know it's there.

What it does, in order:
  1. Daily budget: if the provider has blocked us for longer than any deadline (daily
     limit), answer at once with error_code="daily_budget_exhausted". No waiting, no call.
  2. Admission (D5): estimate the wait from the queue and the token-per-minute refill.
     If wait > the policy deadline, or the queue is full, reject at once
     (error_code="shed") with a retry estimate. Fast and honest beats slow and silent (D4).
  3. Bounded FIFO queue. A dispatcher releases the head when the local token buckets
     (requests/min, tokens/min, requests/day) allow. Deadlines are re-checked when a
     request leaves the queue; expired ones are dropped (status timeout).
  4. Call the provider. On 429: wait retry-after and retry, within a per-request cap and
     a global retry budget, and only if the deadline still allows. A 429 also drains the
     local token bucket: the provider knows better than our estimate.
  5. Sync with the provider's own counters (x-ratelimit-remaining-*), so a limit that
     changed without notice is learned from the headers and from the 429s.

Buckets refill continuously, as measured on Groq (M3): TPM ~133 tokens/s, RPM one per 2 s.
Tokens are reserved as prompt + max_tokens (Groq checks that at admission, measured M3/M5),
and the unused part is refunded when the call finishes.
"""

import asyncio
import time
from collections import deque
from dataclasses import dataclass

from relay.llm import ModelClient, ModelRequest, ModelResponse

CHARS_PER_TOKEN = 4  # admission estimate only; real counts come back in usage


@dataclass
class Limits:
    rpm: float = 30
    tpm: float = 8000
    rpd: float = 1000


class TokenBucket:
    """Continuous refill: `capacity` per `period_s`."""

    def __init__(self, capacity: float, period_s: float, now: float | None = None):
        self.capacity = capacity
        self.rate = capacity / period_s
        self.level = capacity
        self.t = now if now is not None else time.monotonic()

    def refill(self, now: float) -> None:
        self.level = min(self.capacity, self.level + (now - self.t) * self.rate)
        self.t = now

    def wait_for(self, amount: float, now: float) -> float:
        """Seconds until `amount` is available (0 if it is now)."""
        self.refill(now)
        if self.level >= amount:
            return 0.0
        return (min(amount, self.capacity) - self.level) / self.rate

    def take(self, amount: float, now: float) -> None:
        self.refill(now)
        self.level -= amount

    def give(self, amount: float) -> None:
        self.level = min(self.capacity, self.level + amount)


@dataclass
class _Waiter:
    est_tokens: int
    deadline: float
    future: asyncio.Future


class Gateway:
    def __init__(self, client: ModelClient, limits: Limits = Limits(), *, max_queue: int = 30,
                 deadline_s: float = 10.0, max_retries: int = 2, retry_budget_ratio: float = 0.2,
                 tpm_headroom: float = 0.9):
        self.client = client
        self.name = client.name
        self.limits = limits
        now = time.monotonic()
        # Run slightly under the provider's limit: our token estimate is approximate.
        self.rpm = TokenBucket(limits.rpm, 60, now)
        self.tpm = TokenBucket(limits.tpm * tpm_headroom, 60, now)
        self.rpd = TokenBucket(limits.rpd, 86400, now)
        self.max_queue = max_queue
        self.deadline_s = deadline_s
        self.max_retries = max_retries
        self.retry_budget_ratio = retry_budget_ratio
        self.queue: deque[_Waiter] = deque()
        self.peak_queue = 0
        self.blocked_until = 0.0  # provider said: no requests before this (daily limit)
        self.requests = 0
        self.retries = 0
        self.shed = 0
        self._wake = asyncio.Event()
        self._dispatcher: asyncio.Task | None = None

    # ------------------------------------------------------------- public: the ModelClient interface

    async def complete(self, req: ModelRequest) -> ModelResponse:
        t_start = time.perf_counter()
        est = sum(len(m["content"]) for m in req.messages) // CHARS_PER_TOKEN + req.max_tokens
        deadline = time.monotonic() + self.deadline_s
        self.requests += 1
        queue_s = retry_sleep_s = 0.0
        retries = depth = 0

        def local(code: str, **kw) -> ModelResponse:
            # Found in the limits-halved run: a request retried and THEN shed lost its retry count.
            r = self._local(t_start, code, queue_s=queue_s, **kw)
            r.retries, r.retry_sleep_ms, r.queue_depth = retries, round(retry_sleep_s * 1000, 1), depth
            return r

        while True:
            # 1. Daily budget gone: say so at once.
            if time.monotonic() < self.blocked_until:
                return local("daily_budget_exhausted", retry_after=self.blocked_until - time.monotonic())
            # Our own daily counter (synced from the provider's headers) can't refill in time.
            # Found in the first daily_exhausted run: without this check, requests waited in the
            # queue for a daily refill that takes ~86 s and timed out, instead of a labelled reply.
            daily_wait = self.rpd.wait_for(1 + len(self.queue), time.monotonic())
            if daily_wait > self.deadline_s:
                return local("daily_budget_exhausted", retry_after=daily_wait)
            # 2. Admission.
            wait = self.estimated_wait(est)
            if len(self.queue) >= self.max_queue or time.monotonic() + wait > deadline:
                self.shed += 1
                return local("shed", retry_after=wait)
            # 3. Queue.
            q0 = time.monotonic()
            depth = len(self.queue) + 1
            admitted = await self._acquire(est, deadline)
            queue_s += time.monotonic() - q0
            if not admitted:
                return local("queue_deadline", status="timeout")
            # 4. Call.
            resp = await self.client.complete(req)
            self._sync(resp, est)
            if resp.status != "rate_limited":
                break
            ra = resp.retry_after_s if resp.retry_after_s is not None else 2.0
            if ra > self.deadline_s:  # longer than anyone waits: treat as the daily limit
                self.blocked_until = time.monotonic() + ra
                break
            budget_ok = self.retries < max(1.0, self.retry_budget_ratio * self.requests)
            if retries >= self.max_retries or not budget_ok or time.monotonic() + ra > deadline:
                break
            retries += 1
            self.retries += 1
            await asyncio.sleep(ra)
            retry_sleep_s += ra
        resp.t_start = t_start  # the caller's view: waiting in the gateway counts
        resp.queue_ms = round(queue_s * 1000, 1)
        resp.retry_sleep_ms = round(retry_sleep_s * 1000, 1)
        resp.retries = retries
        resp.queue_depth = depth
        return resp

    def estimated_wait(self, est_tokens: int) -> float:
        """D5: wait ≈ the work ahead of us at the binding refill rate (tokens/min or requests/min)."""
        now = time.monotonic()
        ahead_tokens = sum(w.est_tokens for w in self.queue) + est_tokens
        ahead_reqs = len(self.queue) + 1
        return max(self.tpm.wait_for(ahead_tokens, now) if ahead_tokens <= self.tpm.capacity
                   else (ahead_tokens - self.tpm.level) / self.tpm.rate,
                   self.rpm.wait_for(ahead_reqs, now) if ahead_reqs <= self.rpm.capacity
                   else (ahead_reqs - self.rpm.level) / self.rpm.rate)

    # ------------------------------------------------------------- internals

    def _local(self, t_start: float, code: str, *, status: str = "rate_limited", retry_after: float | None = None,
               queue_s: float = 0.0) -> ModelResponse:
        now = time.perf_counter()
        return ModelResponse(status=status, model=self.name, t_start=t_start, t_end=now, error_code=code,
                             error=code, retry_after_s=None if retry_after is None else round(retry_after, 1),
                             queue_ms=round(queue_s * 1000, 1))

    async def _acquire(self, est: int, deadline: float) -> bool:
        fut = asyncio.get_running_loop().create_future()
        self.queue.append(_Waiter(est, deadline, fut))
        self.peak_queue = max(self.peak_queue, len(self.queue))
        self._ensure_dispatcher()
        self._wake.set()
        try:
            return await fut
        except asyncio.CancelledError:  # the user gave up: leave the queue
            if not fut.done():
                fut.cancel()
            raise

    def _ensure_dispatcher(self) -> None:
        if self._dispatcher is None or self._dispatcher.done():
            self._dispatcher = asyncio.create_task(self._dispatch())

    async def _dispatch(self) -> None:
        while True:
            while self.queue and (self.queue[0].future.done()):  # cancelled by a user who gave up
                self.queue.popleft()
            if not self.queue:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=5)
                except asyncio.TimeoutError:
                    if not self.queue:
                        return
                continue
            head = self.queue[0]
            now = time.monotonic()
            if now > head.deadline:  # D5: re-check the deadline when leaving the queue
                self.queue.popleft()
                head.future.set_result(False)
                continue
            wait = max(self.rpm.wait_for(1, now), self.tpm.wait_for(head.est_tokens, now), self.rpd.wait_for(1, now))
            if wait > 0:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=min(wait, max(0.01, head.deadline - now)))
                except asyncio.TimeoutError:
                    pass
                continue
            self.queue.popleft()
            self.rpm.take(1, now)
            self.tpm.take(head.est_tokens, now)
            self.rpd.take(1, now)
            head.future.set_result(True)

    def _sync(self, resp: ModelResponse, est: int) -> None:
        """Refund unused reservation; learn from the provider's own counters and 429s."""
        if resp.status == "ok":
            used = resp.prompt_tokens + resp.completion_tokens
            if used:
                self.tpm.give(max(0, est - used))
        if resp.status == "rate_limited":
            self.tpm.level = min(self.tpm.level, 0.0)  # the provider is out: stop sending for a while
            self.rpm.level = min(self.rpm.level, 0.0)
        h = resp.headers or {}
        rem_req = _num(h.get("x-ratelimit-remaining-requests"))
        if rem_req is not None:
            self.rpd.level = min(self.rpd.level, rem_req)
        rem_tok = _num(h.get("x-ratelimit-remaining-tokens"))
        if rem_tok is not None:
            self.tpm.level = min(self.tpm.level, rem_tok)
        self._wake.set()


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
