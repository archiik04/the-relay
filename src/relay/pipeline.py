"""The answer pipeline (decisions P1–P6).

    1. understand  (code)   which papers are named; is it a comparison?
    2. retrieve    (tool)   search_papers, with a timeout and one retry
    3. decide      (branch) one search, or one per paper for a comparison
    4. draft       (model)  one call; JSON with status + quoted claims
    5. check       (code)   cited chunks were retrieved, quotes are verbatim;
                            one redraft on failure (the loop), then refuse

What the check proves, and what it doesn't (Archi): it proves each quote is genuine
text from a retrieved chunk. It does NOT prove the claim follows from the quote.
Semantic support is measured by hand on the benchmark, not asserted here.

Citations shown to the user are built from chunk metadata by this code, never
written by the model, so a page number can't be invented.

Nothing is sent before the check passes (D1): `first_token_ms` is when the checked
reply starts going out; the model's own first and last tokens are recorded
separately (P4).
"""

import asyncio
import json
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Awaitable, Callable, Protocol

from relay.chunking import Chunk
from relay.llm import ModelClient, ModelRequest, ModelResponse
from relay.papers import PAPERS_BY_KEY

STATUSES = ("answered", "not_in_papers", "premise_false")
MIN_QUOTE_WORDS = 4  # shorter quotes ("the model") would match almost anywhere

# Names that point at one paper. "the transformer" (not "Depth Transformer") means the Attention paper.
PAPER_PATTERNS = {
    "attention": re.compile(r"attention is all you need|\bvaswani\b|\bthe transformer\b", re.I),
    "moshi": re.compile(r"\bmoshi\b|\bmimi\b|\bhelium\b", re.I),
    "hnet": re.compile(r"\bh-?net\b|dynamic chunking", re.I),
}

SYSTEM_PROMPT = """You answer questions about three research papers using ONLY the passages provided.

Reply with one JSON object and nothing else:
{
  "status": "answered" | "not_in_papers" | "premise_false",
  "claims": [{"text": "one sentence for the user", "chunk_id": "id of the passage", "quote": "exact words copied from that passage"}],
  "not_covered": "the part of the question the passages do not answer, or null"
}

The user sees ONLY the claim sentences, in order, each followed by its source. There is no other answer text,
so write each claim as a complete, readable sentence and order them so they answer the question.
Cover every part of the question that the passages support: write one claim per distinct point
(a list of three criteria is three claims; a two-part question needs claims for both parts).

Evidence rules:
- Each claim's quote must DIRECTLY state that claim. The quote must be copied character for character from
  the passage named by chunk_id, at least 4 words long.
- A number, capability, result or comparison counts as supported only if the quote itself states it.
  Do not infer, calculate or generalise beyond the quote. Do not use your own knowledge.
- If the passages do not support an answer, set "status": "not_in_papers" and leave "claims" empty. Never guess.
- If a passage contradicts an assumption in the question, set "status": "premise_false" and make the claims
  state what the papers actually say, quoting the contradicting passage. Do not answer as if it were true.
- If only part of the question is supported, answer that part and name the rest in "not_covered".
- For a question about two papers, quote each paper separately and put the two side by side.
  Do not add a judgement (better, more flexible, ...) that no quote states.
"""


# ---------------------------------------------------------------- step 1: understand


@dataclass
class Plan:
    papers_named: list[str]
    comparison: bool
    searches: list[tuple[str, str | None]]  # (query, paper filter)


def understand(question: str) -> Plan:
    named = [key for key, rx in PAPER_PATTERNS.items() if rx.search(question)]
    comparison = len(named) >= 2
    searches = [(question, p) for p in named] if comparison else [(question, None)]
    return Plan(papers_named=named, comparison=comparison, searches=searches)


# ---------------------------------------------------------------- step 2: the search tool


class SearchBackend(Protocol):
    def search(self, query: str, paper: str | None = None): ...


class SearchFailed(Exception):
    pass


async def search_papers(backend: SearchBackend, query: str, paper: str | None, timeout_s: float, retries: int = 1):
    """The retrieval tool. CPU-bound, so it runs in a thread; a timeout gets `retries` more tries."""
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            return await asyncio.wait_for(asyncio.to_thread(backend.search, query, paper), timeout_s)
        except (asyncio.TimeoutError, TimeoutError) as e:
            last = e
    raise SearchFailed(f"search timed out {retries + 1}x ({timeout_s}s each)") from last


