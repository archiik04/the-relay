"""Deterministic answer grading (decision P5).

One grader, used unchanged for every setting, model and run. No model judges the
answers. If a rule here changes, re-grade every saved answer (scripts/grade_answers.py)
so the tables never mix grader versions.

Grades are the brief's: correct | wrong | refused_correctly | refused_wrongly.
A run that never reached an answer (search failed, model rate-limited/timed out)
gets None: it is a reliability outcome, not an answer-quality one.

What this does NOT measure: whether each claim follows from its quote. That is
labelled by hand (P1), and reported as the unsupported-claim rate.
"""

import re
from dataclasses import dataclass

from relay.benchmark import Question, alternatives

# g1: first version. g2: accepted alternative wordings for a key fact; U+2011 hyphens normalised.
GRADER_VERSION = "g2"

ANSWER_STATUSES = {"answered"}
REFUSAL_STATUSES = {"not_in_papers", "premise_false", "unverified"}


@dataclass
class Grade:
    grade: str | None
    reason: str
    missing_facts: list[str]
    gold_cited: bool
    version: str = GRADER_VERSION


def _norm(s: str) -> str:
    s = s.replace("‑", "-").replace("‐", "-")  # the model's non-breaking hyphens
    return re.sub(r"\s+", " ", s).strip().casefold()


def has_fact(text: str, fact: str) -> bool:
    """Whole-word, case-insensitive match of any accepted wording ("sine | sinusoidal").

    '6' must not match '16', '64' or '6.5'; 'key' must not match 'keys'.
    """
    t = _norm(text)
    return any(re.search(r"(?<![\w.])" + re.escape(_norm(a)) + r"(?!\w)(?!\.\d)", t) for a in alternatives(fact))


def cited_pages(result: dict) -> set[tuple[str, int]]:
    """(paper, page) for every claim, from the chunk metadata the pipeline recorded."""
    by_id = {r["chunk_id"]: r["citation"] for r in result.get("retrieved", [])}
    out: set[tuple[str, int]] = set()
    for c in result.get("claims", []):
        cit = by_id.get(c.get("chunk_id"))
        m = cit and re.match(r"\[(\w+) pp?\.(\d+)(?:-(\d+))?\]", cit)
        if m:
            lo, hi = int(m.group(2)), int(m.group(3) or m.group(2))
            out |= {(m.group(1), p) for p in range(lo, hi + 1)}
    return out


def grade(q: Question, result: dict) -> Grade:
    status = result["final_status"]
    if status not in ANSWER_STATUSES | REFUSAL_STATUSES:
        return Grade(None, f"no answer produced ({status})", [], False)

    gold = {(e.paper, p) for e in q.evidence for p in e.pages}
    gold_cited = bool(gold & cited_pages(result))
    answer_text = " ".join([result.get("reply", "")] + [c.get("text", "") for c in result.get("claims", [])])
    missing = [f for f in q.key_facts if not has_fact(answer_text, f)]

    if q.category == "false_premise":
        if status == "premise_false":
            return Grade("refused_correctly", "challenged the premise", missing, gold_cited)
        if status in REFUSAL_STATUSES and gold_cited:
            return Grade("refused_correctly", "refused, citing the contradicting page", missing, gold_cited)
        if status in REFUSAL_STATUSES:
            # P5: a refusal that never challenges the premise is not the correct behaviour.
            return Grade("wrong", "refused without challenging the premise", missing, gold_cited)
        return Grade("wrong", "answered as if the premise were true", missing, gold_cited)

    if not q.answerable:
        if status in REFUSAL_STATUSES:
            return Grade("refused_correctly", f"refused ({status})", [], gold_cited)
        return Grade("wrong", "answered a question the papers don't answer", [], gold_cited)

    if status in REFUSAL_STATUSES:
        return Grade("refused_wrongly", f"refused an answerable question ({status})", missing, gold_cited)
    if missing:
        return Grade("wrong", f"missing key facts: {missing}", missing, gold_cited)
    if not gold_cited:
        return Grade("wrong", "key facts present but no citation to a gold page", missing, gold_cited)
    return Grade("correct", "all key facts, gold page cited", missing, gold_cited)
