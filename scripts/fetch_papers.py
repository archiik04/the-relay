"""Fetch the three papers at their pinned arXiv versions and record a manifest.

Usage:  uv run python scripts/fetch_papers.py [--force]

For each paper it:
  1. downloads https://arxiv.org/pdf/<id>v<version> (skipped if the file is
     already there and its hash matches the manifest, so re-runs don't hit arXiv),
  2. checks the bytes are a PDF,
  3. checks page 1 carries arXiv's own stamp for that exact version
     (e.g. "arXiv:1706.03762v7"); this is the evidence that we have the right version,
  4. writes papers/manifest.json with sha256, size, page count and fetch time.

Exits non-zero if any check fails.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone

import pymupdf
import httpx

from relay.config import get_settings
from relay.papers import PAPERS, Paper, has_version_stamp

USER_AGENT = "the-relay-assignment/0.1 (paper fetch script)"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def version_stamp_found(pdf_bytes: bytes, paper: Paper) -> bool:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        first_page = doc[0].get_text()
    return has_version_stamp(first_page, paper)


def page_count(pdf_bytes: bytes) -> int:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return doc.page_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-download even if hashes match")
    args = parser.parse_args()

    settings = get_settings()
    papers_dir = settings.papers_dir
    papers_dir.mkdir(exist_ok=True)
    manifest_path = papers_dir / "manifest.json"
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    manifest: dict[str, dict] = {}
    ok = True
    with httpx.Client(follow_redirects=True, timeout=60, headers={"User-Agent": USER_AGENT}) as client:
        for paper in PAPERS:
            path = papers_dir / paper.filename
            prev = old.get(paper.key)
            if path.exists() and prev and not args.force and sha256(path.read_bytes()) == prev["sha256"]:
                data = path.read_bytes()
                fetched_at = prev["fetched_at"]
                print(f"[{paper.key}] cached, hash matches manifest")
            else:
                print(f"[{paper.key}] GET {paper.pdf_url}")
                resp = client.get(paper.pdf_url)
                resp.raise_for_status()
                data = resp.content
                path.write_bytes(data)
                fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

            is_pdf = data.startswith(b"%PDF")
            stamp = is_pdf and version_stamp_found(data, paper)
            if not is_pdf:
                print(f"[{paper.key}] FAIL: response is not a PDF")
            elif not stamp:
                print(f"[{paper.key}] FAIL: page 1 lacks 'arXiv:{paper.versioned_id}' stamp")
            ok &= stamp

            manifest[paper.key] = {
                "title": paper.title,
                "arxiv_id": paper.arxiv_id,
                "version": paper.version,
                "url": paper.pdf_url,
                "file": paper.filename,
                "sha256": sha256(data),
                "bytes": len(data),
                "pages": page_count(data) if is_pdf else None,
                "version_stamp_found": stamp,
                "fetched_at": fetched_at,
            }
            print(f"[{paper.key}] {len(data):,} bytes, {manifest[paper.key]['pages']} pages, stamp={stamp}")

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {manifest_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
