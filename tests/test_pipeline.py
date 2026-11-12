"""M4: the pipeline's steps, checks and grading, with a scripted fake model (no API calls)."""

import asyncio
import json
import time
from dataclasses import dataclass

import pytest

from relay.benchmark import Evidence, Question
from relay.chunking import Chunk
from relay.grader import grade, has_fact
from relay.llm import ModelRequest, ModelResponse
from relay.pipeline import Pipeline, check_draft, understand


def chunk(cid, paper, text, page=5):
    return Chunk(cid, paper, "3 Model", "body", page, page, text, 10, False)


CHUNKS = [
    chunk("attention-0001", "attention", "The Transformer is based solely on attention mechanisms, dispensing with "
          "recurrence and convolutions entirely.", page=1),
    chunk("moshi-0010", "moshi", "The Depth Transformer has 16 heads and 6 layers in our configuration.", page=8),
    chunk("hnet-0020", "hnet", "The routing module uses cosine similarity between adjacent encoder outputs.", page=6),
]


@dataclass
class _Hit:
    chunk: Chunk
    cosine: float = 0.8
    bm25: float = 10.0


@dataclass
class _Result:
    hits: list


class FakeSearch:
    def __init__(self, delay_s: float = 0.0):
        self.calls: list[tuple[str, str | None]] = []
        self.delay_s = delay_s

    def search(self, query, paper=None):
        self.calls.append((query, paper))
        time.sleep(self.delay_s)
        return _Result([_Hit(c) for c in CHUNKS if paper in (None, c.paper)])


class FakeModel:
    """Returns scripted replies in order; each reply is a dict (sent as JSON), a str, or a ModelResponse."""

    name = "fake"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[ModelRequest] = []

    async def complete(self, req):
        self.requests.append(req)
        r = self.replies.pop(0)
        if isinstance(r, ModelResponse):
            return r
        t = time.perf_counter()
        await asyncio.sleep(0.001)
        return ModelResponse(status="ok", text=r if isinstance(r, str) else json.dumps(r), t_start=t,
                             t_first_token=t + 0.0005, t_last_token=time.perf_counter(), t_end=time.perf_counter(),
                             prompt_tokens=100, completion_tokens=50, finish_reason="stop")


GOOD = {"status": "answered", "answer": "The Depth Transformer has 16 heads and 6 layers.",
        "claims": [{"text": "16 heads and 6 layers", "chunk_id": "moshi-0010",
                    "quote": "The Depth Transformer has 16 heads and 6 layers"}], "not_covered": None}
FAKE_QUOTE = {**GOOD, "claims": [{"text": "x", "chunk_id": "moshi-0010", "quote": "The Depth Transformer has 32 heads"}]}


def run(pipeline, q="How many heads does the Moshi Depth Transformer have?"):
    return asyncio.run(pipeline.run(q))


# ---------------------------------------------------------------- step 1


@pytest.mark.parametrize("q, named, comparison", [
    ("How many layers does the Moshi Depth Transformer use?", ["moshi"], False),  # not the Attention paper
    ("How does the Transformer represent token positions?", ["attention"], False),
    ("How does the Transformer differ from H-Net's chunking?", ["attention", "hnet"], True),
    ("What are the three criteria for comparing layer types?", [], False),
])
def test_understand(q, named, comparison):
    plan = understand(q)
    assert plan.papers_named == named and plan.comparison == comparison


# ---------------------------------------------------------------- step 5


def test_check_accepts_verbatim_quote_modulo_spacing_and_case():
    d = {**GOOD, "claims": [{"text": "x", "chunk_id": "moshi-0010", "quote": "the depth  Transformer has 16 heads"}]}
    assert check_draft(d, {c.chunk_id: c for c in CHUNKS}) == []


