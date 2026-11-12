"""PDF -> clean, labelled paragraphs.

Every paragraph carries: paper, page, section (e.g. "3.2 Attention") and kind
(body / appendix / references / excluded). Chunking (chunking.py) only packs
paragraphs that share a section, so section and page metadata survive into
every citation.

Cleaning rules come from inspecting the three PDFs (see docs/DECISIONS.md, M1):
  - running page headers and bare page numbers are dropped;
  - a heading number on its own line is joined to its title ("3" + "Model Architecture");
  - headings typeset without space characters (Moshi) are rebuilt from glyph gaps;
  - short bold lead-ins ("RQ-Transformer.", "Residual Dropout") start the next paragraph,
    they are not sections;
  - words hyphenated across a line break are re-joined;
  - tables are extracted with PyMuPDF's table finder as one labelled paragraph each.
    KNOWN LIMITATION: it merges rows into groups, so a model name and its number
    can be misaligned. Table questions in the benchmark measure the damage;
  - figure text (symbol fragments, single words in attention visualisations) is dropped.
"""

import re
from collections import Counter
from dataclasses import dataclass

import pymupdf

from relay.config import get_settings
from relay.papers import Paper

# Sections dropped from the searchable index (decisions C1, C2).
EXCLUDED_SECTION_PATTERNS = {
    "*": [r"^acknowledge?ments"],
    # Synthetic example dialogues: their statements are not the paper's claims.
    "moshi": [r"^appendix f\b", r"^f\.\d"],
}
UNNUMBERED_HEADINGS = re.compile(r"^(abstract|references|acknowledge?ments.*|appendix\b.*)$", re.I)

NUMBER_ONLY = re.compile(r"^(?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)$")  # "3", "3.2.1", "A", "A.1"
# "3 Model", "3Model" (Moshi), "3.2 Title", "A Related Work", "A.1 Title". Not "3. Item" (list) nor "XL Scale".
NUMBERED_TITLE = re.compile(r"^(?:\d+(?:\.\d+)*\s*|[A-Z](?:\.\d+)*\s+)[A-Z]")
LIST_ITEM = re.compile(r"^\d+\.\s")


@dataclass
class Paragraph:
    paper: str
    page: int
    section: str
    kind: str  # body | appendix | references | excluded
    text: str
    is_table: bool = False


# ---------------------------------------------------------------- text repair helpers


def text_from_chars(spans: list[dict]) -> str:
    """Rebuild a line from glyph positions, inserting a space at visible gaps.

    Moshi's headings have no space characters, so plain extraction gives
    "AdditionalablationonMimicodec".
    """
    out: list[str] = []
    prev = None
    for span in spans:
        for ch in span["chars"]:
            c = ch["c"]
            if prev is not None and not c.isspace() and out and not out[-1].isspace():
                if ch["bbox"][0] - prev["bbox"][2] > 0.15 * span["size"]:
                    out.append(" ")
            out.append(c)
            prev = ch
    return re.sub(r"\s+", " ", "".join(out)).strip()


def dehyphenate(lines: list[str]) -> str:
    """Join lines; re-join words split by a line-break hyphen ("se-" + "mantic" -> "semantic")."""
    text = ""
    for ln in (x.strip() for x in lines):
        if not ln:
            continue
        if text.endswith("-") and ln[:1].islower() and len(text) > 1 and text[-2].isalpha():
            text = text[:-1] + ln
        else:
            text = f"{text} {ln}" if text else ln
    return re.sub(r"\s+", " ", text).strip()


def looks_like_figure_text(text: str) -> bool:
    """Figure labels: mostly symbols, runs of 1-2 char fragments, or 1-2 loose words."""
    t = text.strip()
    if not t:
        return True
    if sum(c.isalpha() for c in t) / len(t) < 0.5:
        return True
    words = t.split()
    if len(words) >= 4 and sum(len(w) for w in words) / len(words) < 2.2:
        return True
    return len(words) <= 2 and not any(c.isdigit() for c in t) and not t.endswith((".", ":"))


