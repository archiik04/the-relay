# The Relay

A reliability-aware RAG pipeline that answers questions **only** from three
pinned arXiv papers, through a rate-limit-aware gateway to Groq (free tier),
plus a calibrated stand-in model service for loads Groq can't take.

## Setup
```bash
uv sync
cp .env.example .env        # add your Groq key; .env is gitignored
uv run python scripts/fetch_papers.py
uv run pytest -q
```

## Layout (grows per milestone)
| Path | Responsibility |
|---|---|
| `src/relay/papers.py` | The three papers and their pinned versions (single source of truth) |
| `src/relay/config.py` | Settings from env / `.env` |
| `scripts/fetch_papers.py` | Download + version-stamp check + `papers/manifest.json` |
| `src/relay/ingest.py` | PDF -> cleaned paragraphs with page, section, kind; tables with captions |
| `src/relay/chunking.py` | Section-aware packing with overlap; token counts |
| `scripts/build_chunks.py` | Builds `index/chunks-t<N>-o<M>.jsonl` + a sample to read |
| `scripts/probe_groq.py`, `analyze_probe.py` | M3 real-service probes and their analysis |
| `docs/PROBE_FINDINGS.md` | What Groq actually does (feeds Table 1) |
| `papers/manifest.json` | sha256, size, page count of each verified PDF |
| `docs/DECISIONS.md` | Decision log |
| `docs/INTERVIEW_PREP.md` | Concepts and likely questions |
| `results/` | `results.csv` and traces (from M7 onward) |

## Milestones
- [x] M0: repo, pinned papers, decision log
- [x] M1: ingestion + chunking (inspected by eye): `uv run python scripts/build_chunks.py --target 256`
- [ ] M2: benchmark questions + retrieval + recall@k (no LLM quota)
- [~] M3: Groq probe: limits, latency, 429 behaviour (fills Table 1). `concurrency` phase left.
- [ ] M4: end-to-end pipeline, single request
- [ ] M5: gateway (rate limits, budget, retries, deadlines, degradation)
- [ ] M6: stand-in service, calibrated from M3
- [ ] M7: open-loop load generator + `results.csv` + `analyze.py`
- [ ] M8: experiments
- [ ] M9: report
