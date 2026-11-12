"""Validate benchmark/questions.yaml against the real extracted paper text.

Usage: uv run python scripts/check_benchmark.py
Exit code 1 if there are errors. Warnings are printed for a human to judge.
"""

import sys

import pymupdf

from relay import benchmark
from relay.config import get_settings
from relay.ingest import extract_paragraphs
from relay.papers import PAPERS


def main() -> int:
    questions = benchmark.load()
    page_text: dict[tuple[str, int], str] = {}
    page_counts: dict[str, int] = {}
    for paper in PAPERS:
        with pymupdf.open(get_settings().papers_dir / paper.filename) as doc:
            page_counts[paper.key] = doc.page_count
        for p in extract_paragraphs(paper):
            if p.kind in ("body", "appendix"):
                key = (paper.key, p.page)
                page_text[key] = page_text.get(key, "") + " " + p.text

    errors, warnings = benchmark.validate(questions, page_text, page_counts)
    counts = benchmark.summary(questions)
    answerable = sum(q.answerable for q in questions)
    print(f"{len(questions)} questions ({answerable} answerable, {len(questions) - answerable} should be refused)")
    for cat, n in sorted(counts.items()):
        print(f"  {cat:<24} {n}")
    if len(questions) < 15:
        print(f"NOTE: the brief requires at least 15 (have {len(questions)})")
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
