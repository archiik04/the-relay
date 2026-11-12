"""M0: the library is exactly the three papers, at exactly the brief's versions."""

import hashlib
import json

import pymupdf
import pytest

from relay.config import get_settings
from relay.papers import PAPERS, PAPERS_BY_KEY, has_version_stamp

PAPERS_DIR = get_settings().papers_dir
MANIFEST = PAPERS_DIR / "manifest.json"


def test_registry_matches_brief():
    # Copied from the assignment brief; if this fails, someone changed a version.
    assert {(p.arxiv_id, p.version) for p in PAPERS} == {
        ("1706.03762", 7),
        ("2410.00037", 1),
        ("2507.07955", 2),
    }


@pytest.fixture(scope="module")
def manifest():
    if not MANIFEST.exists():
        pytest.skip("run scripts/fetch_papers.py first")
    return json.loads(MANIFEST.read_text())


@pytest.mark.parametrize("paper", PAPERS, ids=lambda p: p.key)
def test_pdf_matches_manifest_hash(paper, manifest):
    path = PAPERS_DIR / paper.filename
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest[paper.key]["sha256"]


@pytest.mark.parametrize("paper", PAPERS, ids=lambda p: p.key)
def test_first_page_has_exact_version_stamp(paper):
    path = PAPERS_DIR / paper.filename
    if not path.exists():
        pytest.skip(f"{path.name} not fetched")
    with pymupdf.open(path) as doc:
        page1 = doc[0].get_text()
    assert has_version_stamp(page1, paper)


# The check itself must be able to fail. These feed it stamps from other
# versions; a check that accepted them would "verify" the wrong PDF.
STAMP = "arXiv:{id}v{v}  [cs.CL]  2 Aug 2023"


@pytest.mark.parametrize(
    "key, stamped_version, expected",
    [
        ("attention", 7, True),
        ("attention", 6, False),
        ("attention", 8, False),
        ("attention", 70, False),  # prefix trap: "v7" inside "v70"
        ("moshi", 1, True),
        ("moshi", 10, False),  # the real bug a substring check had
        ("moshi", 11, False),
        ("hnet", 2, True),
        ("hnet", 1, False),
        ("hnet", 20, False),
    ],
)
def test_stamp_check_rejects_other_versions(key, stamped_version, expected):
    paper = PAPERS_BY_KEY[key]
    text = STAMP.format(id=paper.arxiv_id, v=stamped_version)
    assert has_version_stamp(text, paper) is expected


def test_stamp_check_rejects_other_paper():
    moshi_text = STAMP.format(id="2410.00037", v=7)
    assert not has_version_stamp(moshi_text, PAPERS_BY_KEY["attention"])
