# The Relay

A reliability-aware RAG assistant that answers engineers' questions **only** from three pinned arXiv
papers. Every answer cites its source page, and every sentence the user sees carries a verbatim quote
that code has checked. When the papers don't say, it refuses. All model calls go through a gateway
that works **inside** Groq's free-tier limits. A stand-in model service, calibrated from real Groq
measurements, covers the loads the free tier can't take.

Papers: *Attention Is All You Need* (1706.03762**v7**), *Moshi* (2410.00037**v1**),
*Dynamic Chunking / H-Net* (2507.07955**v2**). Each version's arXiv stamp is checked.

## How a question is answered
1. **Understand** (code): which papers are named; is it a two-paper comparison?
2. **Retrieve** (the `search_papers` tool): 384-token section-aware chunks, BM25 + bge-small dense
   search fused with RRF, top 4. It has a timeout and one retry. A comparison searches each paper
   separately (the branch).
3. **Gateway**: token buckets for requests/min, tokens/min and requests/day (continuous refill, as
   measured), a bounded FIFO queue and a **10 s policy deadline**: anyone who can't start in time is
   told "busy" immediately. Retries on 429 are limited. When the daily budget is gone, the reply is a
   labelled passages-only answer, with no fallback model.
4. **Draft** (one call to `openai/gpt-oss-20b`): JSON claims, each with a chunk ID and an exact quote.
5. **Check** (code): every quote must appear word for word in a retrieved chunk. One redraft on
   failure, then refuse. The reply is built **only** from checked claims, and citations come from
   chunk metadata. Nothing is sent before the check passes.

The check proves that each quote is genuine. It does **not** prove that the claim follows from the
quote. That is measured by hand on the benchmark.

## Setup
```bash
uv sync
cp .env.example .env                                  # add your Groq key (.env is gitignored)
uv run python scripts/fetch_papers.py                 # downloads + verifies the pinned PDFs
uv run python scripts/build_chunks.py --target 384    # builds index/ (also --target 256)
uv run pytest -q
```

## Try it
```bash
uv run python scripts/ask.py "How many attention heads does the Moshi Depth Transformer use?"
uv run python scripts/ask.py --standin "..."          # no Groq quota (synthetic reply)
```

## Reproduce the results
| What | Command |
|---|---|
| Groq limits and latency (Table 1) | `scripts/probe_groq.py inspect / latency / rpm / tpm / concurrency` |
| Retrieval-only evaluation | `scripts/eval_retrieval.py --repeat 3` |
| Benchmark through the pipeline (Table 3) | `scripts/run_benchmark.py --mode hybrid / bm25 / dense` |
| Stand-in calibration | `scripts/calibrate_standin.py` |
| Load scenarios (Tables 2a/2b) | `scripts/run_load.py <scenario> --source real or standin ...` (examples in the file) |
| Raw file | `scripts/build_results_csv.py --table3 <benchmark runs>` → `results/results.csv` |
| Tables, computed only from `results.csv` | `scripts/analyze_results.py --md docs/TABLES.md` |
| Hand-review sheet | `scripts/make_review_sheet.py results/answers/<run>.jsonl` |

## Layout
| Path | What |
|---|---|
| `src/relay/papers.py`, `ingest.py`, `chunking.py` | Pinned papers; PDF → clean labelled paragraphs → chunks (no truncation, nothing dropped) |
| `src/relay/retrieval.py`, `retrieval_eval.py` | BM25 / dense / hybrid retrieval, per-stage timings, recall metrics |
| `src/relay/benchmark.py`, `benchmark/questions.yaml` | 18 self-written questions (12 answerable, 4 near-miss, 1 off-topic, 1 false premise) |
| `src/relay/pipeline.py` | The five steps above |
| `src/relay/llm.py` | Streaming Groq client with model first- and last-token timestamps |
| `src/relay/gateway.py` | Admission, queue, buckets, retries, daily-budget handling |
| `src/relay/standin.py` | The calibrated stand-in model service |
| `src/relay/grader.py`, `results.py` | Deterministic grading; one results.csv row per request |
| `results/` | Raw logs: `probe/`, `retrieval/`, `answers/`, `load/`, `review/`, and `results.csv` |
| `docs/DECISIONS.md` | Every decision, measurement and bug, with who decided what |
| `docs/PROBE_FINDINGS.md`, `docs/TABLES.md` | What Groq actually does; the generated tables |

The papers and the built index are gitignored. Rebuild them with the setup commands.