@pytest.mark.parametrize("draft, problem", [
    (FAKE_QUOTE, "does not appear word for word"),
    ({**GOOD, "claims": [{"text": "x", "chunk_id": "moshi-9999", "quote": "The Depth Transformer has 16"}]}, "not one of"),
    ({**GOOD, "claims": [{"text": "x", "chunk_id": "moshi-0010", "quote": "16 heads"}]}, "shorter than"),
    ({**GOOD, "claims": []}, "needs at least one quoted claim"),
    ({**GOOD, "status": "maybe"}, "status must be"),
    (None, "not a JSON object"),
])
def test_check_rejects(draft, problem):
    problems = check_draft(draft, {c.chunk_id: c for c in CHUNKS})
    assert any(problem in p for p in problems), problems


def test_check_forgives_non_breaking_hyphens_and_maths_spacing():
    c = chunk("hnet-0001", "hnet", "a two-speaker setup where 𝑏𝑡= 1 are retained in the sequence")
    d = {**GOOD, "claims": [{"text": "x", "chunk_id": "hnet-0001", "quote": "a two‑speaker setup where 𝑏𝑡 = 1 are retained"}]}
    assert check_draft(d, {"hnet-0001": c}) == []


def test_check_still_rejects_reordered_or_changed_words():
    c = chunk("hnet-0001", "hnet", "vectors where b = 1 are retained in the sequence")
    for quote in ("vectors where b = 0 are retained", "where vectors b = 1 are retained"):
        d = {**GOOD, "claims": [{"text": "x", "chunk_id": "hnet-0001", "quote": quote}]}
        assert check_draft(d, {"hnet-0001": c}), quote


def test_wrong_chunk_id_is_repointed_when_quote_is_elsewhere():
    model = FakeModel({**GOOD, "claims": [{"text": "x", "chunk_id": "hnet-0020",
                                           "quote": "The Depth Transformer has 16 heads and 6 layers"}]})
    res = run(Pipeline(model, FakeSearch()))
    assert res.final_status == "answered" and res.citations_fixed == 1 and res.redrafts == 0
    assert res.claims[0]["chunk_id"] == "moshi-0010" and res.citations == ["[moshi p.8]"]


def test_not_in_papers_needs_no_claims():
    assert check_draft({"status": "not_in_papers", "answer": "The papers don't say.", "claims": []}, {}) == []


# ---------------------------------------------------------------- the pipeline


def test_good_draft_is_answered_with_citations_from_chunk_metadata():
    res = run(Pipeline(FakeModel(GOOD), FakeSearch()))
    assert res.final_status == "answered" and res.redrafts == 0 and res.model_calls == 1
    assert res.citations == ["[moshi p.8]"] and res.reply == "16 heads and 6 layers [moshi p.8]"


def test_reply_contains_only_claim_text_never_free_text():
    draft = {**GOOD, "answer": "UNCLAIMED: it also outputs silence for its own stream."}
    res = run(Pipeline(FakeModel(draft), FakeSearch()))
    assert "UNCLAIMED" not in res.reply and res.reply.startswith("16 heads and 6 layers")


def test_refusal_and_premise_replies():
    res = run(Pipeline(FakeModel({"status": "not_in_papers", "claims": []}), FakeSearch()))
    assert res.reply.startswith("The three papers don't say this")
    pf = {"status": "premise_false", "claims": [{"text": "The Transformer uses no convolutions.", "chunk_id": "attention-0001",
                                                  "quote": "dispensing with recurrence and convolutions entirely"}]}
    res = run(Pipeline(FakeModel(pf), FakeSearch()))
    assert res.reply == "That premise doesn't match the papers. The Transformer uses no convolutions. [attention p.1]"


def test_failed_check_redrafts_once_then_passes():
    model = FakeModel(FAKE_QUOTE, GOOD)
    res = run(Pipeline(model, FakeSearch()))
    assert res.final_status == "answered" and res.redrafts == 1 and res.model_calls == 2
    assert "failed these checks" in model.requests[1].messages[-1]["content"]


def test_two_failed_checks_refuse_never_send_unverified():
    res = run(Pipeline(FakeModel(FAKE_QUOTE, "not json"), FakeSearch()))
    assert res.final_status == "unverified" and res.claims == [] and "won't guess" in res.reply


