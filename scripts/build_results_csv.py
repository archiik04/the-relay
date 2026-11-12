"""Build results/results.csv: one row per request, from the raw run logs.

Inputs:
  - every load run in results/load/*.jsonl (smoke tests live in results/load/smoke/ and are skipped);
  - every Groq probe in results/probe/*.jsonl (scenario "probe-<phase>"), so Table 1 is computable too;
  - the benchmark runs named with --table3 (the retrieval settings compared in Table 3).
    Their scenario is "retrieval-<mode>", source "real".

Usage:
  uv run python scripts/build_results_csv.py --table3 results/answers/<hybrid run>.jsonl [<bm25 run> <dense run>]
"""

import argparse
import csv
import glob
import json
from pathlib import Path

from relay.config import get_settings
from relay.results import COLUMNS, probe_row, to_row


def main(args) -> None:
    root = get_settings().results_dir
    rows = []
    for path in sorted(glob.glob(str(root / "load" / "*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            rows.append(to_row(json.loads(line)))
    # Real-service probes (Table 1). Summary lines (e.g. recovery_summary) are not requests.
    for path in sorted(glob.glob(str(root / "probe" / "*.jsonl"))):
        stem = Path(path).stem
        for i, line in enumerate(open(path, encoding="utf-8")):
            rec = json.loads(line)
            if "status" in rec and "total_ms" in rec:
                rows.append(probe_row(rec, f"{stem}-{i:03d}"))
    for path in args.table3:
        stem = Path(path).stem
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            mode = r["retrieval_setting"].split("|")[1]
            r.update({"request_id": f"{stem}-{r['question_id']}", "scenario": f"retrieval-{mode}", "source": "real"})
            rows.append(to_row(r))
    out = root / "results.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"{out}: {len(rows)} rows")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--table3", nargs="*", default=[])
    main(p.parse_args())
