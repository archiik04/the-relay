"""Section-aware chunking (decision C3).

Rules:
  1. A chunk never contains text from two sections, so its section label and
     citation are always true for every sentence in it.
  2. Whole paragraphs are packed until the next one would exceed `target_tokens`.
     A paragraph larger than the target is split at sentence boundaries (tables:
     at row boundaries), and only as a last resort at a token boundary.
  3. Each chunk after the first in a section starts with the last sentences of
     the previous chunk, up to `overlap_tokens`, so an idea that straddles the
     cut is still readable in one piece. Overlap never crosses a section.
  4. Every chunk records the pages its text came from (overlap included).

`target_tokens` and `overlap_tokens` are the knobs the retrieval experiment
(Table 3) varies. Token counts use tiktoken's o200k_base: an estimate of the
gpt-oss tokenizer, checked against Groq's reported prompt_tokens (decision C4).
"""

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import lru_cache
from itertools import groupby

import tiktoken

from relay.ingest import Paragraph
from relay.papers import PAPERS_BY_KEY

SEARCHABLE_KINDS = ("body", "appendix")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")


@lru_cache(maxsize=1)
def _encoder():
    return tiktoken.get_encoding("o200k_base")


def count_tokens(text: str) -> int:
    return len(_encoder().encode(text, disallowed_special=()))


@dataclass
class Chunk:
    chunk_id: str
    paper: str
    section: str
    kind: str
    page_start: int
    page_end: int
    text: str
    n_tokens: int
    has_table: bool

    @property
    def citation(self) -> str:
        pages = f"p.{self.page_start}" if self.page_start == self.page_end else f"pp.{self.page_start}-{self.page_end}"
        return f"[{self.paper} {pages}]"

    @property
    def search_text(self) -> str:
        """What retrieval indexes: paper title and section prefixed to the text.

        The prefix disambiguates generic passages ("our model", "Table 2") that
        appear in all three papers.
        """
        return f"{PAPERS_BY_KEY[self.paper].title} | {self.section}\n{self.text}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Unit:
    text: str
    page: int
    is_table: bool
    tokens: int


TABLE_HEADER_LINES = 3  # "[Table on page N]", the header row, the |---| separator


def _split_words(text: str, limit: int) -> list[str]:
    """Last resort: split between whole words so each piece is <= limit tokens.

    Never cuts inside a word or a multi-byte character, and never drops text.
    (An earlier version cut at tokenizer boundaries and decoded the pieces, which
    could split "±" in half; another cut over-long table rows and dropped the rest.)
    """
    pieces: list[str] = []
    current: list[str] = []
    for word in text.split(" "):
        if current and count_tokens(" ".join(current + [word])) > limit:
            pieces.append(" ".join(current))
            current = []
        current.append(word)  # a single word longer than `limit` is kept whole
    if current:
        pieces.append(" ".join(current))
    return pieces


def _split_row(row: str, limit: int) -> list[str]:
    """Split an over-long table row at cell boundaries, so a value stays with its
    error bar ("110.5 ± 0.0"). Only a single enormous cell falls back to words."""
    cells = row.strip("|").split("|")
    pieces: list[str] = []
    current: list[str] = []
    for cell in cells:
        if current and count_tokens("|" + "|".join(current + [cell]) + "|") > limit:
            pieces.append("|" + "|".join(current) + "|")
            current = []
        if count_tokens(f"|{cell}|") > limit:
            if current:
                pieces.append("|" + "|".join(current) + "|")
                current = []
            parts = _split_words(cell, limit - 2)
            pieces.extend(f"|{p}|" for p in parts)  # keep the cell delimiters: change nothing but the split
            continue
        current.append(cell)
    if current:
        pieces.append("|" + "|".join(current) + "|")
    return pieces


def _split_table(text: str, page: int, limit: int) -> list[_Unit]:
    """Split a table by rows, repeating its header on every piece.

    Without the header a piece is just numbers ("|SpaceByte |6.0 |570M"), and
    nothing says which column is which. A row too long for one piece is split
    between words across pieces (each still under the header); nothing is dropped.
    """
    lines = text.split("\n")
    header = "\n".join(lines[:TABLE_HEADER_LINES])
    room = limit - count_tokens(header) - 1
    if room < limit // 4:  # header alone nearly fills a chunk: fall back to plain splitting
        return _split_oversized(text, page, False, limit, table_fallback=True)
    rows: list[str] = []
    for row in lines[TABLE_HEADER_LINES:]:
        rows.extend(_split_row(row, room) if count_tokens(row) > room else [row])
    pieces: list[_Unit] = []
    batch: list[str] = []
    for row in rows:
        if batch and count_tokens("\n".join(batch + [row])) > room:
            body = header + "\n" + "\n".join(batch)
            pieces.append(_Unit(body, page, True, count_tokens(body)))
            batch = []
        batch.append(row)
    if batch:
        body = header + "\n" + "\n".join(batch)
        pieces.append(_Unit(body, page, True, count_tokens(body)))
    return pieces