# ---------------------------------------------------------------- step 5: check


_TYPOGRAPHY = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    # gpt-oss writes hyphens as U+2011 (non-breaking hyphen). Found in M4: genuine quotes
    # from the right chunk were rejected because of it.
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    "­": None,
})


def normalise(s: str) -> str:
    """Forgive what copying can't preserve, nothing else: typography, case and whitespace.

    Whitespace is removed, not collapsed: PDF extraction glues maths ("𝑏𝑡= 1") where the
    model writes spaces ("𝑏𝑡 = 1"). The quote must still be the same characters in the
    same order, at least MIN_QUOTE_WORDS words long.
    """
    s = unicodedata.normalize("NFKC", s).translate(_TYPOGRAPHY)
    return re.sub(r"\s+", "", s).casefold()


def fix_citations(draft: dict | None, chunks: dict[str, Chunk]) -> int:
    """Re-point a claim to the retrieved chunk that really contains its quote.

    Found in M4 (Q10): the model copied a genuine quote but named a neighbouring chunk,
    and repeated the same mistake when asked to redraft. If the quote is NOT in the cited
    chunk but IS in exactly one other retrieved chunk, cite that one: the quote is still
    verbatim, the citation becomes true, and no redraft (no extra model call) is needed.
    Returns how many claims were re-pointed.
    """
    if not draft or not isinstance(draft.get("claims"), list):
        return 0
    fixed = 0
    for c in draft["claims"]:
        if not isinstance(c, dict) or len((c.get("quote") or "").split()) < MIN_QUOTE_WORDS:
            continue
        q = normalise(c["quote"])
        cited = chunks.get(c.get("chunk_id"))
        if cited is not None and q in normalise(cited.text):
            continue
        holders = [cid for cid, ch in chunks.items() if q in normalise(ch.text)]
        if len(holders) == 1:
            c["chunk_id"] = holders[0]
            fixed += 1
    return fixed


def check_draft(draft: dict | None, chunks: dict[str, Chunk]) -> list[str]:
    """Return the problems with a draft; empty means it passes."""
    if draft is None:
        return ["the reply was not a JSON object"]
    problems: list[str] = []
    status = draft.get("status")
    if status not in STATUSES:
        return [f"status must be one of {STATUSES}, got {status!r}"]
    claims = draft.get("claims") or []
    if not isinstance(claims, list):
        return problems + ["'claims' must be a list"]
    if status in ("answered", "premise_false") and not claims:
        problems.append(f"status {status} needs at least one quoted claim")
    for i, c in enumerate(claims, start=1):
        if not isinstance(c, dict):
            problems.append(f"claim {i} is not an object")
            continue
        cid, quote = c.get("chunk_id"), c.get("quote") or ""
        if not isinstance(c.get("text"), str) or not c["text"].strip():
            problems.append(f"claim {i} has no text")
        if cid not in chunks:
            problems.append(f"claim {i} cites {cid!r}, which is not one of the passages provided")
            continue
        if len(quote.split()) < MIN_QUOTE_WORDS:
            problems.append(f"claim {i}: quote is shorter than {MIN_QUOTE_WORDS} words")
        elif normalise(quote) not in normalise(chunks[cid].text):
            problems.append(f"claim {i}: the quote does not appear word for word in {cid}")
    return problems


def parse_json(text: str) -> dict | None:
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


# ---------------------------------------------------------------- the pipeline


