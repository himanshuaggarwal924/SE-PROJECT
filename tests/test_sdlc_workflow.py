"""Phase 4: deterministic SDLC scoring, the SDLC Agent (rate -> score ->
explain) and the Workflow Agent."""

import pytest

import config
from agents import sdlc_scoring
from agents.sdlc_scoring import DECISION_FACTORS, confidence_from_gap, score_models
from pipeline import run_pipeline
from tests.mock_llm import CANNED_FACTOR_RATINGS


def all_factors(level="Medium", **overrides):
    return {**{f: level for f in DECISION_FACTORS}, **overrides}


# ---------------------------------------------------------- the rule table --
def test_rule_table_is_consistent():
    rules = sdlc_scoring.load_rules()
    assert set(rules["factor_weights"]) == set(DECISION_FACTORS)
    for model, prefs in rules["models"].items():
        assert set(prefs) <= set(DECISION_FACTORS), model
    for rule in rules["rules"]:
        assert set(rule["when"]) <= set(DECISION_FACTORS)
        assert set(rule["adjust"]) <= set(rules["models"])


def test_every_model_has_a_workflow_template():
    for model in sdlc_scoring.load_rules()["models"]:
        template = sdlc_scoring.load_workflow_template(model)
        assert template, f"No workflow template for {model}"
        for phase in template["phases"]:
            for field in ("activities", "roles", "deliverables", "security_activities", "testing",
                          "compliance_checkpoints", "approval_gates", "entry_criteria",
                          "exit_criteria", "traceability"):
                assert field in phase, f"{model} / {phase['name']} lacks {field}"


def test_templates_cover_finance_essentials():
    """Every model's workflow has threat modelling or SAST, transaction-integrity
    testing and at least one human approval gate."""
    for model in sdlc_scoring.load_rules()["models"]:
        phases = sdlc_scoring.load_workflow_template(model)["phases"]
        text = str(phases).lower()
        assert "sast" in text or "threat modelling" in text, model
        assert "transaction-integrity" in text, model
        assert any(p["approval_gates"] for p in phases), model


# ------------------------------------------------------------------ scoring --
@pytest.mark.parametrize("ratings, expected_top", [
    (all_factors(requirement_stability="High", change_frequency="Low", stakeholder_availability="Low",
                 complexity="Low", testing_documentation_needs="High", continuous_delivery_need="Low",
                 budget_schedule_constraints="High", regulatory_criticality="Low", security_risk="Low"),
     "Waterfall"),
    (all_factors(change_frequency="High", requirement_stability="Low", stakeholder_availability="High",
                 continuous_delivery_need="High", formal_verification_need="Low",
                 testing_documentation_needs="Low", regulatory_criticality="Low", security_risk="Low",
                 failure_consequences="Low"),
     "Agile"),
    (all_factors(requirement_stability="High", formal_verification_need="High",
                 testing_documentation_needs="High", regulatory_criticality="High",
                 failure_consequences="High", change_frequency="Low", continuous_delivery_need="Low"),
     "V-Model"),
    (CANNED_FACTOR_RATINGS, "Agile + DevSecOps"),
])
def test_textbook_profiles_rank_as_expected(ratings, expected_top):
    assert score_models(ratings)[0].model == expected_top


def test_scores_are_percentages_sorted_and_ranked():
    scores = score_models(CANNED_FACTOR_RATINGS)
    assert [s.rank for s in scores] == list(range(1, len(scores) + 1))
    assert all(0 <= s.score <= 100 for s in scores)
    assert [s.score for s in scores] == sorted((s.score for s in scores), reverse=True)


def test_rules_fire_and_are_reported():
    scores = {s.model: s for s in score_models(all_factors(change_frequency="High"))}
    assert any(a["points"] == -15 for a in scores["Waterfall"].adjustments)


def test_missing_factor_is_left_out_of_the_score():
    only_security = {s.model: s for s in score_models({"security_risk": "High"})}
    assert all(c["factor"] == "security_risk" for s in only_security.values() for c in s.contributions)
    # Rules that depend on a missing factor don't fire.
    assert not any(a["points"] == -15 for a in only_security["Waterfall"].adjustments)


