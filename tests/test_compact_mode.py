"""F1 investigation: the experimental compact requirements mode."""

import config
from agents.schemas import CompactRequirementDraft
from agents.requirements_agent import fill_compact
from pipeline import run_pipeline
from tests.mock_llm import make_requirement


def test_default_mode_is_full(mock_llm):
    assert config.REQUIREMENTS_PROMPT_MODE == "full"
    run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1})
    assert mock_llm.calls_for("RequirementsBatch") and not mock_llm.calls_for("RequirementsCompactBatch")


def test_compact_mode_uses_the_short_prompt_and_fills_fields(mock_llm, monkeypatch):
    monkeypatch.setattr(config, "REQUIREMENTS_PROMPT_MODE", "compact")
    mock_llm.responses["RequirementsCompactBatch"] = lambda s, u: {"scenario_summary": "x", "requirements": [
        make_requirement("FR-01", statement="The system shall refer loans above 50,000 to an underwriter.",
                         sources=["C1", "KB-1"], categories=["functional", "regulatory"])]}
    result = run_pipeline("Personal loan approval", source_text="Loans above 50,000 need an underwriter.",
                          source_name="p.md", options={"num_functional": 1, "num_non_functional": 1})
    call = mock_llm.calls_for("RequirementsCompactBatch")[0]
    assert "acceptance_criteria" not in str(call.json_schema)            # model not asked for the rest
    assert len(call.user_prompt) < len(mock_llm.calls_for("SDLCFactorsBatch")[0].user_prompt) * 3
    fr1 = result.get("requirements_agent").parsed.requirements[0]
    assert fr1.applicable_rules == ["KB-1"] and fr1.risk_level == "High"
    assert fr1.acceptance_criteria and fr1.model_confidence == 0.6
    assert fr1.sources == ["C1", "KB-1"] and not [f for f in fr1.flags if f.type == "possible_hallucination"]


def test_fill_compact():
    draft = CompactRequirementDraft(statement="The system shall log every decision.", categories=["audit/reporting"],
                                    priority="high", sources=["C2"])
    filled = fill_compact(draft, {"C2": {"origin": "document"}})
    assert filled.priority == "High" and filled.risk_level == "Medium" and filled.applicable_rules == []
    assert filled.acceptance_criteria[0].then == "the system does log every decision"