def table_is_figure(md: str) -> bool:
    """The table finder also fires on some figures (H-Net p.7: "n e w p r o d u c t !").

    A real table's cells are words and numbers; a figure's are mostly single glyphs.
    """
    tokens = [t for t in re.split(r"[\s|/]+", md) if t and not set(t) <= set("-:")]
    if not tokens:
        return True
    return sum(len(t) == 1 for t in tokens) / len(tokens) > 0.4


CAPTION = re.compile(r"^Table\s*\d+\s*:")


def _attach_captions(paragraphs: list["Paragraph"]) -> None:
    """Prefix each table with its caption from the same page (n-th table <-> n-th caption).

    The caption carries the searchable words ("BLEU", "WMT 2014") that the cells don't.
    """
    by_page: dict[int, tuple[list, list]] = {}
    for p in paragraphs:
        tables, captions = by_page.setdefault(p.page, ([], []))
        if p.is_table:
            tables.append(p)
        elif CAPTION.match(p.text):
            captions.append(p)
    for tables, captions in by_page.values():
        for table, caption in zip(tables, captions):
            label, _, body = table.text.partition("\n")
            table.text = f"{label} {caption.text}\n{body}"


def clean_table_markdown(md: str) -> str:
    md = md.replace("_._", ".").replace("_ ·_", " ·").replace("**", "").replace("<br>", " / ")
    md = re.sub(r"_([^\w\s|])_", r" \1 ", md)  # "81.0_±_1.3" -> "81.0 ± 1.3"
    md = md.replace("~~", "").replace("`", "")  # strikethrough/code marks the table finder invents
    md = re.sub(r"\|Col\d+", "|", md)
    return re.sub(r"[ \t]+", " ", md).strip()


# ---------------------------------------------------------------- extraction


def _line_info(line: dict) -> tuple[str, float, bool, list[dict]] | None:
    spans = [s for s in line["spans"] if "".join(c["c"] for c in s["chars"]).strip()]
    if not spans:
        return None
    # Glyph-gap rebuild, not raw concatenation: some lines store no space characters.
    text = text_from_chars(spans)
    size = round(max(s["size"] for s in spans), 1)
    bold = all("Bold" in s["font"] or s["flags"] & 16 for s in spans)
    return text, size, bold, spans


def _body_size(doc: pymupdf.Document) -> float:
    sizes: Counter = Counter()
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for s in line["spans"]:
                    sizes[round(s["size"], 1)] += len(s["text"].strip())
    return sizes.most_common(1)[0][0]


def _repeated_lines(doc: pymupdf.Document, min_share: float = 0.3) -> set[str]:
    """Lines recurring on many pages: running headers and footers."""
    counts: Counter = Counter()
    for page in doc:
        counts.update({ln.strip() for ln in page.get_text().splitlines() if len(ln.strip()) > 3})
    return {t for t, c in counts.items() if c >= max(3, min_share * doc.page_count)}