def test_confidence_from_gap():
    from agents.sdlc_scoring import ModelScore
    assert confidence_from_gap([ModelScore("a", 80), ModelScore("b", 65)]) == "High"
    assert confidence_from_gap([ModelScore("a", 80), ModelScore("b", 75)]) == "Medium"
    assert confidence_from_gap([ModelScore("a", 80), ModelScore("b", 78)]) == "Low"


# ---------------------------------------------------------- in the pipeline --
def test_sdlc_ranking_is_computed_by_python_and_explained(mock_llm):
    result = run_pipeline("Loans", options={"num_functional": 2, "num_non_functional": 1})
    sdlc = result.get("sdlc_agent").parsed
    assert sdlc.recommended_model == score_models(CANNED_FACTOR_RATINGS)[0].model == sdlc.ranking[0].model
    assert len(sdlc.factors) == 13
    assert sdlc.factors_scored == 13 and sdlc.scoring_basis.startswith("Based on 13 of 13")
    assert sdlc.explanation_source == "llm"
    assert [a.model for a in sdlc.runner_up_explanations] == [r.model for r in sdlc.ranking[1:3]]
    assert sdlc.approval_status == "pending"

    # The explainer saw ONLY ratings and scores, not the requirements.
    explain = mock_llm.calls_for("SDLCExplanationDraft")[0]
    assert "OUTPUT FROM THE REQUIREMENTS AGENT" not in explain.user_prompt
    assert "RANKING (computed by the scoring rules" in explain.user_prompt
    # ...and could only name the real runner-ups.
    enum = explain.json_schema["$defs"]["Alternative"]["properties"]["model"]["enum"]
    assert enum == [r.model for r in sdlc.ranking[1:3]]
    # The factor call had to rate exactly 13 factors.
    factors_call = mock_llm.calls_for("SDLCFactorsBatch")[0]
    assert factors_call.json_schema["properties"]["factors"]["minItems"] == 13


def test_invalid_evidence_and_missing_factors_are_flagged(mock_llm):
    mock_llm.responses["SDLCFactorsBatch"] = lambda s, u: {"factors": [
        {"factor": "security_risk", "rating": "High", "evidence": ["FR-01", "FR-99"], "reasoning": "x"}]}
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1})
    sdlc = result.get("sdlc_agent").parsed
    factors = {f.factor: f for f in sdlc.factors}
    assert factors["security_risk"].evidence == ["FR-01"] and factors["security_risk"].scored
    assert [f.type for f in factors["security_risk"].flags] == ["invalid_evidence"]
    assert factors["complexity"].flags[0].type == "not_rated" and not factors["complexity"].scored
    # Only 1 factor had evidence: below the minimum, so all ratings are used and confidence is Low.
    assert sdlc.factors_scored == 1 and sdlc.confidence == "Low"
    assert sdlc.scoring_basis.startswith("Only 1 of 13 factors had evidence")


def test_factors_without_evidence_are_not_scored(mock_llm):
    from tests.mock_llm import CANNED_FACTOR_RATINGS
    evidenced = ["regulatory_criticality", "security_risk", "change_frequency",
                 "continuous_delivery_need", "failure_consequences"]
    mock_llm.responses["SDLCFactorsBatch"] = lambda s, u: {"factors": [
        {"factor": f, "rating": r, "evidence": ["FR-01"] if f in evidenced else [], "reasoning": "x"}
        for f, r in CANNED_FACTOR_RATINGS.items()]}
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1})
    sdlc = result.get("sdlc_agent").parsed
    assert sdlc.factors_scored == 5
    assert sdlc.scoring_basis.startswith("Based on 5 of 13 factors")
    assert sdlc.confidence == "Low"                       # 5 < 7 caps the confidence
    expected = score_models({f: CANNED_FACTOR_RATINGS[f] for f in evidenced})
    assert [r.model for r in sdlc.ranking] == [s.model for s in expected]
    unscored = [f for f in sdlc.factors if not f.scored]
    assert len(unscored) == 8 and all(f.flags[-1].type == "no_evidence" for f in unscored)
    # The explainer is told which factors were not scored.
    assert "(no evidence - not scored)" in mock_llm.calls_for("SDLCExplanationDraft")[0].user_prompt