@dataclass
class PipelineResult:
    question: str
    final_status: str  # answered | not_in_papers | premise_false | unverified | search_failed | model_<status>
    reply: str
    citations: list[str]
    claims: list[dict]
    not_covered: str | None
    plan: dict
    retrieved: list[dict]
    model: str
    model_calls: int = 0
    redrafts: int = 0
    citations_fixed: int = 0  # claims re-pointed to the chunk that really holds the quote
    check_problems: list[list[str]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    reasoning_tokens: int = 0
    finish_reasons: list[str | None] = field(default_factory=list)
    model_queue_s: list[float | None] = field(default_factory=list)
    retrieval_ms: float = 0.0
    model_first_token_ms: float | None = None  # first model's first token (P4)
    model_last_token_ms: float | None = None  # last model call's last token
    first_token_ms: float | None = None  # checked reply starts going to the user
    total_ms: float = 0.0
    model_error: str | None = None
    retry_after_s: float | None = None
    queue_ms: float = 0.0  # waiting in the gateway queue (M5)
    retry_sleep_ms: float = 0.0  # sleeping before retries after a 429
    retries: int = 0
    queue_depth: int = 0  # gateway queue length when this request joined it
    degraded: bool = False  # passages-only reply because the daily budget is gone
    drafts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


Sender = Callable[[str], Awaitable[None]]

REFUSAL_UNVERIFIED = ("I couldn't produce an answer I could verify against the papers, "
                      "so I won't guess. Try rephrasing the question.")
REFUSAL_SEARCH = "The paper search is not responding right now, so I can't answer from the papers. Please try again shortly."
REFUSAL_MODEL = "The answering service is busy or unavailable right now, so I can't answer yet. Please try again shortly."


class Pipeline:
    def __init__(self, model: ModelClient, search: SearchBackend, *, max_tokens: int = 512,
                 reasoning_effort: str | None = "low", search_timeout_s: float = 5.0, max_redrafts: int = 1,
                 per_paper_k: int = 2):
        self.model = model
        self.search = search
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.search_timeout_s = search_timeout_s
        self.max_redrafts = max_redrafts
        self.per_paper_k = per_paper_k

    async def run(self, question: str, send: Sender | None = None) -> PipelineResult:
        t0 = time.perf_counter()

        def since(t: float | None) -> float | None:
            return None if t is None else round((t - t0) * 1000, 1)

        plan = understand(question)
        res = PipelineResult(question=question, final_status="", reply="", citations=[], claims=[],
                             not_covered=None, plan=asdict(plan), retrieved=[], model=self.model.name)

        # Steps 2-3: retrieve (branch: one search per paper for a comparison).
        s = time.perf_counter()
        try:
            hits = []
            for query, paper in plan.searches:
                r = await search_papers(self.search, query, paper, self.search_timeout_s)
                hits.extend(r.hits[: self.per_paper_k] if plan.comparison else r.hits)
        except SearchFailed as e:
            res.retrieval_ms = round((time.perf_counter() - s) * 1000, 1)
            return await self._finish(res, "search_failed", REFUSAL_SEARCH, t0, send, error=str(e))
        res.retrieval_ms = round((time.perf_counter() - s) * 1000, 1)
        chunks = {h.chunk.chunk_id: h.chunk for h in hits}
        res.retrieved = [{"chunk_id": h.chunk.chunk_id, "citation": h.chunk.citation, "section": h.chunk.section,
                          "cosine": h.cosine, "bm25": h.bm25} for h in hits]

        # Steps 4-5: draft, check, redraft once (the loop).
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _user_prompt(question, list(chunks.values()))}]
        draft = None
        json_mode = True
        for attempt in range(self.max_redrafts + 1):
            resp = await self.model.complete(ModelRequest(messages=list(messages), max_tokens=self.max_tokens,
                                                          reasoning_effort=self.reasoning_effort, json_mode=json_mode))
            self._account(res, resp, since)
            if resp.error_code == "json_validate_failed" and attempt < self.max_redrafts:
                # Found in M4 (Q03, repeatable): Groq's JSON mode rejected the output server-side and
                # returned nothing. Redraft once without it; our own parser and check still reject non-JSON.
                res.redrafts += 1
                res.check_problems.append(["provider rejected the output: json_validate_failed"])
                json_mode = False
                continue
            if resp.status != "ok":
                res.retry_after_s = resp.retry_after_s
                if resp.error_code == "daily_budget_exhausted":
                    # No model budget left today: give the passages, clearly labelled, never a guess.
                    res.degraded = True
                    return await self._finish(res, "degraded_passages", passages_only_reply(hits, resp.retry_after_s),
                                              t0, send, error=resp.error)
                if resp.error_code == "shed":
                    return await self._finish(res, "model_rate_limited", busy_reply(resp.retry_after_s), t0, send,
                                              error=resp.error)
                return await self._finish(res, f"model_{resp.status}", REFUSAL_MODEL, t0, send, error=resp.error)
            res.drafts.append(resp.text)
            draft = parse_json(resp.text)
            res.citations_fixed += fix_citations(draft, chunks)
            problems = check_draft(draft, chunks)
            if resp.finish_reason == "length":
                problems.insert(0, "the reply was cut off by the token limit; be shorter")
            res.check_problems.append(problems)
            if not problems:
                break
            if attempt < self.max_redrafts:
                res.redrafts += 1
                messages += [{"role": "assistant", "content": resp.text},
                             {"role": "user", "content": "Your reply failed these checks:\n- " + "\n- ".join(problems)
                              + "\nReturn a corrected JSON object. If the passages do not directly state the answer, "
                                "use status not_in_papers."}]
            draft = None

        if draft is None:
            return await self._finish(res, "unverified", REFUSAL_UNVERIFIED, t0, send)

        res.claims = draft.get("claims") or []
        res.not_covered = draft.get("not_covered") or None
        res.citations = list(dict.fromkeys(chunks[c["chunk_id"]].citation for c in res.claims))
        reply = compose_reply(draft["status"], res.claims, res.not_covered, chunks)
        return await self._finish(res, draft["status"], reply, t0, send)

    def _account(self, res: PipelineResult, resp: ModelResponse, since) -> None:
        res.queue_ms += resp.queue_ms
        res.retry_sleep_ms += resp.retry_sleep_ms
        res.retries += resp.retries
        res.queue_depth = max(res.queue_depth, resp.queue_depth)
        if resp.error_code in ("shed", "daily_budget_exhausted", "queue_deadline"):
            return  # the gateway answered locally: no model call was made
        res.model_calls += 1
        res.tokens_in += resp.prompt_tokens
        res.tokens_out += resp.completion_tokens
        res.reasoning_tokens += resp.reasoning_tokens
        res.finish_reasons.append(resp.finish_reason)
        res.model_queue_s.append(resp.queue_time_s)
        if res.model_first_token_ms is None:
            res.model_first_token_ms = since(resp.t_first_token)
        if resp.t_last_token is not None:
            res.model_last_token_ms = since(resp.t_last_token)

    async def _finish(self, res: PipelineResult, status: str, reply: str, t0: float, send: Sender | None,
                      error: str | None = None) -> PipelineResult:
        res.final_status, res.reply, res.model_error = status, reply, error or res.model_error
        res.first_token_ms = round((time.perf_counter() - t0) * 1000, 1)
        if send is not None:
            await send(reply)
        res.total_ms = round((time.perf_counter() - t0) * 1000, 1)
        return res


