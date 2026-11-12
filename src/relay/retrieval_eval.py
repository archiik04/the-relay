"""Retrieval-only evaluation: no LLM, no quota.

Question groups are reported separately and never pooled (Archi's requirement):
  answerable  - recall@k / full recall / MRR against the gold pages
  near_miss   - on-topic, but the papers don't say it
  off_topic   - outside the papers
  false_premise
For the refusal groups, recall is meaningless; what matters is how their evidence
signals (best rerank score / cosine / BM25) compare with the answerable group's.
That comparison is what sets the "enough evidence?" threshold.
"""

from dataclasses import dataclass

from relay.benchmark import Question
from relay.retrieval import RetrievalResult

GROUP_OF = {
    "unanswerable_near_miss": "near_miss",
    "unanswerable_off_topic": "off_topic",
    "false_premise": "false_premise",
}


def group(q: Question) -> str:
    return GROUP_OF.get(q.category, "answerable")


def _covers(hit_paper: str, page_start: int, page_end: int, paper: str, pages: list[int]) -> bool:
    return hit_paper == paper and any(page_start <= p <= page_end for p in pages)


@dataclass
class Coverage:
    any_hit: bool  # at least one gold page retrieved (recall@k)
    all_evidence: bool  # every evidence item covered (matters for multi_part)
    first_rank: int | None  # rank of the first covering hit (for MRR)


def coverage(q: Question, result: RetrievalResult) -> Coverage | None:
    """None for questions without gold evidence (refusal groups)."""
    if not q.evidence:
        return None
    first = None
    covered = [False] * len(q.evidence)
    for h in result.hits:
        c = h.chunk
        for j, ev in enumerate(q.evidence):
            if _covers(c.paper, c.page_start, c.page_end, ev.paper, ev.pages):
                covered[j] = True
                if first is None:
                    first = h.rank
    return Coverage(any_hit=first is not None, all_evidence=all(covered), first_rank=first)
