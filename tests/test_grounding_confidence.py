import pytest

import config
from agents.requirements_agent import check_requirement, plan_calls
from agents.schemas import AcceptanceCriterion, Requirement
from checks.confidence import combine, confidence_components, rescale_similarity
from checks.grounding import check_grounding, extract_numbers, normalise_number

CHUNKS = {
    "C1": {"text": "Loans above 50,000 need a human underwriter.", "document": "p.md",
           "position": 0, "similarity": 0.6},
    "C2": {"text": "Records are kept for 7 years.", "document": "p.md",
           "position": 1, "similarity": 0.2},
}


def req(statement="The system shall do x.", sources=(), confidence=0.8, **kw):
    return Requirement(id="FR-01", statement=statement, sources=list(sources),
                       model_confidence=confidence, **kw)


@pytest.mark.parametrize("text, expected", [
    ("50,000", "50000"), ("99.90", "99.9"), ("5.0", "5"), ("007", "7"), ("0", "0")])
def test_normalise_number(text, expected):
    assert normalise_number(text) == expected


def test_extract_numbers_ignores_ids_and_trivial_numbers():
    text = "FR-01 depends on NFR-12 and [C3]; limit 50,000 within 30-day window at 99.9% with 2FA, 1 user."
    assert extract_numbers(text) == {"50000", "30", "99.9"}


def test_citation_validation_removes_unknown_ids():
    result = check_grounding(req(sources=["C1", "C7"]), CHUNKS, "")
    assert result.valid_sources == ["C1"]
    assert result.invalid_sources == ["C7"]


def test_numbers_in_cited_chunk_or_input_are_grounded():
    r = req("The system shall refer loans above 50000 and respond in 3 seconds.", sources=["C1"])
    result = check_grounding(r, CHUNKS, "Respond in 3 seconds")
    assert result.grounded_numbers == ["3", "50000"]
    assert result.ungrounded_numbers == [] and result.uncited_numbers == []


def test_number_only_in_uncited_chunk_and_invented_number():
    r = req("The system shall keep records 7 years and lock after 4 failures.", sources=["C1"])
    result = check_grounding(r, CHUNKS, "")
    assert result.uncited_numbers == ["7"]
    assert result.ungrounded_numbers == ["4"]


def test_numbers_in_acceptance_criteria_are_checked():
    r = req(sources=["C1"], acceptance_criteria=[AcceptanceCriterion(
        given="a loan of 75,000", when="submitted", then="it is referred")])
    assert check_grounding(r, CHUNKS, "").ungrounded_numbers == ["75000"]


def test_rescale_similarity():
    low, high = config.RETRIEVAL_SIMILARITY_FLOOR, config.RETRIEVAL_SIMILARITY_CEIL
    assert rescale_similarity(low) == 0
    assert rescale_similarity(high) == 1
    assert rescale_similarity(low - 0.1) == 0 and rescale_similarity(high + 0.1) == 1
    assert rescale_similarity((low + high) / 2) == pytest.approx(0.5)


def test_claim_support_is_preferred_over_retrieval_score():
    grounding = check_grounding(req(sources=["C1"]), CHUNKS, "")
    with_support = confidence_components(0.8, grounding, CHUNKS, True, support={"C1": 0.1})
    without = confidence_components(0.8, grounding, CHUNKS, True)
    assert with_support["retrieval_similarity"] == 0.0              # 0.1 is below the floor
    assert without["retrieval_similarity"] == pytest.approx(rescale_similarity(0.6), abs=1e-3)


def test_weak_citation_is_flagged():
    r = check_requirement(req("The system shall refer loans above 50,000.", sources=["C1", "C2"]),
                          CHUNKS, "", support={"C1": 0.7, "C2": 0.05})
    weak = [f.detail for f in r.flags if f.type == "weak_citation"]
    assert len(weak) == 1 and weak[0].startswith("C2")


def test_confidence_components_without_document_skip_citation_and_similarity():
    grounding = check_grounding(req(), {}, "")
    components = confidence_components(0.8, grounding, {}, has_document=False)
    assert components == {"self_rating": 0.8, "number_grounding": 1.0}
    assert combine(components) == pytest.approx(0.9)


def test_confidence_with_document_but_no_citation_is_penalised():
    grounding = check_grounding(req(), CHUNKS, "")
    components = confidence_components(0.8, grounding, CHUNKS, has_document=True)
    assert components["citation_validity"] == 0.0


def test_check_requirement_good_requirement():
    r = check_requirement(req("The system shall refer loans above 50,000.", sources=["C1"]), CHUNKS, "")
    assert r.flags == []
    expected = (0.8 + rescale_similarity(0.6) + 1 + 1) / 4
    assert r.confidence == pytest.approx(expected, abs=1e-3)
    assert not r.needs_human_review


def test_check_requirement_flags_and_review():
    r = check_requirement(req("The system shall approve within 12 minutes.", sources=["C9"],
                              confidence=0.3), CHUNKS, "")
    types = {f.type for f in r.flags}
    assert types == {"invalid_citation", "missing_citation", "possible_hallucination", "low_confidence"}
    assert r.sources == []
    assert r.confidence < config.CONFIDENCE_REVIEW_THRESHOLD
    assert r.needs_human_review


def test_plan_calls_respects_counts_batch_size_and_limits(monkeypatch):
    monkeypatch.setattr(config, "REQUIREMENTS_BATCH_SIZE", 2)
    specs = plan_calls({"options": {"num_functional": 3, "num_non_functional": 99}})
    assert specs[0] == {"kind": "functional", "ids": ["FR-01", "FR-02"]}
    assert specs[1] == {"kind": "functional", "ids": ["FR-03"]}
    nfr_ids = [i for s in specs if s["kind"] == "non_functional" for i in s["ids"]]
    assert len(nfr_ids) == config.MAX_REQUIREMENTS_PER_KIND
