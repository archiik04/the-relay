"""M1: chunking rules, on synthetic paragraphs (no PDFs needed)."""

import pytest

from relay.chunking import chunk_paragraphs, count_tokens
from relay.ingest import Paragraph


def para(section, text, page=1, kind="body", paper="attention", table=False):
    return Paragraph(paper, page, section, kind, text, table)


def sentences(prefix, n):
    return " ".join(f"{prefix} sentence number {i} says something specific." for i in range(n))


def test_never_mixes_sections():
    paras = [para("1 Intro", sentences("Intro", 30)), para("2 Method", sentences("Method", 30), page=2)]
    for c in chunk_paragraphs(paras, target_tokens=128, overlap_tokens=16):
        assert ("Intro" in c.text) != ("Method" in c.text), c.text[:80]


def test_respects_token_target():
    paras = [para("1 Intro", sentences("Intro", 200))]
    chunks = chunk_paragraphs(paras, target_tokens=128, overlap_tokens=16)
    assert len(chunks) > 1
    assert all(c.n_tokens <= 128 for c in chunks)


def test_overlap_repeats_tail_within_section_only():
    paras = [para("1 Intro", sentences("Intro", 60)), para("2 Method", sentences("Method", 60), page=2)]
    chunks = chunk_paragraphs(paras, target_tokens=128, overlap_tokens=32)
    for prev, nxt in zip(chunks, chunks[1:]):
        last_sentence = prev.text.rsplit(". ", 1)[-1]
        if prev.section == nxt.section:
            assert last_sentence in nxt.text, "next chunk should start with the previous tail"
        else:
            assert not nxt.text.startswith(last_sentence)


def test_zero_overlap_allowed():
    chunks = chunk_paragraphs([para("1 Intro", sentences("Intro", 60))], target_tokens=128, overlap_tokens=0)
    assert all(c.n_tokens <= 128 for c in chunks)


def test_overlap_must_be_smaller_than_target():
    with pytest.raises(ValueError):
        chunk_paragraphs([para("1 Intro", "x")], target_tokens=64, overlap_tokens=64)


def test_page_range_tracks_source_pages():
    paras = [para("3 Model", sentences("A", 10), page=4), para("3 Model", sentences("B", 10), page=5)]
    [c] = chunk_paragraphs(paras, target_tokens=1000, overlap_tokens=0)
    assert (c.page_start, c.page_end) == (4, 5)
    assert c.citation == "[attention pp.4-5]"


@pytest.mark.parametrize("kind", ["references", "excluded"])
def test_non_searchable_kinds_are_dropped(kind):
    paras = [para("References", "Vaswani et al. Attention.", kind=kind), para("1 Intro", "Real text here.")]
    chunks = chunk_paragraphs(paras, target_tokens=128, overlap_tokens=0)
    assert [c.section for c in chunks] == ["1 Intro"]


def test_enormous_table_row_is_split_not_truncated():
    header = "[Table on page 3] Table 9: wide\n|A|B|\n|---|---|"
    huge_row = "|" + "|".join(f"{i}.5 ± 0.{i % 10}" for i in range(300)) + "|"
    chunks = chunk_paragraphs([para("5 Eval", f"{header}\n{huge_row}", table=True)], target_tokens=128, overlap_tokens=0)
    indexed = " ".join(c.text for c in chunks)
    for cell in huge_row.strip("|").split("|"):
        assert cell in indexed, f"lost cell {cell!r}"
    assert "�" not in indexed, "a character was broken in half"
    assert all("|A|B|" in c.text for c in chunks)


def test_split_table_repeats_header():
    header = "[Table on page 8] Table 2: BLEU scores\n|Model|BLEU|Params|\n|---|---|---|"
    rows = "\n".join(f"|Model{i}|{20 + i}.1|{100 + i}M|" for i in range(80))
    chunks = chunk_paragraphs([para("6 Results", f"{header}\n{rows}", table=True)], target_tokens=128, overlap_tokens=16)
    assert len(chunks) > 1
    for c in chunks:
        assert "|Model|BLEU|Params|" in c.text, "every table piece needs its column names"


def _words_len(text: str) -> int:
    """Fake model tokenizer: one token per whitespace word."""
    return len(text.split())


def test_model_limit_is_never_exceeded_and_no_word_is_lost():
    long_para = " ".join(f"w{i}" for i in range(500))  # one giant sentence, no boundaries
    paras = [para("3 Model", long_para), para("3 Model", sentences("Tail", 20), page=2)]
    limit = 60
    chunks = chunk_paragraphs(paras, target_tokens=2000, overlap_tokens=0, model_len=_words_len, model_limit=limit)
    for c in chunks:
        assert _words_len(c.search_text) <= limit
    joined = " ".join(c.text for c in chunks).split()
    for w in long_para.split() + sentences("Tail", 20).split():
        assert w in joined, f"lost {w}"


def test_model_limit_with_overlap_never_emits_overlap_only_chunk():
    paras = [para("3 Model", sentences("S", 80))]
    chunks = chunk_paragraphs(paras, target_tokens=400, overlap_tokens=60, model_len=_words_len, model_limit=50)
    assert all(_words_len(c.search_text) <= 50 for c in chunks)
    # Each chunk must add new content: no chunk is a subset of its predecessor.
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.text not in prev.text


def test_model_len_requires_limit():
    with pytest.raises(ValueError):
        chunk_paragraphs([para("1 Intro", "x")], 64, 0, model_len=_words_len)


def test_last_paragraph_of_document_is_kept():
    paras = [para("7 Conclusion", sentences("Body", 30)), para("7 Conclusion", "The very last words.", page=10)]
    chunks = chunk_paragraphs(paras, target_tokens=128, overlap_tokens=16)
    assert chunks[-1].text.endswith("The very last words.")
    assert chunks[-1].page_end == 10


def test_empty_input_gives_no_chunks():
    assert chunk_paragraphs([], 128, 16) == []


def test_token_counter_handles_special_token_text():
    # Moshi p.30 literally contains "<|endoftext|>"; it must count as plain text.
    assert count_tokens("separated using the <|endoftext|> token") > 3
