"""Phase 3: deterministic quality checks, the Quality and Compliance agents,
and the optional revision loop."""

import pytest

import config
from agents.compliance_agent import check_mapping, suggest_missing_controls
from agents.schemas import ComplianceMappingDraft
from checks import quality
from pipeline import run_pipeline
from tests.mock_llm import make_requirement


def req(rid, statement, **kw):
    return {**make_requirement(rid, statement=statement, **kw),
            "kind": "non_functional" if rid.startswith("NFR") else "functional"}


# ------------------------------------------------------- deterministic rules --
def issue_types(r):
    return [(i.type, i.severity) for i in quality.rule_issues(r)]


def test_vague_word_without_number():
    assert ("ambiguity", "Medium") in issue_types(req("FR-01", "The system shall respond fast."))


def test_vague_word_with_number_is_low():
    assert ("ambiguity", "Low") in issue_types(req("FR-01", "The system shall be fast, under 2 seconds."))


def test_vague_word_matching_is_whole_word():
    assert quality.find_vague_words("The steadfast system shall be easy-going") == []
    assert quality.find_vague_words("Supports PDF, DOCX, etc.") == ["etc"]


def test_unmeasurable_performance_nfr_is_high():
    r = req("NFR-01", "The system shall respond quickly.", categories=["performance"],
            acceptance_criteria=[{"given": "a user", "when": "they click", "then": "it responds"}])
    assert ("lack_of_testability", "High") in issue_types(r)


def test_measurable_nfr_has_no_testability_issue():
    r = req("NFR-01", "The system shall respond within 3 seconds.", categories=["performance"])
    assert "lack_of_testability" not in [t for t, _ in issue_types(r)]


def test_missing_actor_and_missing_shall():
    assert ("incompleteness", "Medium") in issue_types(req("FR-01", "Shall store applications."))
    assert ("ambiguity", "Medium") in issue_types(req("FR-01", "Applications are stored."))


def test_missing_source():
    r = req("FR-01", "The system shall store applications.", sources=[], source_stakeholder="")
    assert ("incompleteness", "Low") in issue_types(r)


def test_lexical_duplicates_and_embedding_duplicates():
    a = req("FR-01", "The system shall store every loan application securely.")
    b = req("FR-02", "The system shall securely store every loan application.")
    c = req("FR-03", "The system shall send a monthly statement.")
    assert quality.duplicates([a, b, c]) == [{"ids": ["FR-01", "FR-02"], "similarity": 1.0,
                                              "method": "lexical"}]
    matrix = [[1, 0.2, 0.95], [0.2, 1, 0.1], [0.95, 0.1, 1]]
    assert quality.duplicates([a, b, c], matrix)[0]["ids"] == ["FR-01", "FR-03"]


def test_numeric_conflict_on_same_subject():
    a = req("NFR-01", "The system shall lock the account after 3 failed login attempts.")
    b = req("NFR-02", "The system shall lock the account after 5 failed login attempts.")
    c = req("NFR-03", "The system shall archive statements after 5 years.")
    found = quality.conflicts([a, b, c])
    assert len(found) == 1 and found[0]["ids"] == ["NFR-01", "NFR-02"]
    assert "3 vs 5 attempt" in found[0]["detail"]


def test_shall_not_conflict():
    a = req("FR-01", "The system shall allow manual override of credit decisions.")
    b = req("FR-02", "The system shall not allow manual override of credit decisions.")
    assert any("shall not" in c["detail"] for c in quality.conflicts([a, b]))


# ------------------------------------------------------ compliance checks --
CHUNKS = {"KB-1": {"origin": "kb", "text": "Encrypt data at rest.", "title": "Std", "section": "Enc"},
          "C1": {"origin": "document", "text": "Loans."}}


def test_check_mapping_removes_invented_rules_and_flags_high_impact():
    draft = ComplianceMappingDraft(requirement_id="FR-01",
                                   applicable_rules=["KB-1", "Fictional Banking Act s.4"],
                                   evidence=["KB-1", "KB-9"], impact="Low")
    mapping = check_mapping(draft, {"risk_level": "Low", "categories": ["security"]}, CHUNKS)
    assert mapping.applicable_rules == ["KB-1"]
    assert mapping.evidence == ["KB-1"]
    assert {f.type for f in mapping.flags} == {"unsupported_rule", "invalid_citation"}
    assert mapping.requires_compliance_officer_approval      # security category = high impact
    assert mapping.approval_status == "pending"


def test_low_impact_mapping_without_rule():
    draft = ComplianceMappingDraft(requirement_id="FR-02", impact="Low")
    mapping = check_mapping(draft, {"risk_level": "Low", "categories": ["usability"]}, CHUNKS)
    assert not mapping.requires_compliance_officer_approval
    assert [f.type for f in mapping.flags] == ["no_kb_rule"]


def test_suggest_missing_controls():
    reqs = [req("FR-01", "The system shall encrypt data and keep an audit log of changes.")]
    suggestions = suggest_missing_controls(reqs, CHUNKS)
    controls = [s.control for s in suggestions]
    assert "encryption" not in controls and "audit_logging" not in controls
    assert "multi_factor_authentication" in controls
    assert all(s.status == "suggested" for s in suggestions)
    assert [s.id for s in suggestions] == [f"SUG-{n:02d}" for n in range(1, len(suggestions) + 1)]


