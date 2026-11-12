"""One row per request for results.csv (the brief's raw file), from a pipeline record.

Required columns first, in the brief's order, then our extras (D-open-2 resolved).
`status` uses the brief's four values; what actually happened stays in `final_status`.
"""

REQUIRED = ["request_id", "scenario", "source", "start_time", "first_token_ms", "total_ms", "status", "retries",
            "tokens_in", "tokens_out", "retrieval_setting", "answer_grade"]
EXTRA = ["question_id", "final_status", "degraded", "gave_up", "model_first_token_ms", "model_last_token_ms",
         "queue_ms", "retry_sleep_ms", "queue_depth", "model_calls", "redrafts", "retrieval_ms", "model",
         # Probe rows only (Table 1 is computed from these): the provider's own rate-limit headers.
         "http_status", "retry_after_s", "rl_limit_requests", "rl_limit_tokens", "rl_remaining_requests",
         "rl_remaining_tokens"]
COLUMNS = REQUIRED + EXTRA

OK_STATUSES = {"answered", "not_in_papers", "premise_false", "unverified"}


def csv_status(final_status: str, gave_up: bool) -> str:
    if gave_up or final_status in ("model_timeout", "gave_up"):
        return "timeout"
    if final_status in OK_STATUSES:
        return "ok"
    if final_status in ("model_rate_limited", "degraded_passages"):
        return "rate_limited"
    return "error"  # search_failed, model_error


def to_row(rec: dict) -> dict:
    gave_up = bool(rec.get("gave_up"))
    row = {
        "request_id": rec["request_id"],
        "scenario": rec["scenario"],
        "source": rec["source"],
        "start_time": rec["start_utc"],
        "first_token_ms": "" if gave_up else rec.get("first_token_ms"),
        "total_ms": rec.get("total_ms"),
        "status": csv_status(rec["final_status"], gave_up),
        "retries": rec.get("retries", 0),
        "tokens_in": rec.get("tokens_in", 0),
        "tokens_out": rec.get("tokens_out", 0),
        "retrieval_setting": rec.get("retrieval_setting", ""),
        "answer_grade": rec.get("grade") or "",
        "question_id": rec.get("question_id", ""),
        "final_status": rec["final_status"],
        "degraded": int(bool(rec.get("degraded"))),
        "gave_up": int(gave_up),
        "model_first_token_ms": rec.get("model_first_token_ms"),
        "model_last_token_ms": rec.get("model_last_token_ms"),
        "queue_ms": rec.get("queue_ms", 0.0),
        "retry_sleep_ms": rec.get("retry_sleep_ms", 0.0),
        "queue_depth": rec.get("queue_depth", 0),
        "model_calls": rec.get("model_calls", 0),
        "redrafts": rec.get("redrafts", 0),
        "retrieval_ms": rec.get("retrieval_ms"),
        "model": rec.get("model", ""),
    }
    row.update({c: "" for c in COLUMNS if c not in row})
    return {k: ("" if v is None else v) for k, v in row.items()}


def probe_row(rec: dict, request_id: str) -> dict:
    """A Groq probe request (M3/M5 probes) as a results.csv row, so Table 1 is computable from the file."""
    code = rec.get("status")
    h = rec.get("headers") or {}
    u = rec.get("usage") or {}
    row = {c: "" for c in COLUMNS}
    row.update({
        "request_id": request_id,
        "scenario": f"probe-{rec.get('phase', 'unknown')}",
        "source": "real",
        "start_time": rec.get("start_utc", ""),
        "first_token_ms": rec.get("first_content_ms", "") if rec.get("first_content_ms") is not None else "",
        "total_ms": rec.get("total_ms", ""),
        "status": "ok" if code == 200 else "rate_limited" if code == 429 else "timeout" if code is None else "error",
        "retries": 0,
        "tokens_in": u.get("prompt_tokens", 0),
        "tokens_out": u.get("completion_tokens", 0),
        "question_id": rec.get("label", ""),
        "final_status": f"http_{code}",
        "model": rec.get("model", ""),
        "http_status": code if code is not None else "",
        "retry_after_s": h.get("retry-after", ""),
        "rl_limit_requests": h.get("x-ratelimit-limit-requests", ""),
        "rl_limit_tokens": h.get("x-ratelimit-limit-tokens", ""),
        "rl_remaining_requests": h.get("x-ratelimit-remaining-requests", ""),
        "rl_remaining_tokens": h.get("x-ratelimit-remaining-tokens", ""),
    })
    return row
