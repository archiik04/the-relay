"""One row per request for results.csv (the brief's raw file), from a pipeline record.

Required columns first, in the brief's order, then our extras (D-open-2 resolved).
`status` uses the brief's four values; what actually happened stays in `final_status`.
"""

REQUIRED = ["request_id", "scenario", "source", "start_time", "first_token_ms", "total_ms", "status", "retries",
            "tokens_in", "tokens_out", "retrieval_setting", "answer_grade"]
EXTRA = ["question_id", "final_status", "degraded", "gave_up", "model_first_token_ms", "model_last_token_ms",
         "queue_ms", "retry_sleep_ms", "queue_depth", "model_calls", "redrafts", "retrieval_ms", "model"]
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
    return {k: ("" if v is None else v) for k, v in row.items()}
