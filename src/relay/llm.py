"""Model clients (decision P6).

The pipeline only sees the `ModelClient` protocol: Groq now, the gateway (M5) and the
stand-in (M6) later, without changing the pipeline.

Every response carries the timestamps the latency split needs (decision P4), as
`time.perf_counter()` values so the caller can measure them from its own start:
  - t_first_token: first token of any kind (reasoning or answer). Queueing and prompt
    processing happen before it.
  - t_last_token: last token. Generation happens between the two.
Only RESPONSE headers are kept, so the API key never reaches a log.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx

from relay.config import get_settings

LOGGED_HEADERS = ("x-ratelimit-", "retry-after", "x-request-id")
ORG_ID = re.compile(r"org_[a-z0-9]{10,}")

ModelStatus = Literal["ok", "rate_limited", "timeout", "error"]


@dataclass
class ModelRequest:
    messages: list[dict]
    max_tokens: int = 512
    temperature: float = 0.0
    reasoning_effort: str | None = "low"
    json_mode: bool = True


@dataclass
class ModelResponse:
    status: ModelStatus
    text: str = ""
    model: str = ""
    http_status: int | None = None
    t_start: float = 0.0
    t_first_token: float | None = None
    t_last_token: float | None = None
    t_end: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    queue_time_s: float | None = None  # Groq's own usage.queue_time
    finish_reason: str | None = None
    retry_after_s: float | None = None
    headers: dict = field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None  # e.g. "json_validate_failed" (Groq's JSON mode, reported inside a 200 stream)


class ModelClient(Protocol):
    name: str

    async def complete(self, req: ModelRequest) -> ModelResponse: ...


class GroqClient:
    """Streams one chat completion from Groq. No retries here: retrying is policy (M5)."""

    def __init__(self, model: str = "openai/gpt-oss-20b", timeout_s: float = 60.0):
        s = get_settings()
        if not s.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")
        self.name = model
        self._http = httpx.AsyncClient(
            base_url=s.groq_base_url,
            headers={"Authorization": f"Bearer {s.groq_api_key.get_secret_value()}"},
            timeout=httpx.Timeout(timeout_s, connect=10.0),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def complete(self, req: ModelRequest) -> ModelResponse:
        body: dict = {
            "model": self.name,
            "messages": req.messages,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if req.reasoning_effort:
            body["reasoning_effort"] = req.reasoning_effort
        if req.json_mode:
            body["response_format"] = {"type": "json_object"}

        res = ModelResponse(status="error", model=self.name, t_start=time.perf_counter())
        try:
            async with self._http.stream("POST", "/chat/completions", json=body) as r:
                res.http_status = r.status_code
                res.headers = {k: v for k, v in r.headers.items() if k.lower().startswith(LOGGED_HEADERS)}
                if r.status_code != 200:
                    raw = (await r.aread()).decode(errors="replace")[:1000]
                    res.error = ORG_ID.sub("org_REDACTED", raw)
                    if r.status_code == 429:
                        res.status = "rate_limited"
                        res.retry_after_s = _float(res.headers.get("retry-after"))
                    return res
                text: list[str] = []
                async for line in r.aiter_lines():
                    if not line.startswith("data: ") or line[6:].strip() == "[DONE]":
                        continue
                    chunk = json.loads(line[6:])
                    if chunk.get("error"):  # an error reported inside a 200 stream
                        res.error = ORG_ID.sub("org_REDACTED", json.dumps(chunk["error"]))[:1000]
                        res.error_code = chunk["error"].get("code") if isinstance(chunk["error"], dict) else None
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta", {})
                        if delta.get("reasoning") or delta.get("content"):
                            now = time.perf_counter()
                            if res.t_first_token is None:
                                res.t_first_token = now
                            res.t_last_token = now
                        if delta.get("content"):
                            text.append(delta["content"])
                        if choice.get("finish_reason"):
                            res.finish_reason = choice["finish_reason"]
                    usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage")
                    if usage:
                        res.prompt_tokens = usage.get("prompt_tokens", 0)
                        res.completion_tokens = usage.get("completion_tokens", 0)
                        res.reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
                        res.queue_time_s = usage.get("queue_time")
                res.text = "".join(text)
                if res.finish_reason is None:
                    # Found in M4: a stream that ended without a finish reason or usage, and
                    # empty text, was counted as a successful call.
                    res.status = "error"
                    res.error = res.error or "stream ended without a finish_reason"
                else:
                    res.status = "ok"
        except httpx.TimeoutException as e:
            res.status, res.error = "timeout", f"{type(e).__name__}: {e}"[:300]
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            res.status, res.error = "error", f"{type(e).__name__}: {e}"[:300]
        finally:
            res.t_end = time.perf_counter()
        return res


def _float(v: str | None) -> float | None:
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None
