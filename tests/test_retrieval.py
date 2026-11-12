"""M2: retrieval building blocks. Pure-function tests run instantly; the
end-to-end test uses the real models on the real t256 index."""

import pytest

from relay.benchmark import Evidence, Question
from relay.chunking import Chunk
from relay.retrieval import INDEX_DIR, Hit, RetrievalConfig, RetrievalResult, Retriever, bm25_tokens, rrf
from relay.retrieval_eval import coverage, group


def test_bm25_tokens_keep_compounds_and_numbers():
    toks = bm25_tokens("The H-Net reaches 28.4 BLEU in Section 3.2.1")
    for t in ("h-net", "h", "net", "28.4", "bleu", "3.2.1"):
        assert t in toks
    assert "the" not in toks and "in" not in toks


def test_rrf_symmetric_ranks_tie():
    fused = rrf([[1, 2, 3], [2, 1, 4]], k=60)
    assert fused[1] == fused[2] > fused[3] == fused[4]  # same rank positions -> same score
    assert set(fused) == {1, 2, 3, 4}


def test_rrf_rewards_agreement_over_one_first_place():
    # Item 2 is second in BOTH searches; item 1 is first in only one.
    fused = rrf([[1, 2], [3, 2]], k=60)
    assert fused[2] > fused[1] == fused[3]


def _chunk(paper, a, b):
    return Chunk(f"{paper}-x", paper, "s", "body", a, b, "t", 1, False)


def _q(evidence, category="body_fact"):
    return Question("q", "?", category, bool(evidence), "", ["x"], evidence)


def test_coverage_page_ranges_and_mrr_rank():
    res = RetrievalResult(hits=[Hit(_chunk("moshi", 3, 4), 1, 0.1), Hit(_chunk("attention", 7, 9), 2, 0.1)])
    cov = coverage(_q([Evidence("attention", [8])]), res)
    assert cov.any_hit and cov.all_evidence and cov.first_rank == 2


def test_coverage_requires_matching_paper():
    res = RetrievalResult(hits=[Hit(_chunk("moshi", 8, 8), 1, 0.1)])
    assert not coverage(_q([Evidence("attention", [8])]), res).any_hit


def test_multi_part_needs_all_evidence():
    res = RetrievalResult(hits=[Hit(_chunk("attention", 8, 8), 1, 0.1)])
    cov = coverage(_q([Evidence("attention", [8]), Evidence("hnet", [12])], "multi_part"), res)
    assert cov.any_hit and not cov.all_evidence


def test_refusal_groups_have_no_coverage_and_separate_groups():
    nm = _q([], "unanswerable_near_miss")
    assert coverage(nm, RetrievalResult(hits=[])) is None
    assert group(nm) == "near_miss"
    assert group(_q([], "unanswerable_off_topic")) == "off_topic"
    assert group(_q([], "false_premise")) == "false_premise"
    assert group(_q([Evidence("hnet", [1])], "number_table")) == "answerable"


@pytest.mark.skipif(not (INDEX_DIR / "chunks-t256-o32.jsonl").exists(), reason="build chunks first")
def test_hybrid_rerank_end_to_end_on_real_index():
    r = Retriever(RetrievalConfig(chunks="t256-o32", mode="hybrid", top_k=4, rerank=True))
    res = r.search("How many parallel attention heads does the Transformer use?")
    assert len(res.hits) == 4
    assert {"bm25_ms", "embed_query_ms", "dense_ms", "fusion_ms", "rerank_ms", "total_ms"} <= set(res.timings_ms)
    assert res.max_rerank is not None and res.max_cosine is not None
    # The known passage (Attention p.5, section 3.2.2) should be found.
    assert any(h.chunk.paper == "attention" and h.chunk.page_start <= 5 <= h.chunk.page_end for h in res.hits)
