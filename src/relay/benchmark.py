"""Benchmark questions: loading and validation.

Validation does more than check the schema: for every answerable question it
confirms that each key fact actually appears in the extracted text of the gold
pages. That catches wrong page numbers, and facts our extraction mangles
(table misalignment, "10^19" -> "1019"), before any experiment relies on them.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from relay.config import PROJECT_ROOT
from relay.papers import PAPERS_BY_KEY

BENCHMARK_PATH = PROJECT_ROOT / "benchmark" / "questions.yaml"

CATEGORIES = {
    "body_fact",
    "number_text",
    "number_table",
    "appendix",
    "cross_paper",
    "multi_part",
    "unanswerable_near_miss",
    "unanswerable_off_topic",
    "false_premise",
}
UNANSWERABLE = {"unanswerable_near_miss", "unanswerable_off_topic"}


@dataclass
class Evidence:
    paper: str
    pages: list[int]


@dataclass
class Question:
    id: str
    question: str
    category: str
    answerable: bool
    answer: str
    key_facts: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    notes: str = ""


ALT_SEP = " | "


def alternatives(fact: str) -> list[str]:
    """A key fact may list accepted wordings: "sine | sinusoidal". Any one of them counts."""
    return [a.strip() for a in fact.split(ALT_SEP) if a.strip()]


def _fact(k) -> str:
    # In YAML, alternatives are written as a list: - [sine, sinusoidal]
    return ALT_SEP.join(str(a) for a in k) if isinstance(k, list) else str(k)


def load(path: Path = BENCHMARK_PATH) -> list[Question]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for q in raw.get("questions") or []:
        ev = [Evidence(e["paper"], list(e["pages"])) for e in (q.get("evidence") or [])]
        out.append(Question(
            id=str(q["id"]), question=q["question"], category=q["category"],
            answerable=bool(q["answerable"]), answer=q.get("answer", ""),
            key_facts=[_fact(k) for k in (q.get("key_facts") or [])], evidence=ev, notes=q.get("notes", ""),
        ))
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def validate(questions: list[Question], page_text: dict[tuple[str, int], str], page_counts: dict[str, int]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors must be fixed; warnings need a human look.

    page_text maps (paper, page) -> extracted searchable text of that page.
    """
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for q in questions:
        where = f"{q.id}:"
        if q.id in seen:
            errors.append(f"{where} duplicate id")
        seen.add(q.id)
        if q.category not in CATEGORIES:
            errors.append(f"{where} unknown category '{q.category}'")
        if not q.question.strip():
            errors.append(f"{where} empty question")
        if q.category in UNANSWERABLE and q.answerable:
            errors.append(f"{where} category {q.category} but answerable: true")
        if q.category == "false_premise":
            # The correct behaviour is to challenge the premise. Evidence, if given, is the
            # passage that contradicts it, and key_facts are the correct facts.
            if q.answerable:
                errors.append(f"{where} false_premise must be answerable: false (the premise must be challenged)")
            if q.evidence and not q.key_facts:
                errors.append(f"{where} false_premise evidence given but no key_facts (the correct facts)")
            if not q.evidence:
                continue
        elif not q.answerable:
            if q.evidence:
                errors.append(f"{where} answerable: false but evidence listed")
            continue
        elif q.category in UNANSWERABLE:
            continue
        else:
            if not q.evidence:
                errors.append(f"{where} answerable but no evidence pages")
            if not q.key_facts:
                errors.append(f"{where} answerable but no key_facts")
        for ev in q.evidence:
            if ev.paper not in PAPERS_BY_KEY:
                errors.append(f"{where} unknown paper '{ev.paper}'")
                continue
            for pg in ev.pages:
                if not 1 <= pg <= page_counts[ev.paper]:
                    errors.append(f"{where} {ev.paper} has no page {pg}")
                elif not page_text.get((ev.paper, pg)):
                    warnings.append(f"{where} {ev.paper} p.{pg} has no searchable text (references/excluded/figure-only?)")
        gold = " ".join(page_text.get((ev.paper, pg), "") for ev in q.evidence for pg in ev.pages)
        for fact in q.key_facts:
            # At least one accepted wording must actually be on a gold page.
            if not any(_norm(a) in _norm(gold) for a in alternatives(fact)):
                warnings.append(f"{where} key fact '{fact}' not found in extracted text of its gold pages "
                                "(wrong page? or extraction mangled it: if so that's a finding)")
    return errors, warnings


def summary(questions: list[Question]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for q in questions:
        counts[q.category] = counts.get(q.category, 0) + 1
    return counts
