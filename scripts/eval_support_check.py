"""Score the local support check (src/relay/support.py) against Archi's hand labels.

Test set: the 20 claims of the frozen pipeline's run 4, labelled supported yes/no by Archi in
results/review/hand-review-run4-archi.md (read from that file, not retyped).
Caveat printed with the result: 20 claims, and the rule was designed with this run in view,
so these numbers are optimistic for new questions.

Usage: uv run python scripts/eval_support_check.py [--sweep]
"""

import json
import re
import sys

from relay.config import PROJECT_ROOT
from relay.support import MIN_COVERAGE, check

RUN = PROJECT_ROOT / "results" / "answers" / "answers-gpt-oss-20b-t384-o32-hybrid-20261112T124111Z.jsonl"
LABELS = PROJECT_ROOT / "results" / "review" / "hand-review-run4-archi.md"


def labels() -> dict[str, list[bool]]:
    out = {}
    for line in LABELS.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| (Q\d\d) \| [^|]+ \| ([^|]+) \|", line)
        if m and re.fullmatch(r"(yes|no)(, (yes|no))*", m.group(2).strip()):
            out[m.group(1)] = [x.strip() == "yes" for x in m.group(2).split(",")]
    return out


def rows():
    lab = labels()
    for line in RUN.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["question_id"] in lab:
            assert len(lab[r["question_id"]]) == len(r["claims"]), r["question_id"]
            for c, human in zip(r["claims"], lab[r["question_id"]]):
                yield r["question_id"], c["text"], c["quote"], human


def score(threshold: float, verbose: bool = False) -> dict:
    tp = fp = tn = fn = 0  # positive = rule flags the claim as UNSUPPORTED
    for qid, claim, quote, human_ok in rows():
        ok, cov, missing = check(claim, quote, threshold)
        if not human_ok and not ok:
            tp += 1
        elif human_ok and not ok:
            fp += 1
        elif human_ok and ok:
            tn += 1
        else:
            fn += 1
        if verbose:
            verdict = "agree" if ok == human_ok else ("MISSED" if not human_ok else "WRONGLY DROPPED")
            print(f"{qid} human={'yes' if human_ok else 'no '} rule={'yes' if ok else 'no '} cov={cov:.2f} "
                  f"{verdict:<15} missing={missing[:6]}")
    return {"threshold": threshold, "caught": tp, "of_unsupported": tp + fn, "wrongly_dropped": fp,
            "of_supported": fp + tn}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    s = score(MIN_COVERAGE, verbose=True)
    print(f"\nRule (coverage >= {MIN_COVERAGE}, numbers must match): caught {s['caught']} of {s['of_unsupported']} "
          f"unsupported claims; wrongly dropped {s['wrongly_dropped']} of {s['of_supported']} supported claims.")
    if "--sweep" in sys.argv:
        print("\nthreshold sweep (for transparency; choosing from this would fit the 20 claims):")
        for t in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
            x = score(t)
            print(f"  {t:.1f}: caught {x['caught']}/{x['of_unsupported']}, wrongly dropped "
                  f"{x['wrongly_dropped']}/{x['of_supported']}")
    print("\nCaveat: 20 hand-labelled claims from one run; the rule was designed with this run in view.")


if __name__ == "__main__":
    main()
