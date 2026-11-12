"""Render submission/conversation-history.md as a PDF (submission/The_Relay_Conversation_History.pdf).

Uses the write-up's styles; code blocks and Markdown tables are kept as preformatted text so nothing is lost.
"""

import re
import sys
from pathlib import Path

from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Preformatted, Spacer
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_report_pdf as R  # noqa: E402

SRC = R.ROOT / "submission" / "conversation-history.md"
OUT = R.ROOT / "submission" / "The_Relay_Conversation_History.pdf"
PRE = ParagraphStyle("pre", fontName=R.MONO, fontSize=6.6, leading=7.8, leftIndent=6, spaceAfter=3)
WHO_A = ParagraphStyle("whoA", parent=R.S["h2"], fontSize=9.6, spaceBefore=7, textColor=R.FLAG)
WHO_C = ParagraphStyle("whoC", parent=R.S["h2"], fontSize=9.6, spaceBefore=5)
BODY = ParagraphStyle("tb", parent=R.S["body"], fontSize=8.4, leading=10.0, spaceAfter=1.6)


def story_for(md: str) -> list:
    story: list = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            story.append(Preformatted("\n".join(buf) or " ", PRE, maxLineLength=150))
            continue
        if line.startswith("|"):
            buf = []
            while i < len(lines) and lines[i].startswith("|"):
                buf.append(lines[i])
                i += 1
            story.append(Preformatted("\n".join(buf), PRE, maxLineLength=150))
            continue
        if line.startswith("# "):
            story.append(Paragraph(R.inline(line[2:]), R.S["title"]))
        elif line.startswith("## "):
            story.append(Paragraph(escape(line[3:]), WHO_A))
        elif line.startswith("### "):
            story.append(Paragraph(escape(line[4:]), WHO_C))
        elif line.strip():
            text = line.strip()
            bullet = re.match(r"^(\s*)(- |\* |\d+\. )", line)
            try:
                p = Paragraph(R.inline(re.sub(r"^\s*(- |\* )", "", text)), BODY,
                              bulletText="•" if bullet and not bullet.group(2)[0].isdigit() else None)
            except Exception:  # unusual markup in a message: show it as plain text instead
                p = Paragraph(escape(text), BODY)
            story.append(p)
        else:
            story.append(Spacer(1, 1.5))
        i += 1
    return story


def main() -> None:
    R.build(story_for(SRC.read_text(encoding="utf-8")), OUT)
    from pypdf import PdfReader
    print(f"{OUT}: {len(PdfReader(str(OUT)).pages)} pages")


if __name__ == "__main__":
    main()
