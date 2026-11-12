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

## B1: Benchmark protocol
**Status:** Accepted (2026-11-12) · **Who:** Archi set the composition and the no-invention rule; the assistant added the freeze rule

- **18 questions minimum** (brief requires 15): 12 answerable + 6 to be refused (4 on-topic near misses, plus 2 from off-topic / false premise).
- Written by Archi. Every gold page and key fact is checked against the extracted text of the pinned PDF versions, by viewer page number (`scripts/check_benchmark.py`). Nothing is invented.
- **Written and frozen (git commit) before any retrieval results are seen.** Later edits are allowed only for broken questions (wrong page, ambiguous), each logged with its reason; never because the retriever failed on it.
- **Final split (frozen 2026-11-12):** 12 answerable (8 body_fact, 1 number_table, 1 appendix, 2 multi_part) + 4 unanswerable_near_miss + 1 unanswerable_off_topic + 1 false_premise.
- Q01–Q03 evidence widened before the freeze to include the detailed sections, not just the intro summary. Archi checked them in the PDF: Moshi 3.4.4 (pp. 15–16), 3.4.3 (pp. 14–15), 3.3 (pp. 9–11).
- **Grader rules this benchmark needs:** numbers match as whole numbers (Q04 `6` ≠ `16`); short key facts match as whole words (Q11 `key`); the false-premise question (Q18) is graded on whether the answer challenges the premise, not on key-fact matching alone.

## Open
- **D-open-1:** what goes in `answer_grade` for stand-in rows? (Proposal: empty, reported as "not measured".)
- **D-open-2:** extra CSV columns after the required ones (queue_ms, retry_sleep_ms, provider_ttft_ms, degraded_level, …).
- **D-open-3:** fall back to a *second* Groq model when the first one's daily quota is gone? Is that legitimate degradation, or a "trick to get around limits"? Decide before M8.
- **D-open-4:** the numeric meaning of "fast" at low load. Set after the M3 calibration.