def passages_only_reply(hits, retry_after_s: float | None) -> str:
    """The last rung of the degradation ladder: no model call, no generated text, clearly labelled."""
    when = f" in about {round(retry_after_s / 60)} minutes" if retry_after_s and retry_after_s >= 60 else " later"
    lines = [f"[Limited answer] Today's answering budget is used up, so I can't write a checked answer now. "
             f"Full answers resume{when}. These are the most relevant passages I found; they may not answer "
             "your question:"]
    for h in hits[:3]:
        snippet = " ".join(h.chunk.text.split()[:45])
        lines.append(f"- {h.chunk.citation} {h.chunk.section}: \"{snippet}…\"")
    return "\n".join(lines)


def busy_reply(retry_after_s: float | None) -> str:
    wait = f"in about {max(1, round(retry_after_s))} seconds" if retry_after_s else "shortly"
    return f"Too many questions are waiting right now, so I'd rather say so than make you wait. Please try again {wait}."


NOT_IN_PAPERS = "The three papers don't say this, so I won't guess."
PREMISE_FALSE = "That premise doesn't match the papers."


def compose_reply(status: str, claims: list[dict], not_covered: str | None, chunks: dict[str, Chunk]) -> str:
    """The reply is built ONLY from checked claims (decision P7), each followed by its source.

    Run 2 showed the model putting sentences in a free-text answer that no claim backed.
    With no free text, every factual sentence the user sees has a verified quote behind it.
    `not_covered` is shown labelled as a gap, not as a claim.
    """
    parts: list[str] = []
    if status == "not_in_papers":
        parts.append(NOT_IN_PAPERS)
    elif status == "premise_false":
        parts.append(PREMISE_FALSE)
    for c in claims:
        text = c["text"].strip()
        parts.append(f"{text} {chunks[c['chunk_id']].citation}")
    reply = " ".join(parts)
    if not_covered and status == "answered":
        reply += f"\n\nThe papers don't cover: {not_covered.strip()}"
    return reply


def _user_prompt(question: str, chunks: list[Chunk]) -> str:
    parts = []
    for c in chunks:
        title = PAPERS_BY_KEY[c.paper].title
        parts.append(f"[{c.chunk_id}] {title} | {c.section} | {c.citation}\n{c.text}")
    return "Passages:\n\n" + "\n\n".join(parts) + f"\n\nQuestion: {question}"
