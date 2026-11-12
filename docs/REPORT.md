# The Relay: write-up
*Archi Kanungo · code, raw results (`results/results.csv`) and decision log: github.com/archiik04/the-relay*

> DRAFT: assistant's first draft from the measurements, for Archi to rewrite in Archi's own words.
> [TOMORROW] = numbers from the 13 Nov real runs. [ARCHI] = sections only Archi can write.

## 1. What I built and why
A Python pipeline that answers only from the three pinned papers (version stamps checked on page 1).
1. **Understand:** rules, no model call: which papers are named; is it a comparison?
2. **Retrieve:** a `search_papers` tool over 384-token section-aware chunks, BM25 + bge-small fused with RRF, top 4. It has a timeout and one retry. A two-paper question searches each paper (the branch).
3. **Draft:** one gpt-oss-20b call, returning JSON claims, each with a chunk ID and an exact quote.
4. **Check:** code verifies every quote word for word against the retrieved chunk. One redraft (the loop), else refuse.
5. **Send:** the reply is built **only** from checked claims, with citations from chunk metadata. Nothing is sent before the check.

Every model call goes through one **gateway**: token buckets matching Groq's continuously refilling limits, a bounded FIFO queue, a 10 s admission deadline, limited retries, and a labelled passages-only reply when the daily budget is gone.

**The decision that shaped it most: one model call per answer.** Measured Groq limits are 8,000 tokens/min, and each call reserves prompt + max_tokens (~2,500). That allows ~3 answers per minute. A separate model call to check the answer would halve that. So the check is code, which cost us something measurable (§8).

**What "fast" means:** a reply starts within ~1 s when idle (p50 945 ms, n=18). No admitted request waits more than 10 s in the queue. Anyone we can't serve in time is told immediately.

## 2. The real service and my stand-in
**Limits (Table 1)** were found by probing:
- tiny calls back to back until a 429 (30/min);
- large prompts until a 429 (8K tokens/min);
- 10 calls at once (all succeeded);
- reading `x-ratelimit-*` on every response (1,000 requests/day).

What surprised us:
- **Limits refill continuously** (one request per 86.4 s), not at midnight.
- Groq checks **prompt + max_tokens** when admitting a call, but charges the tokens actually used.
- **A 429 doesn't consume daily requests.**
- **JSON mode can fail server-side inside a "200 OK" stream** (`json_validate_failed`, 1.25% of calls), with nothing returned.
- Tokens per day was never reached (documented 200K, low confidence).

**Stand-in:** an in-process service behind the same interface as Groq, calibrated by resampling **70 real calls** (first token p50 655 ms, generation p50 186 ms, 168 output tokens). It returns 429s in ~65 ms with retry-after and the same headers, streams its reply in pieces, fails at the measured JSON-rejection rate, has slow outliers, and slows as calls pile up.

**Where it differs most:**
- No network, so no connection or TLS delays. Real calls showed seconds before Groq's own queue (§4).
- The slowdown under load is **assumed**. Groq showed little slowdown at 10 calls at once.
- Its answers are synthetic, so answer quality is "not measured" for stand-in rows.

## 3. Results
**Tables 1, 2a, 2b and 3 below**, all computed from `results.csv` by `scripts/analyze_results.py`.
- Percentiles are nearest-rank; n is shown next to each.
- First-token time counts only requests that got a reply.
- Real vs stand-in is marked per row: [TOMORROW] real steady and burst.

**A number we could not have guessed:** Groq's JSON mode rejected **1.25%** of outputs server-side, inside a 200 stream, every time on the same maths-heavy question (Q03).

**Answer quality (18 self-written questions):**
- **5/6 correct refusals.** All 4 near-misses and the off-topic question were refused; the false premise was refused generically instead of corrected.
- **Answerable: 4/12 correct by the automatic grader, 3/12 by my hand review.**
- **About 2,100 tokens per answer.**
- **50% of claims (10/20) said more than their own verbatim quote** (hand-labelled). The grader agreed with my verdicts on 13/18.

## 4. Where the time goes
**One slow request (Q04, real run 4): first token at 3,518 ms.**

| Phase | Time |
|---|---|
| Retrieval (working) | 24.5 ms |
| Before the model's first token (waiting) | 3,265 ms |
| Generating 212 tokens, 132 of them reasoning (working) | 226 ms |
| Quote check before sending (working) | 1.9 ms |
| Retrying | 0 |

Groq's own `usage.queue_time` covers only 368 ms of the 3,265 ms wait. **The delay was before the first token, and mostly outside Groq's reported queue** (network or front-end; not resolved).

How we know: four timestamps per request (`model_first_token_ms`, `model_last_token_ms`, `first_token_ms`, `total_ms`) plus Groq's usage fields, all in `results.csv`. Buffering for the check cost 1.9 ms.

