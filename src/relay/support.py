"""A cheap local support check: does a claim say more than its own quote? (no model call)

The verbatim check proves a quote is genuine; it does not prove the claim follows from it.
Archi's hand review found 10 of 20 claims overstate their quote. This rule is the cheapest
possible second line of defence, measured against those hand labels
(scripts/eval_support_check.py), not deployed in the frozen pipeline.

Rule (fixed before scoring, one threshold):
  1. every number in the claim must appear in the quote (number words count: "six" = 6);
  2. at least MIN_COVERAGE of the claim's content words must appear in the quote,
     compared by a crude 5-letter stem ("averaging" ~ "average").
"""

import re

from relay.retrieval import STOPWORDS

MIN_COVERAGE = 0.6
EXTRA_STOP = frozenset("also into such using used uses use both each more most other only same than very well".split())
NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
NUM = re.compile(r"\d+(?:\.\d+)?")
WORD = re.compile(r"[a-z][a-z\-]+")


def _norm(s: str) -> str:
    s = s.replace("‑", "-").replace("‐", "-").lower()
    return re.sub(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", lambda m: NUMBER_WORDS[m.group(1)], s)


def _stems(s: str) -> set[str]:
    words = (w for tok in WORD.findall(s) for w in tok.split("-"))
    return {w[:5] for w in words if len(w) >= 4 and w not in STOPWORDS and w not in EXTRA_STOP}


def check(claim: str, quote: str, min_coverage: float = MIN_COVERAGE) -> tuple[bool, float, list[str]]:
    """(supported?, share of the claim's content words found in the quote, what is missing)."""
    c, q = _norm(claim), _norm(quote)
    missing_numbers = [n for n in NUM.findall(c) if not re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", q)]
    cs, qs = _stems(c), _stems(q)
    coverage = len(cs & qs) / len(cs) if cs else 1.0
    missing = missing_numbers + sorted(cs - qs)
    return (not missing_numbers and coverage >= min_coverage), round(coverage, 3), missing