def _overlaps(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


class _State:
    def __init__(self, paper: Paper):
        self.paper = paper
        self.section = "Front matter"
        self.kind = "body"
        self.after_references = False
        self.pending_number: str | None = None
        self.pending_lead_in: str | None = None
        self.out: list[Paragraph] = []

    def set_section(self, title: str) -> None:
        if self.section.lower() == "references" or title.lower().startswith("appendix"):
            self.after_references = True
        self.section = title
        t = title.lower()
        pats = EXCLUDED_SECTION_PATTERNS["*"] + EXCLUDED_SECTION_PATTERNS.get(self.paper.key, [])
        if t == "references":
            self.kind = "references"
        elif any(re.search(p, t) for p in pats):
            self.kind = "excluded"
        else:
            self.kind = "appendix" if self.after_references else "body"

    def emit(self, page: int, text: str, is_table: bool = False) -> None:
        if self.pending_lead_in and not is_table:
            text = f"{self.pending_lead_in} {text}"
            self.pending_lead_in = None
        self.out.append(Paragraph(self.paper.key, page, self.section, self.kind, text, is_table))


def _heading_title(text: str, size: float, bold: bool, body: float, st: _State) -> str | None:
    """Return the heading title if this line is a section heading, else None."""
    if not bold or len(text) > 100 or text.endswith((".", ":")) or LIST_ITEM.match(text):
        return None
    if NUMBER_ONLY.match(text) and size >= body - 0.2:
        return text
    # Title on the line after a lone number ("3" then "Model Architecture").
    if st.pending_number and size >= body - 0.2:
        return text
    if NUMBERED_TITLE.match(text) and size >= body - 0.2:
        return text
    if UNNUMBERED_HEADINGS.match(text) and size >= body - 0.2:
        return text
    # Unnumbered appendix headings set large (e.g. Attention's "Attention Visualizations").
    if (st.after_references or st.kind == "references") and size >= body + 1.5:
        return text
    return None


def extract_paragraphs(paper: Paper) -> list[Paragraph]:
    path = get_settings().papers_dir / paper.filename
    st = _State(paper)
    with pymupdf.open(path) as doc:
        body = _body_size(doc)
        repeated = _repeated_lines(doc)
        for pno, page in enumerate(doc, start=1):
            tables = [(t.bbox, clean_table_markdown(t.to_markdown())) for t in page.find_tables().tables]
            # Figures mistaken for tables: drop their text entirely (their area stays masked).
            tables = [(bb, "" if table_is_figure(md) else md) for bb, md in tables]
            emitted_tables: set[int] = set()
            for block in page.get_text("rawdict")["blocks"]:
                hit = [i for i, (bb, _) in enumerate(tables) if _overlaps(block["bbox"], bb)]
                if hit:
                    for i in hit:
                        if i not in emitted_tables:
                            emitted_tables.add(i)
                            if tables[i][1]:
                                st.emit(pno, f"[Table on page {pno}]\n{tables[i][1]}", is_table=True)
                    continue
                _block(block, pno, body, repeated, st)
            for i, (_, md) in enumerate(tables):
                if i not in emitted_tables and md:
                    st.emit(pno, f"[Table on page {pno}]\n{md}", is_table=True)
    _attach_captions(st.out)
    return st.out


def _block(block: dict, pno: int, body: float, repeated: set[str], st: _State) -> None:
    lines: list[str] = []

    def flush():
        if not lines:
            return
        text = dehyphenate(lines)
        lines.clear()
        if not looks_like_figure_text(text):
            st.emit(pno, text)

    infos = [x for x in (_line_info(ln) for ln in block.get("lines", [])) if x]
    for idx, (text, size, bold, spans) in enumerate(infos):
        if text in repeated or (text.isdigit() and not bold) or text.startswith(f"arXiv:{st.paper.arxiv_id}"):
            continue
        rebuilt = text
        title = _heading_title(rebuilt, size, bold, body, st)
        if title:
            flush()
            if NUMBER_ONLY.match(title):
                st.pending_number = title
                continue
            if st.pending_number:
                title = f"{st.pending_number} {title}"
                st.pending_number = None
            title = re.sub(r"^(\d+(?:\.\d+)*)(?=[A-Z])", r"\1 ", title)  # "3Model" -> "3 Model"
            st.set_section(title)
            continue
        st.pending_number = None
        # A short bold line alone at the top of a block is a lead-in ("RQ-Transformer.").
        if bold and idx == 0 and len(rebuilt.split()) <= 6 and len(infos) == 1:
            st.pending_lead_in = rebuilt
            continue
        lines.append(text)
    flush()


def references_text(paper: Paper) -> str:
    """The bibliography: kept out of the search index, available if ever needed (C1)."""
    return "\n".join(p.text for p in extract_paragraphs(paper) if p.kind == "references")
