# Groq probe findings (feeds Table 1)

Raw evidence: `results/probe/*.jsonl` (organisation ID redacted). Every claim cites its run.
Model: `openai/gpt-oss-20b` unless stated. Free account, `x-groq-region: bom`.
Spent so far on 20b (2026-11-11): **42 requests, 12,362 tokens** (sum of `usage.total_tokens`).

## Table 1 draft
| Limit | Value found | How found | Confidence |
|---|---|---|---|
| Requests per minute | **30** | `rpm` run: 30 back-to-back calls succeeded, the 31st returned 429 "RPM: Limit 30, Used 30, Requested 1" | High |
| Tokens per minute | **8,000** | `x-ratelimit-limit-tokens: 8000` on every response; `tpm` run's 429 "TPM: Limit 8000" | High |
| Requests per day | **1,000** | `x-ratelimit-limit-requests: 1000` on every response | High that it's the limit; see refill below |
| Tokens per day | **200,000 (docs only)** | Groq rate-limits page (fetched 2026-11-11). Not in any header; not reached. | Low: unobserved |
| Requests in flight at once | not measured yet | `concurrency` phase pending | — |
| What it returns at a limit | HTTP **429** in ~60–70 ms; `retry-after` header in **whole seconds, rounded up**; JSON body `type: "requests"` or `"tokens"`, `code: "rate_limit_exceeded"`, and the exact wait ("try again in 1.335s") | `rpm` + `tpm` runs | High |
| Time until it recovers | **~2.6–2.8 s** after a per-minute 429 (wait `retry-after`, then one retry succeeded) | `recover-0` in `rpm` and `tpm` runs | Medium (n=1 each) |

## How the limits behave (beyond the numbers)
| Finding | Evidence | Confidence |
|---|---|---|
| **TPM refills continuously** at 8000/60 = 133.3 tokens/s | `(8000 − remaining) ÷ reset-tokens` = 133.3 on every inspect call. The 429's "try again in 1.335s" = (2104 − 1926) ÷ 133.3 exactly. | High |
| **The daily request limit refills continuously**, one request per 86.4 s, not at midnight | `reset-requests` = 86.4 s × deficit. **Prediction confirmed:** after ~7 idle min, the 3 inspect requests had returned (`rpm-0` showed 999, not 996), with no UTC midnight in between. | Medium-high. Never observed at real exhaustion. |
| **RPM also behaves like a refilling bucket**: one slot every 2 s | RPM 429 said "try again in 2s" (= 60/30), and a retry 2.8 s later succeeded | Medium (n=1) |
| **Limits are per model** | While 20b was RPM-blocked, a 120b call succeeded and showed its own fresh counters (999 / 7858) | High |
| **The limit check uses prompt + `max_tokens`** | 429 body: "Requested 2104" = 2088 prompt + 16 max_tokens | High |
| **What's finally charged is unclear** | From a full bucket: `max_tokens=64` charged 142 (= prompt + cap) twice; `max_tokens=4000` charged 110 (= actual use) once. These don't fit one rule. | **Unresolved.** An earlier "hint" that it always charges the cap is withdrawn. |
| gpt-oss produces hidden reasoning tokens that count as output | "ok": 22 of 32 tokens were reasoning (default), 8 of 18 (`low`). 2K-token prompt: 14 of 16 before the cap cut it off (`finish_reason: length`). | High that it happens |
| Reasoning streams before the answer | first reasoning chunk precedes first content chunk on both streamed calls | High that it happens; timing n=1 |
| Groq reports its own server-side queue time | `usage.queue_time`: 0.05–0.98 s seen | High that the field exists |

## Latency on realistic prompts (`latency`, 2026-11-11 18:21 UTC)
File: `results/probe/latency-gpt-oss-20b-20261111T182116Z.jsonl`. 20 streamed calls, **sequential, low load**, ~2.2K-token prompts of real paper text, `max_tokens=400`, default reasoning. All 20 returned `200` / `finish_reason: stop`. Nearest-rank percentiles; with n=20, p99 = the slowest call.

| Measure (ms) | p50 | p95 | max |
|---|---|---|---|
| First visible answer token | 822.5 | 1102.5 | 1662.9 |
| Total | 1011.9 | 1309.2 | 1672.0 |
| **D1 gap** (first → last answer token) | **145.3** | 191.3 | 203.0 |
| Reasoning phase (first reasoning → first answer token) | 159.6 | 234.1 | 321.4 |
| Groq `queue_time` (server-reported) | **336.0** | 391.0 | 465.8 |
| Groq `prompt_time` | 131.5 | 186.3 | 328.6 |
| Groq `completion_time` | 338.0 | 460.5 | 490.3 |

| Tokens per call | p50 | p95 | max |
|---|---|---|---|
| prompt | 2206 | 2542 | 3417 |
| completion | 302 | 384 | **394** (cap was 400) |
| of which hidden reasoning | 168 | 211 | 245 |
| visible answer | 146 | 186 | 186 |

**Readings:**
- **D1 is settled: buffer.** Median gap 145 ms ≤ 250 ms, and even the slowest of the 20 (203 ms) is under it.
- **About a third of a typical request's time is spent waiting in Groq's own queue** (median 336 ms of ~1012 ms), even at our low load. That's a number we couldn't have guessed.
- **Reasoning is more than half of output tokens** (168 of 302) and delays the first answer token by ~160 ms (median).
- **TPM binds long before RPM.** At ~2.5K tokens per call, 8000 TPM allows ~3 calls/minute; 30 RPM would allow 30. At ~2.5K per call, a 200K tokens/day budget (docs; unverified) ≈ 80 calls/day.
- **`max_tokens=400` was nearly too tight**: the longest completion used 394. Raise it (~512) or lower reasoning, then re-check.
- **Not representative of:** load (calls were one at a time), our real questions (prompts asked for "the main point of this excerpt"), or the 120b model.

## Design consequences
1. **The gateway reserves prompt + `max_tokens` before calling**, because that's the check Groq applies. Whether Groq later refunds unused tokens doesn't change this rule. It only changes how quickly capacity comes back, which we read from the headers anyway.
2. **`max_tokens` is a capacity lever.** A tight cap lets more requests pass Groq's check. But gpt-oss spends part of the cap on hidden reasoning (14 of 16 here), so a cap that's too tight cuts off the *answer* (`finish_reason: length`). We tune it on real questions in M4.
3. **Our gateway limiters are continuous buckets**: tokens 133.3/s (capacity 8000), requests 0.5/s (capacity 30), daily requests 1/86.4 s (capacity 1000). These copy the provider's own shapes.
4. **3pm "daily budget gone" ≈ 41 full answers/hour across all users**, not "zero until midnight". The reply people see should say capacity is limited, not "come back tomorrow."
5. **Per-model limits make a 20b→120b fallback technically possible.** Whether it's legitimate is still D-open-3.

## Still to measure
- Latency distributions on realistic prompts (`latency` phase), including the D1 first-to-last-token gap.
- Requests in flight (`concurrency` phase).
- (Optional, 1–2 requests) repeat `max_tokens=4000` from a full bucket to see whether the 110 repeats.
