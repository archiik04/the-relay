# Decision log

Each entry: what we decided, why, what we rejected, what it costs, and what
would make us revisit it. Status is **Accepted**, **Tentative** (waiting on a
measurement), or **Open**. "Who" records whose idea it was, since the brief asks
what in the submission is distinctly mine.

Labels used below:
- **[Brief]**: a requirement of the assignment.
- **[Rec]**: an engineering recommendation.
- **[Hyp]**: an experimental hypothesis, not yet measured.

---

## D0: Overall architecture: async pipeline + one model gateway
**Status:** Accepted (2026-11-11) · **Who:** assistant proposed, Archi accepted

- **Decision:** asyncio pipeline (understand → retrieve [tool] → evidence check [branch/loop] → draft → verify). **Every** model call goes through a single gateway that owns rate limits, budgets, retries and deadlines.
- **Rejected:**
  - A sequential pipeline: it can't show overload at all.
  - A plain async pipeline: it sends a flood of 429s and retry storms.
  - The full set of reliability mechanisms: too much to build and defend in 4 days.
- **Deliberately not built:**
  - Circuit breakers. Groq's 429 already says what's wrong and when to retry.
  - Response caching. It would hide the latency we must measure.
  - Redis, Kafka, a vector database, Kubernetes.
- **Cost:** we deliberately cap throughput below the provider limit, so some requests are shed that a naive system would have *attempted*.
- **Revisit if:** measurements show the gateway itself adds noticeable latency, or failures that aren't 429s dominate.

## D1: Buffer the full answer, verify it, then send
**Status:** **Accepted (2026-11-11), by measurement:** median first→last answer-token gap = **145.3 ms** (p95 191.3, max 203.0; n=20, `latency-gpt-oss-20b-20261111T182116Z.jsonl`) ≤ the 250 ms rule set in advance · **Who:** assistant framed the options; Archi chose the decision threshold

- **Decision:** generate the whole answer, check its citations, then send it. Show progress updates ("searching… found 4 passages… writing") while the user waits. **Progress updates are not answer tokens** and don't count toward `first_token_ms`.
- **Rejected:**
  - Raw token streaming: it sends text that hasn't been checked. The brief says never send a wrong answer to stay fast.
  - Sentence-gated streaming: sentences already shown can't be taken back if a later one fails the check, and a sentence can be true alone but misleading if the answer stops there.
- **Rule set in advance (Archi):** buffering stays if the measured **median gap between the model's first and last output token is ≤ 250 ms**. Archi's reasoning: extra wait above ~200–250 ms is noticeable. Supporting reference: commonly cited usability thresholds (~100 ms feels instant, ~1 s keeps flow).
- **Cost:** user-facing first-token time ≈ total time. We still log the provider's own first-token time for calibration and for report section 4.
- **Revisit if:** the median gap is > 250 ms, or reasoning-token overhead makes total time much longer than expected.

## D2: Primary model: `openai/gpt-oss-20b`
**Status:** Tentative, small 20b-vs-120b A/B in M3 · **Who:** assistant, from Groq docs

- **Groq docs, fetched 2026-11-11 (to be verified on our account):** Llama models are Enterprise-only. gpt-oss-20b and gpt-oss-120b are Production status. qwen3.8-27b is Preview, which the docs say "may be discontinued at short notice."
- Documented limits for 20b and 120b are identical: **30 RPM / 1K RPD / 8K TPM / 200K TPD**. ⚠ The page says these are "base limits for the Developer plan", so they **may not be our free-tier limits**.
- Published paid price, which we'll use for "cost per 1,000 answers": 20b $0.075 in / $0.30 out per 1M tokens; 120b $0.15 / $0.60.
- **Why 20b:** same limits as 120b, Production status, lower latency and price [Hyp].
- **Risk:** gpt-oss models are reasoning models. Hidden reasoning tokens use TPM and delay the first token. **Measure this.**
- **Revisit if:** 120b is clearly more accurate on the A/B test. "Good" is non-negotiable (D4).

## D3: No LLM call for the "understand" step (rule-based scope check + query rewrite)
**Status:** Tentative, pending verified limits · **Who:** assistant, from the budget arithmetic

- **Why:** if the documented 8K TPM / 200K TPD apply to us, one answer (~2–3.5K tokens [Hyp]) means only ~2–4 answers can start per minute, and ~60–100 answers fit in a day. A second LLM call per request roughly halves that.
- **Cost:** weaker query understanding, so some out-of-scope questions may get through to retrieval. The evidence check and the verifier are the safety net.

## D4: Priorities: keep fast, good and cheap; give up "nobody turned away"
**Status:** Accepted · **Who:** Archi, with the reasoning refined in discussion

- Under overload, people get turned away either way: **fast and honestly** (load shedding) or **slowly and silently** (timeouts after a long wait). We choose fast and honest.
- On the free tier, "cheap" means **daily quota**. Waste in the morning (retries, answers for users who already left) turns everyone away in the afternoon.

## D5: Admission policy
**Status:** Accepted, design · **Who:** Archi drafted it; the assistant corrected the ordering rule and the degradation rule

- **Bounded FIFO queue.** Admit a request only if estimated wait + service time ≤ the policy deadline.
  - Wait is estimated from **both RPM and TPM headroom**: wait ≈ queue position × calls per request ÷ available rate, whichever limit binds first.
