"""M2: benchmark validation rules (synthetic questions; no real benchmark needed)."""

from relay.benchmark import Evidence, Question, validate

PAGES = {("attention", 8): "the big transformer model achieves 28.4 bleu on en-de"}
COUNTS = {"attention": 15, "moshi": 66, "hnet": 39}


def q(**kw):
    base = dict(id="q1", question="What BLEU?", category="number_text", answerable=True, answer="28.4",
                key_facts=["28.4"], evidence=[Evidence("attention", [8])])
    base.update(kw)
    return Question(**base)


def test_valid_question_passes():
    assert validate([q()], PAGES, COUNTS) == ([], [])


def test_key_fact_missing_from_gold_page_warns():
    _, warnings = validate([q(key_facts=["41.8"])], PAGES, COUNTS)
    assert any("41.8" in w for w in warnings)


def test_page_out_of_range_is_error():
    errors, _ = validate([q(evidence=[Evidence("attention", [99])])], PAGES, COUNTS)
    assert any("no page 99" in e for e in errors)


def test_unanswerable_with_evidence_is_error():
    bad = q(category="unanswerable_near_miss", answerable=False, evidence=[Evidence("attention", [8])])
    errors, _ = validate([bad], PAGES, COUNTS)
    assert errors


def test_unanswerable_category_marked_answerable_is_error():
    errors, _ = validate([q(category="unanswerable_off_topic")], PAGES, COUNTS)
    assert any("answerable: true" in e for e in errors)


def test_duplicate_ids_and_unknown_category():
    errors, _ = validate([q(), q(category="trivia")], PAGES, COUNTS)
    assert any("duplicate" in e for e in errors) and any("unknown category" in e for e in errors)


def test_false_premise_may_be_refused_without_evidence():
    fp = q(category="false_premise", answerable=False, evidence=[], key_facts=[])
    assert validate([fp], PAGES, COUNTS) == ([], [])


def test_false_premise_with_contradicting_evidence_is_checked():
    # e.g. "Why did the big model score 30 BLEU?" -> evidence: p.8 says 28.4
    fp = q(category="false_premise", answerable=False, key_facts=["28.4"])
    assert validate([fp], PAGES, COUNTS) == ([], [])
    _, warnings = validate([q(category="false_premise", answerable=False, key_facts=["99.9"])], PAGES, COUNTS)
    assert any("99.9" in w for w in warnings)


def test_false_premise_cannot_be_marked_answerable():
    errors, _ = validate([q(category="false_premise", answerable=True)], PAGES, COUNTS)
    assert any("challenged" in e for e in errors)