def _split_oversized(text: str, page: int, is_table: bool, limit: int, table_fallback: bool = False) -> list[_Unit]:
    """Split one paragraph that is bigger than `limit` into units that each fit."""
    if is_table:
        return _split_table(text, page, limit)
    is_table = table_fallback
    pieces = text.split("\n") if is_table else SENTENCE_END.split(text)
    units: list[_Unit] = []
    for piece in pieces:
        for part in [piece] if count_tokens(piece) <= limit else _split_words(piece, limit):
            units.append(_Unit(part, page, is_table, count_tokens(part)))
    # Re-pack small pieces greedily so a long paragraph isn't shredded into sentences.
    packed: list[_Unit] = []
    for u in units:
        if packed and packed[-1].tokens + u.tokens + 1 <= limit:
            sep = "\n" if is_table else " "
            joined = packed[-1].text + sep + u.text
            packed[-1] = _Unit(joined, packed[-1].page, is_table, count_tokens(joined))
        else:
            packed.append(u)
    return packed


def _overlap_tail(units: list[_Unit], budget: int) -> list[_Unit]:
    """The last sentences of a chunk (never table rows), up to `budget` tokens."""
    if budget <= 0:
        return []
    tail: list[_Unit] = []
    used = 0
    for u in reversed(units):
        if u.is_table:
            break
        for sent in reversed(SENTENCE_END.split(u.text)):
            n = count_tokens(sent)
            if used + n > budget:
                return tail
            tail.insert(0, _Unit(sent, u.page, False, n))
            used += n
    return tail


def _make_chunk(paper: str, section: str, kind: str, units: list[_Unit], idx: int) -> Chunk:
    text = "\n".join(u.text for u in units)
    pages = [u.page for u in units]
    return Chunk(
        chunk_id=f"{paper}-{idx:04d}",
        paper=paper,
        section=section,
        kind=kind,
        page_start=min(pages),
        page_end=max(pages),
        text=text,
        n_tokens=count_tokens(text),
        has_table=any(u.is_table for u in units),
    )


ModelLen = Callable[[str], int]


def _search_prefix(paper: str, section: str) -> str:
    return f"{PAPERS_BY_KEY[paper].title} | {section}\n"  # must match Chunk.search_text


def _fit_unit(u: _Unit, prefix: str, model_len: ModelLen, limit: int) -> list[_Unit]:
    """Split a unit until prefix + unit fits the model limit: by lines, then sentences, then words.

    Nothing is dropped: every piece is kept, so no text is lost to truncation.
    """
    if model_len(prefix + u.text) <= limit:
        return [u]
    for splitter in (lambda s: s.split("\n"), SENTENCE_END.split, None):
        parts = splitter(u.text) if splitter else None
        if splitter is None:
            words = u.text.split(" ")
            if len(words) < 2:
                raise ValueError(f"a single word exceeds the model limit: {u.text[:40]!r}")
            mid = len(words) // 2
            parts = [" ".join(words[:mid]), " ".join(words[mid:])]
        parts = [p for p in parts if p.strip()]
        if len(parts) > 1:
            out: list[_Unit] = []
            for p in parts:
                out.extend(_fit_unit(_Unit(p, u.page, u.is_table, count_tokens(p)), prefix, model_len, limit))
            return out
    raise ValueError("unit could not be split to fit")  # unreachable: the word split always divides


def chunk_paragraphs(
    paragraphs: list[Paragraph],
    target_tokens: int,
    overlap_tokens: int,
    model_len: ModelLen | None = None,
    model_limit: int | None = None,
) -> list[Chunk]:
    """Pack paragraphs into chunks.

    If `model_len`/`model_limit` are given, every chunk's search_text is also
    guaranteed to be at most `model_limit` in that model's tokens (e.g. the
    embedding and reranker word pieces), so the model never silently truncates.
    """
    if overlap_tokens >= target_tokens:
        raise ValueError("overlap must be smaller than the target size")
    if (model_len is None) != (model_limit is None):
        raise ValueError("pass both model_len and model_limit, or neither")
    searchable = [p for p in paragraphs if p.kind in SEARCHABLE_KINDS]
    chunks: list[Chunk] = []
    # Consecutive paragraphs with the same section form one group.
    for (paper, section, kind), group in groupby(searchable, key=lambda p: (p.paper, p.section, p.kind)):
        prefix = _search_prefix(paper, section)
        units: list[_Unit] = []
        for p in group:
            n = count_tokens(p.text)
            if n <= target_tokens - overlap_tokens:
                pieces = [_Unit(p.text, p.page, p.is_table, n)]
            else:
                pieces = _split_oversized(p.text, p.page, p.is_table, target_tokens - overlap_tokens)
            for piece in pieces:
                units.extend(_fit_unit(piece, prefix, model_len, model_limit) if model_len else [piece])

        def fits(candidate: list[_Unit]) -> bool:
            if sum(x.tokens + 1 for x in candidate) > target_tokens:
                return False
            return model_len is None or model_len(prefix + "\n".join(x.text for x in candidate)) <= model_limit

        current: list[_Unit] = []
        for u in units:
            if current and not fits(current + [u]):
                chunks.append(_make_chunk(paper, section, kind, current, len(chunks)))
                current = _overlap_tail(current, overlap_tokens)
                if current and not fits(current + [u]):
                    current = []  # overlap + next unit can't fit: drop the overlap, never the content
            current.append(u)
        if current:  # end of section (and of document): the remainder always becomes a chunk
            chunks.append(_make_chunk(paper, section, kind, current, len(chunks)))
    return chunks