- **Re-check the deadline when a request leaves the queue**, and drop it if it has expired.
- **Rejection is immediate** and includes a retry estimate based on how fast the queue is currently draining. That estimate is not a guarantee.
- **Degrade only to retrieval settings the benchmark has approved** (accuracy within an agreed margin of the best setting), and **always label** a degraded answer. Per-request checks can't prove a setting's quality; the benchmark does.
- **Rejected:**
  - Earliest-deadline-first: under overload it fails in a cascade, serving the requests most likely to miss anyway.
  - Priority classes: we have no real priority data.
  - Unbounded queue: turns rejections into timeouts.
- **Correction recorded:** starvation is not a risk. Deadlines bound how long anyone waits.
- **Note:** the server's **policy deadline** differs from the user's hidden **patience**. That gap is a candidate for the "least certain assumption" (report §8).
- **Headline metric (Archi):** **goodput per unit of daily quota**, i.e. useful verified answers per 1K tokens spent.
- **Experiment:** FIFO-only vs deadline-aware admission under the same burst, run on the stand-in so it costs no quota.

## D6: Paper versions are pinned and verified
**Status:** Accepted (M0) · **Who:** assistant

- `scripts/fetch_papers.py` downloads `arxiv.org/pdf/<id>v<N>` and checks that page 1 carries arXiv's stamp for **that exact version**. It records sha256 hashes in `papers/manifest.json`.
- PDFs are gitignored (we don't redistribute them). The manifest is committed.
- **Bug found and fixed (2026-11-11):**
  - The first version used a substring check, so `arXiv:2410.00037v1` matched a `v10` stamp, and a v10 PDF would have passed as Moshi v1.
  - The first test ("v6 is absent from the v7 PDF") could never fail, so it proved nothing. Archi's explanation of that test prompted the second look that found the bug.
  - Now: exact match via regex (`v1(?!\d)`), and the check itself is tested against made-up stamps (v6/v8/v70 for Attention, v10/v11 for Moshi, v1/v20 for H-Net, and a different paper's id).
- **Observed:** Attention 15 pages, Moshi **66** pages, H-Net 39 pages. Moshi and H-Net are mostly appendix and references. This matters for chunking in M1.

## D7: Stack trims
**Status:** Accepted · **Who:** assistant proposed, Archi accepted

- **No FAISS:** a few thousand chunks fit an exact NumPy dot product.
- **FastAPI only for the stand-in.**
- **Custom open-loop load generator instead of Locust.** Locust's default user model waits for each reply, which hides overload (coordinated omission).
- **Cross-encoder only as one Table 3 setting.**
- Dependencies are added per milestone, only when needed.

## C1–C4: Ingestion and chunking (M1)
**Status:** Accepted (2026-11-12) · **Who:** assistant proposed from the PDF inspection; Archi accepted with refinements (keep the bibliography available separately; exclude all of Moshi Appendix F; boundaries must preserve meaning, not just hit a token count)

- **C1: References are not searchable.** Keyword-dense, answer nothing (Moshi: 11 pages). Kept available via `ingest.references_text()`. Acknowledgements are excluded too.
- **C2: Appendices are searchable and labelled `appendix`.** Moshi Appendix F (synthetic example dialogues, F.1–F.3) is excluded: its statements are made-up dialogue, not the paper's claims.
- **C3: Section-aware packing.** Whole paragraphs, never across a section, overlap only within a section, page range on every chunk. Archi's reason: a chunk that mixes the end of an experiment section with the start of a limitations section can be retrieved for keywords from both, and the model may merge their claims and cite the wrong section. *Chunk boundaries should preserve meaning, not just satisfy a token limit.*
  - Indexed text has the paper title and section prefixed, which separates "our model" in one paper from another.
  - Oversized tables are split by row, **repeating the header** on every piece.
- **C4: Token counts use tiktoken `o200k_base`** (an estimate of gpt-oss's tokenizer; to be checked against Groq's `prompt_tokens`). Paper text is encoded as plain text even when it contains special-token strings: Moshi p.30 literally contains `<|endoftext|>`.

**Extraction problems found by reading the output, each pinned by a test:**
- Moshi headings had no spaces ("AdditionalablationonMimicodec"); some Attention body lines too ("Thecodeweusedtotrain…"). Fixed by rebuilding text from glyph gaps.
- False headings from bold lead-ins and capital pairs ("XL Scale.", "DC is composed…", "1. Initial processing:"). Fixed: stricter heading pattern; lead-ins now open the next paragraph.
- Attention's appendix initially fell inside References. Fixed.
- First debris filter deleted table numbers (a cell "28.4" has few letters). Fixed by extracting tables separately.
- A figure was detected as a table (H-Net p.7). Fixed by a single-glyph ratio check.
- Captions were separated from their tables. Fixed: caption prefixed to the table text.

**Known limitations (not fixed; candidates for "how this library misleads a naive retriever"):**
1. **Table rows are merged and misaligned.** Attention Table 2: four models share three EN-DE BLEU values, because Deep-Att has none. Pairing them in order gives every model the wrong score. Table 3 rows (A) squash four variants together.
2. **Tables are labelled by where they sit on the page, not where they're discussed.** Attention Table 2 is filed under "5.4 Regularization", but discussed in 6.1. The page citation is right; the section label is not.
3. **Superscripts are flattened.** "2.3 · 10^19 FLOPs" extracts as "2.3 · 1019". Maths in general is scrambled ("W Q / i").
4. Small accent artefacts ("D´efossez").
5. **Moshi's small-caps subsection headings aren't detected** (found while checking Q02). Everything under 3.4.x is labelled "3.4 Generative audio modeling", because the heading rule needs bold. No text is lost, and the page citation is right, but the section label is less precise. Not fixed before the benchmark freeze, because a fix would change chunk boundaries.
6. **Display equations are dropped as figure-like text** (found by the checker on Q09). H-Net Equation (4) holds the routing threshold `0.5`, so the system can't cite it. Kept in the benchmark on purpose, to measure this gap.

## R1–R5: Retrieval (M2)
**Status:** Accepted (2026-11-12) · **Who:** assistant proposed; Archi approved and added three requirements: modular stages, per-stage latency, refusal groups evaluated separately

- **R1:** BM25 over `search_text` (title + section + chunk). The tokenizer keeps `h-net`, `28.4`, `3.2.1` whole and also splits compounds.
- **R2:** Dense retrieval with `BAAI/bge-small-en-v1.5` (CPU, 384-dim), with the query instruction bge recommends. Embeddings are cached per exact chunk text.
- **R3:** Reciprocal Rank Fusion, k=60.
- **R4:** Optional rerank with `cross-encoder/ms-marco-MiniLM-L-6-v2` over the top 20 fused candidates.
- **R5:** Page-level recall@k, full recall (all evidence items covered) and MRR for answerable questions. Evidence signals (best rerank, cosine, BM25) are reported per group: answerable / near-miss / off-topic / false-premise, **never pooled**.
- **The sufficiency threshold must use rerank, cosine or BM25 signals, not the RRF score.** RRF depends only on rank positions, so the top hit always gets about the same score whether or not the question is answerable.
- **Per-stage timings** (`bm25`, `embed_query`, `dense`, `fusion`, `rerank`, `total`) are recorded for every search. LLM timing is recorded by the pipeline (M4) in the same per-request row.
- **Finding (measured 2026-11-12):** bge-small reads at most 512 word pieces. **t256: 0 of 463 chunks truncated (longest 349). t512: 56 of 242 (23.1%) truncated (longest 625).** Our 512 o200k tokens are more than 512 bge word pieces, so the end of ~1 in 4 large chunks is never embedded. The cross-encoder has the same 512 limit.
- **Decision (Archi): replace t512 with t384, and guarantee no truncation instead of measuring it once.**
  - The reranker reads question + passage in one 512 window, so a measurement with a short test question proves nothing for long ones.
  - A **64 word-piece question budget** leaves a passage limit of **445** (512 − 64 − 3 special tokens), checked under the stricter of the two tokenizers. The chunker enforces it, and `build_chunks.py` refuses to write an index that breaks it.
  - Questions over the budget **skip rerank and record `rerank_skipped_long_query`**, rather than being cut silently.
  - **Rebuilt indexes: t256 = 454 chunks (max 331 word pieces); t384 = 324 chunks (max 444).**
- **Bugs this requirement exposed (assistant's code, caught by Archi's "no truncation" requirement and the tests written for it):**
  1. An over-long table row was cut and the rest dropped.
  2. The last-resort split cut at tokenizer boundaries and could break "±" in half.
  3. Splitting a row at spaces separated a value from its error bar.
  4. Splitting a giant cell dropped its closing delimiter.
  - **Now:** splits happen only between cells, then sentences, then whole words, and nothing is dropped. Tests check that every word of searchable text is indexed, and that every section and document ends with its real final words.

## R6: First retrieval evaluation on the frozen benchmark (measured)
**Status:** Measured 2026-11-12; the choice of settings is Archi's · Run: `results/retrieval/retrieval-eval-20261112T110234Z.csv` (benchmark commit 932b143, 3 repeats, CPU)

| Setting (k=4) | recall@k | full | MRR | p50 ms |
|---|---|---|---|---|
| t256 bm25 | 83.3% | 75.0% | 0.569 | 1.1 |
| t256 dense | 91.7% | 83.3% | 0.833 | 19.6 |
| t256 hybrid | 100% | 91.7% | 0.694 | 22.1 |
| t256 hybrid+rerank | 91.7% | 83.3% | 0.688 | 634.6 |
| t384 bm25 | 91.7% | 91.7% | 0.708 | 0.8 |
| t384 dense | 100% | 91.7% | 0.840 | 16.2 |
| t384 hybrid | 91.7% | 91.7% | 0.833 | 18.9 |
| t384 hybrid+rerank | 83.3% | 83.3% | 0.653 | 784.2 |

- **n = 12 answerable, so one question = 8.3 points.** Most differences are one or two questions. The misses are concentrated in **Q02** (Moshi multi-stream) and **Q12** (two-paper comparison).
- **The reranker never helped:** recall equal or lower in both chunk sizes, at **+600–770 ms** of CPU time per question.
- **No retrieval score separates near-miss from answerable.** With rerank, near-miss best scores are 0.9–3.2, while answerable ones go down to 0.63–0.78 (Q12) and 3.2 (Q08, Q09). Cosine overlaps too (median 0.78 vs 0.81). Only the off-topic question is clearly separable (rerank ≈ −9). **Consequence:** refusing near-misses must be done by the answer-time grounding check, not by a retrieval threshold. A retrieval threshold can only catch clearly off-topic questions.
- **Q12 (two papers): the top 4 are all H-Net in every t384 setting.** One query with k=4 can't serve a comparison. Candidate fix: retrieve per paper, or split the question into one query per paper (a pipeline branch).
- **False premise (Q18):** the contradicting passage was retrieved in 8/8 settings (n=1).
- **Q09 ranks first but its passage lacks `0.5`** (equation dropped), so recall overstates it. The answer grade will show the gap.

## R7: Retrieval settings for Table 3 and the pipeline default
**Status:** Accepted (2026-11-12) · **Who:** Archi chose, from R6 and the assistant's recommendation

- **Table 3 settings:** t384 with bm25, dense and hybrid, all **without the reranker**. Same chunks for all three, so only the search method varies.
- **Pipeline and load-test default: t384 hybrid (k=4).**
  - BM25 catches exact tokens (table numbers, values, model names) and dense catches paraphrase.
  - Cost is ~19 ms p50 against ~1 s of LLM time.
  - Dense was marginally better on our 12 questions (one question's difference), which is too small to decide on. Table 3's answer grades will confirm or overturn this.
- **Reranker dropped.** Measured in R6: no recall gain in either chunk size, +600–770 ms per question on CPU. It uses no Groq quota (it runs locally); the cost is latency, which breaks the response budget.
- **Why not BM25 as the default:** it saves ~15 ms (~1.5% of a request), ranks the right page lower (MRR 0.708 vs 0.833), and our questions reuse the papers' wording, which flatters exact-word matching. Paraphrased user questions would hurt it.
- **Carried into M4:** refusals for near-miss questions must come from the answer-time grounding check (R6: no retrieval score separates them). A two-paper question needs per-paper retrieval or a split query (Q12).

## P1–P6: The answer pipeline (M4)
**Status:** Accepted (2026-11-12) · **Who:** assistant proposed; Archi tightened the support rule, added the separate model timestamps, and required consistent grading plus measured semantic failures

- **P1: five steps, one model call per answer (option C).**
  1. **Understand** (code): which papers are named, and is it a comparison?
  2. **Retrieve**: the `search_papers` tool (t384 hybrid, k=4), with a timeout.
  3. **Decide** (the branch): a comparison runs one search per paper. A tool timeout gets one retry, then a labelled "couldn't search" reply. Never answer without passages.
  4. **Draft** (one Groq call): JSON with `status` ∈ {answered, not_in_papers, premise_false} and claims, each with a chunk ID and an exact quote.
  5. **Check** (code): cited chunks were retrieved, and quotes appear word for word. One redraft on failure (the loop), then refuse.
  - **Why C:** reserving 2,000 prompt + 512 output = 2,512 tokens per call gives 8,000 / 2,512 ≈ 3.18 calls/min under the TPM limit. Options A and B (2–3 calls per answer) give about 1–1.6 answers/min. Every redraft costs a second reservation, so the redraft rate is measured.
- **Support rule (Archi):** every factual claim must be **directly stated in its quote**. That includes numbers, capabilities and comparisons; inference doesn't count. If the passages don't support an answer → `not_in_papers`. If a passage contradicts the question's assumption → `premise_false`, with the contradicting quote.
  - **Comparisons:** each paper's side is quoted separately and set side by side. No added judgment that no quote states.
  - **Partly answerable:** answer the supported part and say plainly which part the papers don't cover.
- **What the check proves, and what it doesn't (Archi):** the exact-quote check proves the chunk and the quote are genuine. **It does not prove the claim follows from the quote.** Semantic support is measured instead, by hand-labelling each claim in the 18-question run (*supported by its quote: yes/no*) → the unsupported-claim rate, reported with its n.
- **P2:** no retrieval-score threshold in v1 (R6: none separates near-miss from answerable). Scores are still logged.
- **P3:** gpt-oss-20b, `reasoning_effort: low`, `max_tokens: 512`, temperature 0. JSON mode is verified with one real call before anything relies on it. A 20b vs 120b comparison runs on the 18 questions.
- **P4: three timestamps (Archi),** so latency splits into waiting, generation and checking:
  - `model_first_token_ms`: the model's first token (queue + prompt processing);
  - `model_last_token_ms`: the model finishes (generation);
  - `first_token_ms`: the checked answer starts sending to the user (check, plus any redraft).
  - The `model_*` columns follow the required columns in results.csv (closes D-open-2).
- **P5: one deterministic grader** in code and under version control, used unchanged for every setting, model and run. No model judges the answers. A rule change means re-grading every saved answer.
  - **Answerable question:** `correct` if every key fact is present (numbers and short words as whole words) and at least one citation is a gold page. Otherwise `wrong`, or `refused_wrongly` if it refused.
  - **Refusal questions:** `refused_correctly` if refused, else `wrong`. For a false premise, it's correct only if the status is `premise_false`, or a refusal that cites the contradicting page.
  - Archi reads all 18 answers once. Any disagreement with the grader is a logged grader fix.
- **P6:** the pipeline talks to a `ModelClient` interface (Groq now, the gateway in M5, the stand-in in M6), and is async throughout.

## M4 run 1: first end-to-end run (measured 2026-11-12)
Raw: `results/answers/answers-gpt-oss-20b-t384-o32-hybrid-20261112T112623Z.jsonl` (gpt-oss-20b, t384 hybrid k=4, grader g1). Kept as-is, bugs included.
(A two-question smoke-test log from before the warm-up fix was deleted by the assistant; it only showed the cold-start failure described below.)

- **Grades:** 4 correct, 6 wrong, 3 refused_wrongly, 5 refused_correctly. All 4 near-miss and the off-topic question were refused correctly. The false premise was refused, but not challenged.
- **Tokens:** ~1,500–2,000 prompt tokens per call (the 2,000 estimate holds); 71–302 completion tokens.
- **Bugs found (assistant's code), fixed after this run:**
  1. **The quote check rejected genuine quotes:** gpt-oss writes hyphens as U+2011, and maths spacing differs from the PDF ("𝑏𝑡 = 1" vs "𝑏𝑡= 1"). This caused 2 of the 3 refused_wrongly (Q02, Q03). Fix: normalise those hyphens and ignore whitespace. Replaying the saved drafts offline, both pass on the first draft. Tests still reject changed or reordered words.
  2. **Right quote, wrong chunk ID** (Q10). The model repeated it when asked to redraft. Fix: if the quote is in exactly one other retrieved chunk, re-point the citation there (`citations_fixed`). That's cheaper than a redraft, and the citation becomes true.
  3. **An empty stream with no finish reason counted as success** (Q03's redraft). Now it's an error.
  4. **Cold start:** in the smoke test, the first search loaded the embedding model inside the 5 s tool timeout and failed twice. Fix: `Retriever.warm_up()` at startup.
- **Real model behaviour, kept as findings:**
  - **Q12 shows a semantic failure the quote check can't catch.** The H-Net claim "learns to segment … by predicting token boundaries" cites a genuine quote about distillation that doesn't say that. The reply also contains sentences that aren't in any claim. Exactly what Archi predicted: verbatim ≠ supported.
  - **Q18:** "the papers do not state that it uses convolutional layers" (`not_in_papers`) instead of `premise_false`, although the retrieved p.6 says "contains no recurrence and no convolution".
  - **Q09:** answered without 0.5 or 1.0. 0.5 is absent from the index (equation dropped); 1.0 was present, but omitted.
  - **Q01 model_first_token 7,719 ms**, with Groq's own queue_time at 0.26 s. That's ~7.4 s before Groq's queue, on the first call of the run, and not yet explained.
- **Grading issues that need Archi's decision (benchmark is frozen, so these are logged B1 edits if accepted):**
  - **Q01, Q07: correct answers graded wrong because of the key-fact wording.** Q07 said "sinusoidal" (key facts `sine`, `cosine`). Q01 used p.15's wording ("linguistic quality", "prefix"), but its key facts come from p.3 ("factuality", "before audio tokens").
  - **Q04: correct answer (16 heads, 6 layers), cited pp.13–14.** Section 3.4 prose states the same numbers, but the gold page lists only the table (p.8). The question says "according to the hyperparameters table".

## M4 run 2: after the bug fixes (measured 2026-11-12)
Raw: `results/answers/answers-gpt-oss-20b-t384-o32-hybrid-20261112T115427Z.jsonl` (grader g2). Run 1 re-graded with g2: 7 correct, 3 wrong, 3 refused_wrongly, 5 refused_correctly.

- **Grades:** 7 correct, 6 wrong, 0 refused_wrongly, 5 refused_correctly.
  - Answerable: 7/12 correct (58.3%), 0 wrongly refused.
  - Refusal group: 5/6 (83.3%); Q18 was refused, not challenged.
- **The fixes worked:** all 18 answered with one model call; 0 redrafts; 1 citation re-pointed (Q10).
- **Timing (n=18):** model first token 268–1,648 ms; first_token (checked reply out) 414–1,718 ms. The check itself adds 1–14 ms.
- **The remaining wrong answers:**
  - **Q02, Q10, Q12: the reply contains sentences that are in no claim**, or claims whose quote doesn't state them. Q02's "outputs silence for its own stream" is not in its quote. Q12's H-Net side cites a distillation passage. Q10's selection rule is in the reply but not claimed. The structure allows free text in `answer` beside the claims, and the model uses it.
  - **Q12:** each per-paper search still uses the whole two-paper question. The H-Net search returned p.4 and p.39, not the routing module (p.6).
  - **Q03:** wording ("split residual vector quantiser") and content (never says "first level").
  - **Q10's key facts ask for more than the question:** `mean pooling` and `cross-attention` aren't asked for by the question.
  - **Q09:** 0.5 missing from the index; 1.0 omitted. **Q18:** `not_in_papers` instead of `premise_false`.
- **Hand review:** `results/review/review-answers-gpt-oss-20b-t384-o32-hybrid-20261112T115427Z.md`. Archi labels each claim supported/unsupported (P1) and agrees or disagrees with each grade (P5).

## P7: The reply is built only from checked claims
**Status:** Accepted (2026-11-12) · **Who:** assistant proposed after run 2; Archi approved

- The free-text `answer` field is gone. The user sees the claim sentences in order, each followed by the citation for its chunk (built by code), plus a labelled "The papers don't cover: …" when part of the question is unsupported. Refusals use fixed wording.
- **Why:** in run 2, Q02, Q10 and Q12 had reply sentences that no claim backed. Now no sentence reaches the user without a verified quote beside it.
- **What it doesn't fix:** a claim can still overstate its quote. P7 removes unclaimed text, not bad claims. The hand review still measures semantic support.
- **Cost:** the reply reads as cited points rather than a flowing paragraph. Model calls are unchanged.
- **Amendment after run 3 (Archi: "keep P7, ask for coverage"):** run 3 showed the model writing fewer claims and dropping parts of the answer. The prompt now says: cover every supported part of the question, one claim per distinct point. It's a general rule, written because of how the reply is built, not for particular questions.

## M4 run 3: replies built from claims only (P7) (measured 2026-11-12)
Raw: `results/answers/answers-gpt-oss-20b-t384-o32-hybrid-20261112T123207Z.jsonl`. Q03 alone was re-run in `…123813Z.jsonl` to diagnose it.

- **Grades: 4 correct (was 7), 8 wrong, 1 no answer (Q03), 5 refused_correctly.**
- **P7 made answers shorter, not only cleaner.** Claims per answer fell (run 2: mostly 2–3; run 3: mostly 1).
  - Q07 dropped "sinusoidal" and "relative positions"; Q05 dropped "sequential operations". Q02 is now shorter, but every sentence is quoted.
  - Q06 is the same answer, but now "average" ≠ key fact "averaging". In run 2 the grader also read claim texts that said "averaging".
- **One run per setting, and the model is not deterministic at temperature 0** (Q12 needed a redraft in run 3 but not in run 2). Differences of 1–3 questions between runs are partly noise.
- **Real-service finding: Groq's JSON mode can fail server-side.** A 200 stream carries `{"code": "json_validate_failed", "failed_generation": ""}` after ~700 ms of generation, and no usage is reported. It's repeatable on Q03, whose passages are full of maths symbols. Before this, the client recorded it as "stream ended without a finish_reason". **Handling:** capture in-stream errors; on `json_validate_failed`, redraft once with JSON mode off (our own parser and check still reject non-JSON).
- **Budget:** answer runs today used **115,463 measured tokens**. The failed Q03 calls report no usage, so the real total is higher. Against the documented (unverified) 200K tokens/day, about 2 more full runs fit today.
- **Grader caution:** adding alternative wordings after seeing the answers (e.g. "average" for Q06) would tune the grader to the outputs. The hand review measures grader error instead.

## B1: Benchmark protocol
**Status:** Accepted (2026-11-12) · **Who:** Archi set the composition and the no-invention rule; the assistant added the freeze rule

- **18 questions minimum** (brief requires 15): 12 answerable + 6 to be refused (4 on-topic near misses, plus 2 from off-topic / false premise).
- Written by Archi. Every gold page and key fact is checked against the extracted text of the pinned PDF versions, by viewer page number (`scripts/check_benchmark.py`). Nothing is invented.
- **Written and frozen (git commit) before any retrieval results are seen.** Later edits are allowed only for broken questions (wrong page, ambiguous), each logged with its reason; never because the retriever failed on it.
- **Final split (frozen 2026-11-12):** 12 answerable (8 body_fact, 1 number_table, 1 appendix, 2 multi_part) + 4 unanswerable_near_miss + 1 unanswerable_off_topic + 1 false_premise.
- Q01–Q03 evidence widened before the freeze to include the detailed sections, not just the intro summary. Archi checked them in the PDF: Moshi 3.4.4 (pp. 15–16), 3.4.3 (pp. 14–15), 3.3 (pp. 9–11).
- **B1 edit 1 (2026-11-12, after M4 run 1; Archi: "allow alternatives").** Reason: the grader rejected correct answers because of wording, not because the retriever or model failed.
  - Key facts may list accepted wordings (any one counts; at least one must be on a gold page). Grader g1 → g2. Every saved run is re-graded with g2.
  - Q01: `factuality` | `linguistic quality`; `before audio tokens` | `prefix`. The p.3 and pp.15–16 gold pages word it differently.
  - Q07: `sine` and `cosine` merged into one fact, `sine` | `sinusoid` | `sinusoidal`. Q12 gets the same alternatives for `sine`.
  - Q04: pp.13–14 added. Section 3.4 prose states the same 16 heads / 6 layers.
- **B1 edit 2 (2026-11-12, after the hand review; Archi: "fix it"):** Q10's key facts required `mean pooling` and `cross-attention`, which the question never asks for. Now: `direct selection` | `boundary-marked` (the strategy) and `retained` | `kept` | `keeps` | `discarded` (the rule). Both are on p.6. Made before the Table 3 runs, so all three settings are graded on the same question. Run 4's Q10 stays `wrong` (its answer never states the rule), which matches Archi's hand verdict.
- **Grader rules this benchmark needs:** numbers match as whole numbers (Q04 `6` ≠ `16`); short key facts match as whole words (Q11 `key`); the false-premise question (Q18) is graded on whether the answer challenges the premise, not on key-fact matching alone.

## M4 final: pipeline frozen at run 4's version (2026-11-12)
Raw: `results/answers/answers-gpt-oss-20b-t384-o32-hybrid-20261112T124111Z.jsonl` (P7 + coverage rule).

- **Run 4:** 4 correct, 9 wrong, 5 refused_correctly. The coverage rule did not change behaviour: Q07 and Q10 are still one claim. Q04 is correct but wrote "six" and "sixteen", which the grader misses.
- **Frozen anyway, by deadline and by principle.** Every sentence a user sees has a verified quote behind it, which follows the brief's "never send a wrong or embarrassing answer". The measured cost is completeness: run 2's free-text version scored 7 by the grader, partly *because* of unsupported sentences. The report shows all three runs. The hand review measures how many "wrong" grades are correct answers the grader missed.
- **Schedule correction (Archi, 18:15 IST on 12 Nov):** submission is due **13 Nov 13:40 IST**, not in 2 days. Cut: the 20b vs 120b comparison, the stand-in as a separate server process, and gateway extras.

## M5–M7: gateway, stand-in, load generator (built 2026-11-12 evening)
- **Gateway** (`src/relay/gateway.py`): a ModelClient wrapping the provider, as designed in D0/D5.
  - Continuous-refill buckets for RPM, TPM (at 90% of the limit) and RPD. Each call reserves prompt + max_tokens; the unused part is refunded.
  - Immediate shedding when the estimated wait exceeds the 25 s policy deadline, or the queue (30) is full.
  - Bounded FIFO, with the deadline re-checked when a request leaves the queue.
  - On a 429: retry within 2 per request and a 20% global budget. A retry-after longer than the deadline is treated as the daily limit, and the gateway stops calling.
  - It syncs with `x-ratelimit-remaining-*`. When the daily budget is gone, the reply is a **labelled passages-only answer** with no model call.
- **Concurrency probe (Table 1):** 10 calls at once all succeeded in 626–787 ms (`concurrency-20261112T124902Z.jsonl`), so no in-flight limit was observed at 10. The headers confirm each call reserves prompt + max_tokens (78 + 64 = 142) when admitted.
- **Stand-in** (`src/relay/standin.py`): in-process (decided under deadline), calibrated by `scripts/calibrate_standin.py` from **70 real calls**. TTFT p50 655 ms, generation p50 186 ms, 168 completion tokens, 429 in ~65 ms, 1.25% JSON rejections (`results/standin_calibration.json`).
  - **Assumed, not measured:** the slowdown under load (+15% first-token time per call in flight above 4), and the 1% error rate.
  - "Per-minute limit halved" halves **both** RPM and TPM without telling the gateway. TPM is the binding limit (~3 answers/min); halving RPM alone would change nothing.
- **Load generator** (`scripts/run_load.py`): open loop. Poisson arrivals plus bursts. Times are measured from the scheduled start. Users give up after 30 s.
- **Bug found by the first daily_exhausted run (assistant's code):** the gateway's daily counter, synced from headers, reached 0. Requests then waited in the queue for an ~86 s refill and timed out (9 of 17), instead of getting the labelled reply. Fix: if the daily counter can't refill within the deadline, reply at once. The flawed run is kept in `results/load/superseded/`.
- **Second bug, found in the limits-halved table (assistant's code):** a request that was retried after a 429 and *then* shed lost its retry count. The table showed 0.00 retries/request while the gateway had retried twice. Fixed (every early gateway reply carries its retry count) and re-run; the table now shows 0.10. The flawed run is in `results/load/superseded/retry-count-bug/`.
- **Peak queue length is 1 in every 10 s run, by design.** One answer needs ~2,500 tokens and tokens/min refill at ~120/s, so each answer occupies ~21 s of budget. With a 10 s deadline, a second request can never be admitted behind the first.
- **Seen in the stand-in runs:**
  - Under overload, admitted requests wait up to the deadline (p50 17 s). **The policy deadline is what sets "fast" for admitted users** (D-open-4).
  - The daily budget refills gradually: one full answer came back at +135 s in the daily_exhausted run.

## Hand review of the final pipeline (Archi, 2026-11-12)
File: `results/review/hand-review-run4-archi.md` (run 4, the frozen pipeline).
- **Unsupported-claim rate: 50.0% (10 of 20 claims).** Half the claims say more than their verbatim quote. This is exactly the gap Archi predicted in P1: the check proves the quote is real, not that it supports the claim. Typical overreach adds a mechanism or detail from nearby text: Q01 "multi-stream", Q11 "key **and value**", Q08 "restores the original length".
- **Grader agrees with Archi on 13/18 (72.2%).** 2 false negatives (Q04 number words, Q06 word form) and 3 false positives (Q01, Q08, Q11: key facts present but a claim unsupported). No grader change after seeing the answers (that would tune the grader to the outputs). The report gives both numbers.
- **Correct:** grader 4/18 (22.2%), Archi 3/18 (16.7%). **Refusals:** 5/6 by both. All near-miss and off-topic questions were refused. The false premise was refused generically instead of being challenged.
- **What this says about the design:** the next step would be a support check per claim. That's either a second model call (option B in P1, which halves throughput under the TPM limit) or a stricter local check, e.g. requiring each claim's key terms to appear in its quote. Not built (deadline); named in the report as the main weakness.

## Local support check, measured against Archi's labels (2026-11-13)
- **Rule** (`src/relay/support.py`, no model call): every number in a claim must appear in its quote (number words count), and ≥ 60% of the claim's content words (5-letter stems) must appear in the quote. The 0.6 threshold was set in code before scoring.
- **Scored on Archi's 20 hand-labelled claims** (`scripts/eval_support_check.py`; labels read from `hand-review-run4-archi.md`): **caught 9 of 10 unsupported claims; wrongly dropped 3 of 10 supported claims.**
  - Missed: Q03 c1 (names "SeaNet autoencoder"; the quote only describes the encoder; 68% overlap).
  - Wrongly dropped: Q05 ("three criteria" vs "One… Another… The third"), Q07 (a short correct paraphrase, 50%), Q08 c2 ("progressively compressed", a fair paraphrase in other words).
- **Sweep:** 0.5 → 7/10 caught, 2/10 dropped; 0.7 → 10/10 caught, 5/10 dropped. No free setting.
- **Caveats:** 20 claims from one run, and the rule was designed with this run in view, so these numbers are optimistic for new questions.
- **Not deployed** in the frozen pipeline. Deploying it would change the system behind every completed run, so it would need a fresh hybrid run plus the Table 3 runs (~36K more tokens). It's reported as the measured next step.

## Retry experiment (report section 6) (measured 2026-11-12)
- **Hypothesis (assistant's): blind retries make overload worse. Rejected on this provider.** Same overload arrivals (62 requests, stand-in). With `NaiveRetryClient` (no gateway; every 429 retried after 1 s, up to 5 times): 21 answered vs 19 with the gateway, first-token p50 / p95 2,656 / 6,372 ms vs 6,531 / 10,762 ms. It made 297 provider calls (234 retries) vs ~62.
- **Why:** a 429 is cheap. Stand-in: 65 ms, no budget used. **Real Groq: a 429 does not consume daily requests.** In the probe headers, remaining requests stayed at 970 through the RPM 429 and fell to 969 on the next success; in the TPM probe, 967 → 966 (one episode each, medium confidence). Our gateway is conservative: 90% TPM headroom and a characters ÷ 4 estimate that overstates the prompt. That cost ~2 answers in 5 minutes of overload.
- **The case where retrying made things worse is the model-level redraft** (real Groq, run 1). Q02, Q03 and Q10 each paid a second full call: request totals of 4,835 / 2,189 / 4,019 tokens, ~2,500 reserved per call. All three still ended unverified, and in Q10 the model returned the **identical** draft. Under an 8K tokens/min limit, one wasted reservation is ~21 s of budget, about one other person's answer. Of 5 redrafts across runs 1–4, 2 helped (run 3 Q12, run 4 Q08). Run 1's failures were partly caused by the quote-check bug (U+2011 hyphens).
- **Lesson:** retry what is temporary (a 429 says when); don't blindly retry what is deterministic (the same prompt gives the same failure). A redraft should change something, e.g. tell the model exactly which quote failed and where it actually appears. That is what `fix_citations` now does without any call.

## D8: What "fast" means: a 10 s policy deadline
**Status:** Accepted (2026-11-12) · **Who:** Archi decided; the assistant laid out the trade-off and agreed

- **Definition:** a reply starts within ~1 s when the system isn't busy (measured p50 ~0.9 s). **No admitted request waits more than 10 s in the gateway queue**, so the reply starts within ~12 s including the model call. Anyone we can't serve in time is told **immediately** ("busy, try again in about N s").
- **Archi's reasoning:** with 25 s we admit more people, but they can wait up to 25 s (measured p50 17 s under overload). With 10 s fewer are admitted and more get "busy", but nobody admitted waits more than 10 s. Follows D4: fast and honest beats slow and silent.
- **Cost:** a lower success % under burst and overload in Table 2b. That's the intended trade-off, not a regression. Fewer 429 retries, too: a retry only happens if the deadline still allows it.
- The deadline is set below the simulated user patience (30 s), so people should be told "busy" before they would give up.
- The stand-in runs at 25 s are kept in `results/load/superseded/deadline25/` for comparison.
- **Measured, 25 s vs 10 s, same arrivals (same seed), stand-in:**

  | Scenario | Answered | Answers per 1K tokens | First-token p50 / p95 (ms) |
  |---|---|---|---|
  | overload (62 sent) | 18 → 19 | 0.472 → 0.493 | 16,984 / 24,076 → 6,531 / 10,762 |
  | steady (17) | 16 → 15 | 0.475 → 0.477 | 1,272 / 18,957 → 1,577 / 5,076 |
  | burst (12) | 4 → 3 | 0.541 → 0.528 | 1,201 / 6,822 → 1,187 / 1,981 |
  | limits halved (20) | 16 → 14 | 0.481 → 0.483 | 2,008 / 24,716 → 1,577 / 6,922 |
  | daily exhausted (17) | 6 → 6 | same | same |

  **The prediction held.** Throughput is capped by the token limit (~3 answers/min), so under sustained overload the 10 s deadline answered as many people at well under half the wait, and nobody gave up (1 did at 25 s). The real cost is 1–2 fewer answers in burst, steady and limits-halved, where those people got an instant "busy" instead of a long wait. Answers per 1K tokens is unchanged.

## Resolved
- **D-open-1 → stand-in rows have an empty `answer_grade`,** reported as "not measured". The stand-in's text is synthetic.
- **D-open-2 → extra columns after the required ones:** `model_first_token_ms`, `model_last_token_ms`, `queue_ms`, `retry_sleep_ms`, `final_status`, `degraded`, `question_id`, and so on.
- **D-open-3 → no fallback to a second model (Archi).** "We need to test the work with the limits itself." When the daily budget is gone, the reply is a labelled passages-only answer (no model call).
- **No frontend (Archi asked; assistant recommended against).** The brief asks for code, raw results and the report. A command-line `scripts/ask.py` serves the live demo.

## Open
- **D-open-4:** the numeric meaning of "fast" at low load. Set after the M3 calibration.
