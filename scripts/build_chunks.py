"""Build the chunk index for one chunking setting, plus a sample for reading by eye.

Usage: uv run python scripts/build_chunks.py --target 256 --overlap 32

Writes:
  index/chunks-t<target>-o<overlap>.jsonl   one chunk per line (gitignored: it's paper text)
  index/sample-t<target>-o<overlap>.md      12 seeded random chunks, to read before trusting
"""

import argparse
import json
import random
import statistics
from collections import Counter

from relay.chunking import chunk_paragraphs
from relay.config import PROJECT_ROOT
from relay.ingest import extract_paragraphs
from relay.papers import PAPERS
from relay.retrieval import PASSAGE_LIMIT_WORDPIECES, wordpieces


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, required=True)
    ap.add_argument("--overlap", type=int, default=32)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    chunks = []
    for paper in PAPERS:
        paras = extract_paragraphs(paper)
        chunks.extend(chunk_paragraphs(paras, args.target, args.overlap,
                                       model_len=wordpieces, model_limit=PASSAGE_LIMIT_WORDPIECES))
    # Guarantee, not hope: refuse to write an index the models would silently truncate.
    over = [c.chunk_id for c in chunks if wordpieces(c.search_text) > PASSAGE_LIMIT_WORDPIECES]
    if over:
        raise SystemExit(f"{len(over)} chunks exceed {PASSAGE_LIMIT_WORDPIECES} word pieces: {over[:5]}")
    # Global, stable ids.
    for i, c in enumerate(chunks):
        c.chunk_id = f"{c.paper}-t{args.target}-{i:04d}"

    out_dir = PROJECT_ROOT / "index"
    out_dir.mkdir(exist_ok=True)
    name = f"t{args.target}-o{args.overlap}"
    with (out_dir / f"chunks-{name}.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")

    sizes = [c.n_tokens for c in chunks]
    print(f"setting {name}: {len(chunks)} chunks, {sum(sizes):,} tokens total")
    print(f"  per paper: {dict(Counter(c.paper for c in chunks))}")
    print(f"  tokens/chunk: median {statistics.median(sizes)}, min {min(sizes)}, max {max(sizes)}")
    print(f"  chunks < 25% of target: {sum(s < args.target / 4 for s in sizes)}")
    print(f"  chunks containing a table: {sum(c.has_table for c in chunks)}")
    wp = [wordpieces(c.search_text) for c in chunks]
    print(f"  model word pieces (stricter tokenizer): max {max(wp)} <= limit {PASSAGE_LIMIT_WORDPIECES}")

    rng = random.Random(args.seed)
    sample = rng.sample(chunks, min(12, len(chunks)))
    lines = [f"# Chunk sample, setting {name} (seed {args.seed})\n"]
    for c in sample:
        lines.append(f"## {c.chunk_id} {c.citation} {c.section} ({c.kind}, {c.n_tokens} tok)\n\n```\n{c.text}\n```\n")
    (out_dir / f"sample-{name}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  sample: index/sample-{name}.md")


if __name__ == "__main__":
    main()