# ---------------------------------------------------------- in the pipeline --
def test_quality_and_compliance_in_pipeline(mock_llm):
    result = run_pipeline("Personal loan approval", options={"num_functional": 2, "num_non_functional": 2})
    q = result.get("quality_agent").parsed
    assert [r.requirement_id for r in q.reviews] == ["FR-01", "FR-02", "NFR-01", "NFR-02"]
    nfr = q.review_for("NFR-01")
    assert {"rule", "llm"} <= {i.origin for i in nfr.issues}
    assert nfr.clarification_questions[0].stakeholder_role == "Product owner"

    c = result.get("compliance_agent").parsed
    assert [m.requirement_id for m in c.mappings] == ["FR-01", "FR-02", "NFR-01", "NFR-02"]
    assert c.mappings[0].applicable_rules == ["KB-1"]
    assert c.disclaimer.startswith("Decision support only")
    # The compliance prompt contains the wider KB context.
    prompt = mock_llm.calls_for("ComplianceBatch")[0].user_prompt
    assert "KNOWLEDGE BASE (the only rules you may cite)" in prompt


def test_quality_schema_forces_valid_ids_per_batch(mock_llm):
    run_pipeline("Loans", options={"num_functional": 5, "num_non_functional": 1})
    batches = mock_llm.calls_for("QualityBatch")
    enums = [c.json_schema["$defs"]["RequirementReviewDraft"]["properties"]["requirement_id"]["enum"]
             for c in batches]
    assert enums == [["FR-01", "FR-02", "FR-03", "FR-04"], ["FR-05", "NFR-01"]]


def test_failed_quality_batch_keeps_rule_findings(mock_llm):
    mock_llm.responses["QualityBatch"] = "not json"
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1})
    quality_result = result.get("quality_agent")
    assert quality_result.status == "partial"
    nfr = quality_result.parsed.review_for("NFR-01")
    assert nfr.issues and all(i.origin == "rule" for i in nfr.issues)


def test_failed_compliance_batch_marks_not_assessed(mock_llm):
    mock_llm.responses["ComplianceBatch"] = "not json"
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1})
    mapping = result.get("compliance_agent").parsed.mappings[0]
    assert mapping.requires_compliance_officer_approval
    assert mapping.flags[0].type == "not_assessed"


def test_kb_citation_beyond_requirements_view_is_invalid_for_requirements(mock_llm, monkeypatch):
    monkeypatch.setattr(config, "KB_MAX_CHUNKS", 1)        # requirements see only KB-1
    mock_llm.responses["RequirementsBatch"] = lambda s, u: {"scenario_summary": "x", "requirements": [
        make_requirement("FR-01", sources=["KB-2"], applicable_rules=["KB-2"])]}
    result = run_pipeline("Personal loan with KYC checks and data encryption",
                          options={"num_functional": 1, "num_non_functional": 1})
    assert "KB-2" in result.chunk_map                       # compliance saw it...
    fr1 = result.get("requirements_agent").parsed.requirements[0]
    assert fr1.sources == [] and fr1.applicable_rules == []   # ...but requirements did not


# ------------------------------------------------------------ revision loop --
@pytest.fixture
def revision_on(monkeypatch):
    monkeypatch.setattr(config, "QUALITY_REVISION_ENABLED", True)


def test_revision_round_rewrites_high_severity_requirements_once(mock_llm, revision_on):
    def quality_answer(system, user, schema):
        ids = schema["$defs"]["RequirementReviewDraft"]["properties"]["requirement_id"]["enum"]
        return {"reviews": [{"requirement_id": rid, "issues": [
            {"type": "ambiguity", "explanation": "Unclear.", "severity": "High"}] if rid == "FR-01" else [],
            "clarification_questions": []} for rid in ids]}
    mock_llm.responses["QualityBatch"] = quality_answer

    steps = []
    result = run_pipeline("Loans", options={"num_functional": 2, "num_non_functional": 1},
                          on_step_finished=lambda node, s, u: steps.append(node))
    assert steps == ["prepare_context", "requirements_agent", "quality_agent", "revise_requirements",
                     "quality_agent", "compliance_agent", "sdlc_agent", "workflow_agent"]  # ONE round
    fr1 = result.get("requirements_agent").parsed.requirements[0]
    assert len(fr1.revision_history) == 1
    assert fr1.revision_history[0]["issues"][0]["severity"] == "High"
    assert result.get("requirements_agent").parsed.validation_summary["revised_ids"] == ["FR-01"]
    revision_prompt = mock_llm.calls[3].user_prompt
    assert "ISSUE (High, ambiguity): Unclear." in revision_prompt


def test_no_revision_when_no_high_issues(mock_llm, revision_on):
    steps = []
    run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1},
                 on_step_finished=lambda node, s, u: steps.append(node))
    assert "revise_requirements" not in steps
