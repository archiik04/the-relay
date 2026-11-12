"""Retrieval: BM25, dense (bge-small), Reciprocal Rank Fusion, optional cross-encoder rerank.

Modular on purpose (Archi's requirement): a RetrievalConfig picks the chunk index
and which stages run, so settings can be compared without touching chunking.

Every search returns per-stage timings (ms) and the raw evidence signals
(best cosine, best BM25, best rerank score). The "is there enough evidence?"
branch must use those signals, NOT the fused RRF score: RRF depends only on rank
positions, so the top hit of an unanswerable question gets the same RRF score as
the top hit of an answerable one.

Models load once per process and are warmed up, so the first query isn't
charged for model loading. All of this is CPU-bound and synchronous; the async
pipeline (M4) must call it via asyncio.to_thread.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

import numpy as np
from rank_bm25 import BM25Okapi

from relay.chunking import Chunk
from relay.config import PROJECT_ROOT

INDEX_DIR = PROJECT_ROOT / "index"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
# bge v1.5 recommends this instruction on short queries (not on passages).
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

STOPWORDS = frozenset(
    "a an the of in on at to for from by with and or is are was were be been being this that these those "
    "it its as which what who whom how why when where does do did can could would should will may might "
    "than then there their they we our you your i he she his her not no".split()
)
# Keeps compounds whole: "h-net", "rq-transformer", "28.4", "3.2.1", "gpt-3".
TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")


# ---------------------------------------------------------------- model input limits (no silent truncation)
# Both models read at most 512 word pieces. The reranker reads [CLS] query [SEP] passage [SEP],
# so the passage shares the window with the question. We reserve a question budget and size
# every chunk so that NEITHER model ever truncates it.
MODEL_MAX_WORDPIECES = 512
QUERY_BUDGET_WORDPIECES = 64  # ~45-50 English words
PAIR_SPECIAL_TOKENS = 3  # [CLS] [SEP] [SEP]
PASSAGE_LIMIT_WORDPIECES = MODEL_MAX_WORDPIECES - QUERY_BUDGET_WORDPIECES - PAIR_SPECIAL_TOKENS  # 445


@lru_cache(maxsize=1)
def _tokenizers():
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(EMBED_MODEL), AutoTokenizer.from_pretrained(RERANK_MODEL)


def wordpieces(text: str) -> int:
    """Word pieces (without special tokens) under the stricter of the two model tokenizers."""
    return max(len(tok(text, add_special_tokens=False, truncation=False)["input_ids"]) for tok in _tokenizers())


def bm25_tokens(text: str) -> list[str]:
    """Lowercased tokens; compounds kept whole AND split, so "H-Net" matches "H-Net" and "net"."""
    out: list[str] = []
    for tok in TOKEN.findall(text.lower()):
        if tok in STOPWORDS:
            continue
        out.append(tok)
        if "-" in tok:
            out.extend(p for p in tok.split("-") if p and p not in STOPWORDS)
    return out


def rrf(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal Rank Fusion: score(d) = sum over rankings of 1 / (k + rank), rank from 1."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, start=1):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank)
    return scores


def load_chunks(setting: str) -> list[Chunk]:
    path = INDEX_DIR / f"chunks-{setting}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run scripts/build_chunks.py")
    return [Chunk(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]


@lru_cache(maxsize=1)
def embed_model():
    from sentence_transformers import SentenceTransformer

    m = SentenceTransformer(EMBED_MODEL, device="cpu")
    m.encode(["warm up"], normalize_embeddings=True)
    return m


@lru_cache(maxsize=1)
def rerank_model():
    from sentence_transformers import CrossEncoder

    m = CrossEncoder(RERANK_MODEL, device="cpu")
    m.predict([("warm up", "warm up")])
    return m


def _embeddings(setting: str, chunks: list[Chunk]) -> np.ndarray:
    """Chunk embeddings, cached on disk; the cache is keyed by the exact texts embedded."""
    texts = [c.search_text for c in chunks]
    digest = hashlib.sha256("\n\x00".join(texts).encode()).hexdigest()[:16]
    slug = EMBED_MODEL.split("/")[-1]
    path = INDEX_DIR / f"emb-{setting}-{slug}-{digest}.npy"
    if path.exists():
        return np.load(path)
    vecs = embed_model().encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    np.save(path, vecs)
    return vecs


def truncation_report(setting: str) -> dict:
    """Measured word pieces per chunk under both tokenizers, against the passage limit.

    A chunk over the limit would be silently cut by the embedder (alone) or by the
    reranker (when paired with a question of up to QUERY_BUDGET_WORDPIECES).
    """
    chunks = load_chunks(setting)
    emb_tok, ce_tok = _tokenizers()

    def n(tok, text):
        return len(tok(text, add_special_tokens=False, truncation=False)["input_ids"])

    emb = [n(emb_tok, c.search_text) for c in chunks]
    ce = [n(ce_tok, c.search_text) for c in chunks]
    over = sum(max(a, b) > PASSAGE_LIMIT_WORDPIECES for a, b in zip(emb, ce))
    return {
        "setting": setting,
        "chunks": len(chunks),
        "passage_limit": PASSAGE_LIMIT_WORDPIECES,
        "embed_longest": max(emb),
        "rerank_longest": max(ce),
        "over_limit": over,
    }


@dataclass(frozen=True)
class RetrievalConfig:
    chunks: str = "t256-o32"  # which chunk index (chunking setting)
    mode: Literal["bm25", "dense", "hybrid"] = "hybrid"
    top_k: int = 4  # pieces handed to the model
    fetch_k: int = 20  # candidates per retriever before fusion / rerank
    rerank: bool = False
    rrf_k: int = 60

    @property
    def name(self) -> str:
        return f"{self.chunks}|{self.mode}|k{self.top_k}|{'rerank' + str(self.fetch_k) if self.rerank else 'norerank'}"


@dataclass
class Hit:
    chunk: Chunk
    rank: int
    fused: float
    bm25: float | None = None
    cosine: float | None = None
    rerank: float | None = None


@dataclass
class RetrievalResult:
    hits: list[Hit]
    timings_ms: dict[str, float] = field(default_factory=dict)
    # Evidence signals over the final candidates: inputs to the sufficiency branch.
    max_bm25: float | None = None
    max_cosine: float | None = None
    max_rerank: float | None = None
    # True if rerank was configured but skipped because the question exceeded its budget.
    rerank_skipped_long_query: bool = False


class Retriever:
    def __init__(self, config: RetrievalConfig):
        self.config = config
        self.chunks = load_chunks(config.chunks)
        self.bm25 = BM25Okapi([bm25_tokens(c.search_text) for c in self.chunks]) if config.mode != "dense" else None
        self.vectors = _embeddings(config.chunks, self.chunks) if config.mode != "bm25" else None
        if config.rerank:
            rerank_model()

    def warm_up(self) -> None:
        """Load models and run one search, so the first timed request isn't charged for loading.

        Found in M4: the first real search loaded the embedding model inside the 5 s tool
        timeout, timed out twice, and the question was reported as search_failed.
        """
        self.search("warm up")

    def _paper_mask(self, paper: str) -> np.ndarray:
        mask = np.array([c.paper == paper for c in self.chunks])
        if not mask.any():
            raise ValueError(f"unknown paper {paper!r}")
        return mask

    def search(self, query: str, paper: str | None = None) -> RetrievalResult:
        """Top-k chunks for `query`; `paper` restricts the search to one paper (comparison branch)."""
        if not query or not query.strip():
            raise ValueError("empty query")
        cfg = self.config
        mask = self._paper_mask(paper) if paper else None
        t: dict[str, float] = {}
        t0 = time.perf_counter()
        # Never truncate silently: a question over budget skips rerank, and the result says so.
        skip_rerank = cfg.rerank and wordpieces(query) > QUERY_BUDGET_WORDPIECES
        rankings: list[list[int]] = []
        bm25_scores = cos = None

        if self.bm25 is not None:
            s = time.perf_counter()
            bm25_scores = self.bm25.get_scores(bm25_tokens(query))
            if mask is not None:
                bm25_scores = np.where(mask, bm25_scores, -np.inf)
            rankings.append(_ranked(bm25_scores, cfg.fetch_k))
            t["bm25_ms"] = _ms(s)

        if self.vectors is not None:
            s = time.perf_counter()
            qv = embed_model().encode([QUERY_INSTRUCTION + query], normalize_embeddings=True)[0]
            t["embed_query_ms"] = _ms(s)
            s = time.perf_counter()
            cos = self.vectors @ qv
            if mask is not None:
                cos = np.where(mask, cos, -np.inf)
            rankings.append(_ranked(cos, cfg.fetch_k))
            t["dense_ms"] = _ms(s)

        s = time.perf_counter()
        fused = rrf(rankings, cfg.rrf_k)
        candidates = sorted(fused, key=lambda i: -fused[i])[: cfg.fetch_k]
        t["fusion_ms"] = _ms(s)

        rerank_scores: dict[int, float] = {}
        if cfg.rerank and not skip_rerank:
            s = time.perf_counter()
            pairs = [(query, self.chunks[i].search_text) for i in candidates]
            for i, sc in zip(candidates, rerank_model().predict(pairs)):
                rerank_scores[i] = float(sc)
            candidates = sorted(candidates, key=lambda i: -rerank_scores[i])
            t["rerank_ms"] = _ms(s)

        final = candidates[: cfg.top_k]
        hits = [
            Hit(
                chunk=self.chunks[i],
                rank=r,
                fused=fused[i],
                bm25=float(bm25_scores[i]) if bm25_scores is not None else None,
                cosine=float(cos[i]) if cos is not None else None,
                rerank=rerank_scores.get(i),
            )
            for r, i in enumerate(final, start=1)
        ]
        t["total_ms"] = _ms(t0)
        return RetrievalResult(
            hits=hits,
            timings_ms=t,
            max_bm25=max((h.bm25 for h in hits if h.bm25 is not None), default=None),
            max_cosine=max((h.cosine for h in hits if h.cosine is not None), default=None),
            max_rerank=max((h.rerank for h in hits if h.rerank is not None), default=None),
            rerank_skipped_long_query=skip_rerank,
        )


def _ranked(scores: np.ndarray, k: int) -> list[int]:
    """Indices of the top-k scores, never including masked-out (-inf) chunks."""
    order = np.argsort(-scores)[:k]
    return [int(i) for i in order if np.isfinite(scores[i])]


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)