def test_confidence_capped_by_coverage():
    from agents.sdlc_scoring import ModelScore, confidence_with_coverage
    clear_winner = [ModelScore("a", 90), ModelScore("b", 60)]
    assert confidence_with_coverage(clear_winner, 13) == "High"
    assert confidence_with_coverage(clear_winner, 8) == "Medium"
    assert confidence_with_coverage(clear_winner, 5) == "Low"


def test_failed_explanation_falls_back_to_template(mock_llm):
    mock_llm.responses["SDLCExplanationDraft"] = "garbage"
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1})
    sdlc = result.get("sdlc_agent")
    assert sdlc.status == "partial"
    assert sdlc.parsed.explanation_source == "template"
    assert sdlc.parsed.explanation.startswith(sdlc.parsed.recommended_model)
    assert len(sdlc.parsed.runner_up_explanations) == 2


def test_workflow_is_template_plus_bounded_additions(mock_llm):
    result = run_pipeline("Loans", options={"num_functional": 2, "num_non_functional": 1})
    sdlc = result.get("sdlc_agent").parsed
    workflow = result.get("workflow_agent").parsed
    template = sdlc_scoring.load_workflow_template(sdlc.recommended_model)
    assert workflow.model == sdlc.recommended_model
    assert [p.name for p in workflow.phases] == [p["name"] for p in template["phases"]]
    first = workflow.phases[0]
    assert any("Joint approval of the SDLC choice" in g for g in first.approval_gates)
    assert any("Compliance-officer approval" in c for c in first.compliance_checkpoints) or \
        not any(m.requires_compliance_officer_approval
                for m in result.get("compliance_agent").parsed.mappings)
    assert "Credit bureau integration test (FR-01)" in first.testing
    assert "testing: Credit bureau integration test (FR-01)" in first.added
    # Template items are kept.
    assert set(template["phases"][0]["activities"]) <= set(first.activities)
    assert workflow.customised_by_ai


def test_workflow_survives_failed_customisation(mock_llm):
    mock_llm.responses["WorkflowCustomisation"] = "garbage"
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1})
    workflow = result.get("workflow_agent")
    assert workflow.status == "partial"
    assert workflow.parsed.phases and not workflow.parsed.customised_by_ai


# ---------------------------------------------- evidence candidates (5.1) --
def test_candidate_evidence_maps_requirements_to_factors():
    from agents.sdlc_evidence import candidate_evidence
    reqs = [
        {"id": "FR-01", "statement": "The system shall apply the credit committee threshold.",
         "categories": ["functional", "business"], "risk_level": "High", "applicable_rules": ["KB-1"],
         "dependencies": ["FR-02"], "acceptance_criteria": [{}], "source_stakeholder": "Risk team"},
        {"id": "NFR-01", "statement": "The system shall encrypt data.", "categories": ["security", "privacy"],
         "risk_level": "Medium", "applicable_rules": [], "dependencies": [], "acceptance_criteria": [{}]},
    ]
    state = {"agent_outputs": {"requirements_agent": {"parsed": {"requirements": reqs}}},
             "chunk_map": {"KB-1": {"origin": "kb", "type": "policy"}}}
    found = candidate_evidence(state)
    assert set(found) == set(DECISION_FACTORS)
    assert found["security_risk"] == ["NFR-01"]
    assert found["failure_consequences"] == ["FR-01"]
    assert found["regulatory_criticality"] == ["FR-01", "KB-1"]
    assert found["change_frequency"] == ["FR-01"]            # business category + "threshold"
    assert found["stakeholder_availability"] == ["FR-01"]
    assert all(len(v) <= 4 for v in found.values())


def test_factor_prompt_contains_candidate_hints(mock_llm):
    run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1})
    prompt = mock_llm.calls_for("SDLCFactorsBatch")[0].user_prompt
    assert "- security_risk: High = sensitive data" in prompt and "Likely evidence:" in prompt
    assert "OUTPUT FROM THE REQUIREMENTS AGENT" in prompt          # the ID: statement list