## 5. When a limit is hit
- **Per-minute limit:** the gateway estimates the wait from the queue and the token refill rate.
  - If the wait is ≤ 10 s, the request waits in FIFO order.
  - If not, it gets an immediate "busy, try again in ~N s" (20–50 ms).
  - Everyone is delayed by at most 10 s; whoever arrives once that 10 s is used up is turned away.
  - When Groq returns a 429 anyway, we wait the retry-after and retry (at most 2 per request, 20% of traffic overall) only if the deadline still allows.
  - When the per-minute limits were halved without notice, the gateway learned it from 429s and headers. 70% still succeeded, p95 6.9 s.
- **Per-day limit:** no model call, and no fallback model (that would dodge the limits).
  - The reply is a **labelled passages-only answer**: the top 3 passages with citations, plus when full answers resume.
  - Because the limit refills one request per 86.4 s, full answers trickle back. One did at +135 s in our run.
  - Nobody gets a weaker *generated* answer; they get no generated answer, clearly marked.

## Retrieval: quality versus cost
- **Table 3:** [TOMORROW] bm25 and dense rows.
- Retrieval-only evaluation (12 answerable questions, top 4):

  | Setting | Found a gold page | MRR | p50 latency |
  |---|---|---|---|
  | hybrid | 91.7% | 0.833 | 19 ms |
  | dense | 100% | 0.840 | 16 ms |
  | bm25 | 91.7% | 0.708 | 0.8 ms |
  | + cross-encoder rerank | never better | | +600–770 ms CPU |

- **Choice: t384 hybrid, no rerank.** BM25 catches exact tokens ("Table 1", "28.4"); dense catches paraphrase. That costs 19 ms of a ~1 s request. One question is 8.3 points here, so the difference between dense and hybrid is within noise.
- **Near the limit we don't shrink retrieval.** We only degrade to settings the benchmark has measured, and fewer passages wasn't one of them. We stop at the passages-only reply instead.

## How this library will mislead a naive retriever
1. **Comparison questions pull one paper.** For Q12 (Transformer positions vs H-Net boundaries), a single search returned only H-Net passages in every setting. Fix: one search per paper.
2. **Shared vocabulary across papers.** Q04 asks about Moshi's *Depth Transformer*. The word "Transformer" pulled the Attention paper's model-variations table (attention p.9), which also lists heads and layers, into the top 4. Moshi's own table puts the Temporal Transformer's 32 heads and 32 layers next to the Depth Transformer's 16 and 6. A naive answer takes the wrong row or the wrong paper; ours cited Moshi pp.13–14.
3. **Facts that extraction loses.**
   - H-Net's boundary threshold (0.5) lives only in Equation 4, which PDF extraction drops as figure debris (Q09), so it can never be cited.
   - Table rows are merged: in Attention Table 2, four models share three BLEU values.

## 6. Retries
**Policy:**
- Retry a 429 after its retry-after, at most 2 per request and 20% of traffic, within the deadline.
- A retry-after longer than the deadline is treated as the daily limit, and we stop calling.
- Redraft a failed check once.

**A case where retrying made things worse:** in real run 1, three redrafts (Q02, Q03, Q10) each paid a second full call (~2,500 tokens reserved) and all still failed. Q10 returned the *identical* draft. Under 8K tokens/min, each wasted call is ~21 s of budget: one other person's answer.

**A result that went against my expectation:** under overload on the stand-in, *blind* 429 retries did slightly better than our gateway (21 vs 19 answered). A 429 costs Groq no daily quota and comes back in 60 ms. Lesson: **retry what is temporary; don't repeat what is deterministic.** Our gateway trades ~2 answers for never exceeding the limit.

## 7. What the person sees
At 3 pm, with the daily budget gone, the waiting person gets this within ~30 ms:

> [Limited answer] Today's answering budget is used up, so I can't write a checked answer now. Full answers resume in about N minutes. These are the most relevant passages I found; they may not answer your question:
> - [hnet p.6] 2.2.1 …: "…"

That's real passages with page citations, honest about the limit, and no guessing.

## 8. What I'm unsure about, what I left out, what I learned
**Least certain assumption:** that the quote check means "supported". It doesn't. **50% of claims overstate their quote.** If that's wrong in the user's favour, fine; if it holds, users read confident sentences with real-looking citations that say more than the source. The next step is a per-claim support check: a second model call (half the throughput) or a stricter local rule.

**Deliberately not built:**
1. A separate HTTP stand-in server (in-process instead, under deadline).
2. Priority classes and circuit breakers (no priority data; a 429 already says when to retry).

Also cut: the 20b vs 120b comparison.

**New to me:** [ARCHI], e.g. coordinated omission, or continuously refilling limits, in your own words.

## Your feedback on Vaani
[ARCHI]

## How I worked with the assistant
[ARCHI] Real transcript attached.
- **Three prompts that mattered:** [ARCHI]
- **One thing it got wrong that I caught:** candidates:
  - the version check passed v10 as v1, found via my "v6 test" explanation;
  - table splitting silently dropped text, exposed by my "no truncation" requirement;
  - the quote check rejected real quotes over a hyphen character.
- **One decision where I overruled it:** candidates: 512→384 chunks; no fallback model; the stricter support rule; separate model timestamps; the 10 s deadline.
- **What is distinctly mine:** [ARCHI]

---
## Tables (generated)
See `docs/TABLES.md`. They will be pasted here after the final run.
