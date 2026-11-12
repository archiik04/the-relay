"""Write a hand-review sheet for one benchmark run (P1: semantic support is labelled by hand).

Usage: uv run python scripts/make_review_sheet.py results/answers/<run>.jsonl

For every answer it lists the reply, the grader's verdict, and each claim with its quote.
Archi fills in two things:
  - per claim: supported by its quote? yes / no
  - per answer: do you agree with the grade? If not, why (a logged grader fix, P5)
"""

import json
import sys
from pathlib import Path

from relay.benchmark import load


def main(path: str) -> None:
    qs = {q.id: q for q in load()}
    src = Path(path)
    out = src.parent.parent / "review" / f"review-{src.stem}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Hand review: {src.name}", "",
             "Fill in **supported?** (yes/no) for every claim, and **agree with grade?** for every answer.",
             "A claim is supported only if its quote directly states it (P1).", ""]
    for line in src.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        q = qs[r["question_id"]]
        lines += [f"## {r['question_id']} ({r['category']}): grade `{r['grade']}`",
                  f"**Q:** {q.question}", "",
                  f"**Reference answer:** {q.answer}", "",
                  f"**Status:** {r['final_status']} · grader: {r['grade_reason']}", "",
                  "**Reply:**", "", "> " + r["reply"].replace("\n", "\n> "), ""]
        if r["claims"]:
            lines += ["| # | Claim | Quote (verbatim, checked) | Source | Supported? |", "|---|---|---|---|---|"]
            cit = {x["chunk_id"]: x["citation"] for x in r["retrieved"]}
            for i, c in enumerate(r["claims"], 1):
                cell = lambda s: (s or "").replace("|", "\|").replace("\n", " ")  # noqa: E731
                lines.append(f"| {i} | {cell(c.get('text'))} | {cell(c.get('quote'))} | {cit.get(c.get('chunk_id'), '?')} | |")
            lines.append("")
        lines += ["**Agree with grade?** ", "", "---", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main(sys.argv[1])
