"""M2: properties every BUILT chunk index must have (t256 and t384).

Run after scripts/build_chunks.py. These check the real output, not synthetic input:
  - no model ever truncates a chunk (word pieces under the passage limit, both tokenizers),
  - chunks are clean (no empty text, figure debris, running headers, glued words, page numbers),
  - only searchable sections are indexed,
  - nothing is lost at the end of a section or at the end of a document,
  - retrieval fails loudly on bad input and skips rerank (flagged) for over-long questions.
"""

import re

import pytest

from relay.ingest import extract_paragraphs, looks_like_figure_text
from relay.papers import PAPERS
from relay.retrieval import (
    INDEX_DIR,
    PASSAGE_LIMIT_WORDPIECES,
    RetrievalConfig,
    Retriever,
    load_chunks,
    wordpieces,
)

SETTINGS = [s for s in ("t256-o32", "t384-o32") if (INDEX_DIR / f"chunks-{s}.jsonl").exists()]
pytestmark = pytest.mark.skipif(not SETTINGS, reason="run scripts/build_chunks.py first")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


@pytest.fixture(scope="module")
def paragraphs():
    return {p.key: [x for x in extract_paragraphs(p) if x.kind in ("body", "appendix")] for p in PAPERS}


@pytest.mark.parametrize("setting", SETTINGS)
def test_no_chunk_exceeds_model_window(setting):
    over = [c.chunk_id for c in load_chunks(setting) if wordpieces(c.search_text) > PASSAGE_LIMIT_WORDPIECES]
    assert not over, over[:5]


@pytest.mark.parametrize("setting", SETTINGS)
def test_chunks_are_clean(setting):
    titles = {p.title for p in PAPERS}
    for c in load_chunks(setting):
        assert c.text.strip(), c.chunk_id
        assert c.kind in ("body", "appendix") and c.section not in ("References",), c.chunk_id
        assert "\x00" not in c.text
        assert not (looks_like_figure_text(c.text) and not c.has_table), (c.chunk_id, c.text[:60])
        for line in c.text.split("\n"):
            # The title legitimately appears once, on page 1. Anywhere else it's a running header.
            if c.page_start > 1:
                assert line.strip() not in titles, f"{c.chunk_id}: running header left in"
            if not c.has_table:
                assert not line.strip().isdigit(), f"{c.chunk_id}: bare page number"
        if not c.has_table:
            glued = [w for w in c.text.split() if len(w) >= 22 and re.fullmatch(r"[A-Za-z,.:;]+", w)]
            assert not glued, (c.chunk_id, glued[:3])
        assert 1 <= c.page_start <= c.page_end


@pytest.mark.parametrize("setting", SETTINGS)
def test_end_of_every_section_and_document_is_indexed(setting, paragraphs):
    chunks = load_chunks(setting)
    for key, paras in paragraphs.items():
        by_section: dict[str, list] = {}
        for p in paras:
            by_section.setdefault(p.section, []).append(p)
        # The section's LAST chunk must end with the section's actual final words.
        # (Completeness of everything before that is covered by the word-level test.)
        for section, ps in by_section.items():
            final_words = " ".join(norm(ps[-1].text).split()[-3:])
            sec_chunks = [c for c in chunks if c.paper == key and c.section == section]
            assert sec_chunks, f"{key} / {section}: no chunks"
            assert norm(sec_chunks[-1].text).endswith(final_words), f"{key} / {section}: end of section missing"
        # End of document: the paper's last chunk ends with its last searchable words.
        final_words = " ".join(norm(paras[-1].text).split()[-3:])
        paper_chunks = [c for c in chunks if c.paper == key]
        assert norm(paper_chunks[-1].text).endswith(final_words), f"{key}: end of document missing"


@pytest.mark.parametrize("setting", SETTINGS)
def test_every_word_of_searchable_text_is_indexed(setting, paragraphs):
    chunks = load_chunks(setting)
    def words(s: str) -> set[str]:
        # "|" separates table cells; a row legitimately splits between cells.
        return {w for w in re.split(r"[\s|]+", s) if w}

    for key, paras in paragraphs.items():
        indexed = words(" ".join(c.text for c in chunks if c.paper == key))
        missing = words(" ".join(p.text for p in paras)) - indexed
        assert not missing, f"{key}: {sorted(missing)[:10]}"


def test_missing_index_raises():
    with pytest.raises(FileNotFoundError):
        load_chunks("t9999-o0")


def test_empty_query_rejected():
    r = Retriever(RetrievalConfig(chunks=SETTINGS[0], mode="bm25"))
    with pytest.raises(ValueError):
        r.search("   ")


def test_paper_filter_returns_only_that_paper():
    r = Retriever(RetrievalConfig(chunks=SETTINGS[-1], mode="hybrid"))
    for paper in ("attention", "moshi", "hnet"):
        res = r.search("How are positions or boundaries represented?", paper=paper)
        assert res.hits and all(h.chunk.paper == paper for h in res.hits)
    with pytest.raises(ValueError):
        r.search("x", paper="nope")


def test_over_long_question_skips_rerank_and_says_so():
    r = Retriever(RetrievalConfig(chunks=SETTINGS[0], mode="hybrid", rerank=True))
    long_q = "Explain " + " and ".join(["how the encoder handles very long attention contexts"] * 12) + "?"
    res = r.search(long_q)
    assert res.rerank_skipped_long_query and res.max_rerank is None and "rerank_ms" not in res.timings_ms
    short = r.search("What is Mimi?")
    assert not short.rerank_skipped_long_query and short.max_rerank is not None
