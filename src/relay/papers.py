"""The library: exactly three papers, at exactly the versions the brief names.

This registry is the single place paper identity lives. Ingestion, citations
and the fetch script all read from it, so a version can't drift in one place
and not another.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Paper:
    key: str  # short id used in citations, e.g. [attention p.5]
    arxiv_id: str
    version: int
    title: str

    @property
    def versioned_id(self) -> str:
        return f"{self.arxiv_id}v{self.version}"

    @property
    def pdf_url(self) -> str:
        return f"https://arxiv.org/pdf/{self.versioned_id}"

    @property
    def filename(self) -> str:
        return f"{self.versioned_id}.pdf"


PAPERS: tuple[Paper, ...] = (
    Paper("attention", "1706.03762", 7, "Attention Is All You Need"),
    Paper("moshi", "2410.00037", 1, "Moshi: a speech-text foundation model for real-time dialogue"),
    Paper("hnet", "2507.07955", 2, "Dynamic Chunking for End-to-End Hierarchical Sequence Modeling"),
)

PAPERS_BY_KEY = {p.key: p for p in PAPERS}


def has_version_stamp(page_text: str, paper: Paper) -> bool:
    """True if arXiv's margin stamp for exactly this version is in the text.

    A plain substring test is wrong: "arXiv:2410.00037v1" is a substring of
    "arXiv:2410.00037v10", so a v10 PDF would pass a v1 check. The (?!\\d)
    lookahead requires the version number to end where we expect.
    """
    pattern = rf"arXiv:{re.escape(paper.arxiv_id)}v{paper.version}(?!\d)"
    return re.search(pattern, page_text) is not None
