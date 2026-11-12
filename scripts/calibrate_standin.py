"""Build the stand-in's calibration from real Groq measurements (M6).

Sources (all raw logs in this repo):
  - results/answers/*.jsonl: real pipeline calls with RAG-sized prompts (M4 runs 1-4).
    Only requests with exactly one model call are used, so each sample is one call:
      ttft_s  = model_first_token_ms - retrieval_ms   (queue + prompt processing)
      gen_s   = model_last_token_ms - model_first_token_ms
      completion_tokens
  - results/probe/*.jsonl: 429 response time, retry-after values, refusals.
The stand-in resamples these empirical values (bootstrap) rather than fitting a curve,
so its spread is the measured spread.

Writes results/standin_calibration.json.
"""

import glob
import json
import statistics

from relay.config import get_settings


def main() -> None:
    root = get_settings().results_dir
    ttft, gen, comp = [], [], []
    calls = provider_rejects = 0
    for path in sorted(glob.glob(str(root / "answers" / "*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            calls += r["model_calls"]
            provider_rejects += sum(1 for p in r["check_problems"] if p and "json_validate_failed" in " ".join(p))
            if "json_validate_failed" in (r.get("model_error") or ""):
                provider_rejects += 1
            if r["model_calls"] != 1 or r["model_first_token_ms"] is None or r["model_last_token_ms"] is None:
                continue
            ttft.append(round((r["model_first_token_ms"] - r["retrieval_ms"]) / 1000, 4))
            gen.append(round((r["model_last_token_ms"] - r["model_first_token_ms"]) / 1000, 4))
            comp.append(r["tokens_out"])
    r429_ms, retry_after = [], []
    for path in sorted(glob.glob(str(root / "probe" / "*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if r.get("status") == 429:
                r429_ms.append(r.get("total_ms"))
                ra = (r.get("headers") or {}).get("retry-after")
                if ra is not None:
                    retry_after.append(float(ra))
    cal = {
        "source": "M4 answer logs (single-call requests) + M3 probe 429s",
        "n_calls": len(ttft),
        "ttft_s": ttft,
        "gen_s": gen,
        "completion_tokens": comp,
        "r429_ms": [x for x in r429_ms if x is not None],
        "retry_after_s_seen": retry_after,
        "provider_json_reject_rate": round(provider_rejects / calls, 4) if calls else 0.0,
        "limits": {"rpm": 30, "tpm": 8000, "rpd": 1000},
        "summary": {
            "ttft_p50_s": statistics.median(ttft), "gen_p50_s": statistics.median(gen),
            "completion_p50": statistics.median(comp), "r429_p50_ms": statistics.median(r429_ms) if r429_ms else None,
        },
    }
    out = root / "standin_calibration.json"
    out.write_text(json.dumps(cal, indent=1), encoding="utf-8")
    print(out, json.dumps(cal["summary"]), "n =", cal["n_calls"], "json reject rate =", cal["provider_json_reject_rate"])


if __name__ == "__main__":
    main()