def test_comparison_searches_each_paper_separately():
    search = FakeSearch()
    model = FakeModel({"status": "not_in_papers", "answer": "The papers don't say.", "claims": []})
    run(Pipeline(model, search), "How does the Transformer differ from H-Net?")
    assert [p for _, p in search.calls] == ["attention", "hnet"]
    prompt = model.requests[0].messages[1]["content"]
    assert "[attention-0001]" in prompt and "[hnet-0020]" in prompt and "[moshi-0010]" not in prompt


def test_search_timeout_retries_once_then_reports():
    search = FakeSearch(delay_s=0.2)
    res = run(Pipeline(FakeModel(), search, search_timeout_s=0.05))
    assert res.final_status == "search_failed" and len(search.calls) == 2 and res.model_calls == 0


def test_rate_limited_model_is_reported_not_answered():
    limited = ModelResponse(status="rate_limited", retry_after_s=3.0, error="429")
    res = run(Pipeline(FakeModel(limited), FakeSearch()))
    assert res.final_status == "model_rate_limited" and res.retry_after_s == 3.0


def test_provider_json_rejection_redrafts_once_without_json_mode():
    rejected = ModelResponse(status="error", error_code="json_validate_failed", error="json_validate_failed")
    model = FakeModel(rejected, GOOD)
    res = run(Pipeline(model, FakeSearch()))
    assert res.final_status == "answered" and res.redrafts == 1
    assert model.requests[0].json_mode is True and model.requests[1].json_mode is False


def test_timestamps_are_ordered():
    res = run(Pipeline(FakeModel(FAKE_QUOTE, GOOD), FakeSearch()))
    assert 0 < res.model_first_token_ms <= res.model_last_token_ms <= res.first_token_ms <= res.total_ms


def test_reply_is_sent_only_after_the_check():
    sent: list[str] = []

    async def send(text):
        sent.append(text)

    asyncio.run(Pipeline(FakeModel(FAKE_QUOTE, GOOD), FakeSearch()).run("Moshi heads?", send))
    assert len(sent) == 1 and "16 heads" in sent[0]


# ---------------------------------------------------------------- grading


def q(category, answerable=True, facts=("16", "6"), pages=((("moshi", 8)),)):
    ev = [Evidence(p, [pg]) for p, pg in pages]
    return Question("QX", "?", category, answerable, "", list(facts), ev)


def result(status, reply="", claims=(), retrieved=(("moshi-0010", "[moshi p.8]"),)):
    return {"final_status": status, "reply": reply, "claims": list(claims),
            "retrieved": [{"chunk_id": c, "citation": cit} for c, cit in retrieved]}


@pytest.mark.parametrize("text, fact, ok", [
    ("16 heads and 6 layers", "6", True), ("16 heads", "6", False), ("64 dims", "6", False),
    ("6.5 points", "6", False), ("it has 6.", "6", True), ("the key value", "key", True), ("keys", "key", False),
    ("sinusoidal encodings", "sine | sinusoidal", True), ("sinusoidal encodings", "sine", False),
    ("a two‑speaker setup", "two-speaker", True),
])
def test_whole_word_fact_matching(text, fact, ok):
    assert has_fact(text, fact) is ok


def test_grades():
    claim = [{"text": "16 heads, 6 layers", "chunk_id": "moshi-0010"}]
    assert grade(q("number_table"), result("answered", "16 heads and 6 layers", claim)).grade == "correct"
    only_heads = [{"text": "16 heads", "chunk_id": "moshi-0010"}]
    assert grade(q("number_table"), result("answered", "16 heads", only_heads)).grade == "wrong"
    assert grade(q("number_table"), result("answered", "16 heads, 6 layers", [])).grade == "wrong"  # no gold citation
    assert grade(q("number_table"), result("not_in_papers")).grade == "refused_wrongly"
    assert grade(q("unanswerable_near_miss", False, ()), result("not_in_papers")).grade == "refused_correctly"
    assert grade(q("unanswerable_near_miss", False, ()), result("answered", "x")).grade == "wrong"
    assert grade(q("false_premise", False, ()), result("premise_false")).grade == "refused_correctly"
    assert grade(q("false_premise", False, ()), result("not_in_papers")).grade == "wrong"
    assert grade(q("number_table"), result("model_rate_limited")).grade is None
