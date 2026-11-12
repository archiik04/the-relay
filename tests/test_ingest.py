"""M1: extraction against the real PDFs (skipped if papers aren't fetched).

Each test pins down a problem actually found while inspecting the PDFs.
"""

import re

import pytest

from relay.chunking import chunk_paragraphs
from relay.config import get_settings
from relay.ingest import (
    NUMBERED_TITLE,
    dehyphenate,
    extract_paragraphs,
    looks_like_figure_text,
    table_is_figure,
)
from relay.papers import PAPERS, PAPERS_BY_KEY

# ---------------------------------------------------------------- unit rules


def test_dehyphenate_rejoins_line_break_words():
    assert dehyphenate(["the se-", "mantic tokens"]) == "the semantic tokens"
    assert dehyphenate(["speech-", "Text"]) == "speech- Text"  # capitalised: not a split word


@pytest.mark.parametrize("text", ["3 Model Architecture", "3Model", "3.2.1 Scaled Dot-Product", "A Related Work", "A.1 Static Chunking"])
def test_numbered_title_accepts_section_headings(text):
    assert NUMBERED_TITLE.match(text)


@pytest.mark.parametrize("text", ["XL Scale.", "DC is composed of", "TTS Training.", "HG38. We trained", "WSJ 23 F1"])
def test_numbered_title_rejects_lookalikes(text):
    # These were false headings in the first extraction pass.
    assert not NUMBERED_TITLE.match(text)


@pytest.mark.parametrize("text", ["!new_", "n e w _ p r o d u c t !", "It", "#duct!"])
def test_figure_text_detected(text):
    assert looks_like_figure_text(text)


def test_real_sentence_is_not_figure_text():
    assert not looks_like_figure_text("In this work we employ h = 8 parallel attention layers.")


def test_figure_mistaken_for_table():
    assert table_is_figure("|n e w p r o d u c t ! / _ _ / # # #|")
    assert not table_is_figure("|Transformer (big)|28.4|41.8|2.3 · 1019|")


# ---------------------------------------------------------------- real PDFs

needs_pdfs = pytest.mark.skipif(
    not all((get_settings().papers_dir / p.filename).exists() for p in PAPERS),
    reason="run scripts/fetch_papers.py first",
)


@pytest.fixture(scope="module")
def paragraphs():
    return {p.key: extract_paragraphs(p) for p in PAPERS}


@needs_pdfs
def test_known_sentence_has_right_section_and_page(paragraphs):
    hits = [p for p in paragraphs["attention"] if "we employ h = 8 parallel attention layers" in p.text]
    assert len(hits) == 1
    assert hits[0].section == "3.2.2 Multi-Head Attention"
    assert hits[0].page == 5


@needs_pdfs
def test_moshi_headings_have_spaces_restored(paragraphs):
    sections = {p.section for p in paragraphs["moshi"]}
    assert "Appendix A. Additional ablation on Mimi codec" in sections
    assert "3.2 The Helium Text Language Model" in sections


@needs_pdfs
def test_no_glued_words_in_searchable_text(paragraphs):
    for key, paras in paragraphs.items():
        for p in paras:
            if p.kind in ("body", "appendix") and not p.is_table:
                glued = [w for w in p.text.split() if len(w) >= 22 and re.fullmatch(r"[A-Za-z,.:;]+", w)]
                assert not glued, (key, p.page, glued[:3])


@needs_pdfs
def test_moshi_appendix_f_fully_excluded(paragraphs):
    for p in paragraphs["moshi"]:
        if re.match(r"^(Appendix F\b|F\.\d)", p.section):
            assert p.kind == "excluded", p.section


@needs_pdfs
def test_references_are_not_searchable(paragraphs):
    for key, paras in paragraphs.items():
        refs = [p for p in paras if p.section == "References"]
        assert refs, f"{key}: references section not detected"
        chunks = chunk_paragraphs(paras, 256, 32)
        assert not any(c.section == "References" for c in chunks)


@needs_pdfs
def test_attention_appendix_follows_references(paragraphs):
    vis = [p for p in paragraphs["attention"] if p.section == "Attention Visualizations"]
    assert vis and all(p.kind == "appendix" for p in vis)


@needs_pdfs
def test_running_header_removed(paragraphs):
    title = PAPERS_BY_KEY["moshi"].title
    assert not any(p.text.strip() == title for p in paragraphs["moshi"])


@needs_pdfs
def test_tables_found_with_captions(paragraphs):
    tables = [p for p in paragraphs["attention"] if p.is_table]
    assert len(tables) == 4
    t2 = [p for p in tables if p.page == 8][0]
    assert "Table 2:" in t2.text.split("\n")[0] and "BLEU" in t2.text
    assert "28.4" in t2.text  # Transformer (big) EN-DE BLEU survives extraction


@needs_pdfs
def test_hnet_figure_on_page_7_is_not_a_table(paragraphs):
    assert not any(p.is_table and p.page == 7 for p in paragraphs["hnet"])
