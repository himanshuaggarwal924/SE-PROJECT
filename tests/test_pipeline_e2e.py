"""End-to-end pipeline tests with the mock LLM (no Ollama needed)."""

import json

import audit_log
import config
from pipeline import run_pipeline
from tests.mock_llm import make_requirement


def test_full_pipeline_with_typed_description(mock_llm):
    steps = []
    result = run_pipeline("Loan approval for a retail bank", user="alice",
                          on_step_finished=lambda node, secs, update: steps.append(node))

    assert steps == ["prepare_context", "requirements_agent", "quality_agent",
                     "compliance_agent", "sdlc_agent", "workflow_agent"]
    requirements = result.get("requirements_agent").parsed
    assert [r.id for r in requirements.functional_requirements] == \
        [f"FR-0{n}" for n in range(1, config.NUM_FUNCTIONAL_REQUIREMENTS + 1)]
    assert len(requirements.non_functional_requirements) == config.NUM_NON_FUNCTIONAL_REQUIREMENTS
    assert all(r.approval_status == "pending" for r in requirements.requirements)
    assert result.get("sdlc_agent").parsed.recommended_model == "Agile + DevSecOps"
    assert result.context_info["method"] == "none"

    # The SDLC Agent received the compact requirement list.
    sdlc_prompt = mock_llm.calls_for("SDLCFactorsBatch")[0].user_prompt
    assert "OUTPUT FROM THE REQUIREMENTS AGENT" in sdlc_prompt
    assert "FR-01 [functional] (priority High, risk Medium): The system shall do thing FR-01." in sdlc_prompt


def test_requirements_are_written_in_batches(mock_llm):
    result = run_pipeline("Loans", options={"num_functional": 7, "num_non_functional": 2})
    batches = mock_llm.calls_for("RequirementsBatch")
    assert len(batches) == 4      # FR 3+3+1, NFR 2 (batch size 3)
    # Ollama's grammar is told the exact number of requirements per batch.
    sizes = [c.json_schema["properties"]["requirements"]["minItems"] for c in batches]
    assert sizes == [3, 3, 1, 2]
    assert [c.json_schema["properties"]["requirements"]["maxItems"] for c in batches] == sizes
    # Later batches are told what was already written.
    assert "None yet." in batches[0].user_prompt
    assert "FR-03: The system shall do thing FR-03." in batches[1].user_prompt
    assert len(result.get("requirements_agent").parsed.requirements) == 9


def test_audit_trail_records_every_step(mock_llm):
    result = run_pipeline("Loans", user="alice", options={"num_functional": 2, "num_non_functional": 1})
    events = audit_log.read_events(result.run_id)
    names = [e["event"] for e in events]
    assert names == ["pipeline_started", "context_prepared",
                     "agent_call", "agent_call", "agent_completed",      # requirements: 2 batches
                     "agent_call", "agent_completed",                    # quality: 1 batch of 3
                     "agent_call", "agent_completed",                    # compliance: 1 batch of 3
                     "agent_call", "agent_call", "agent_completed",      # sdlc: rate + explain
                     "agent_call", "agent_completed",                    # workflow
                     "pipeline_finished"]
    assert events[0]["user"] == "alice"
    assert "system_prompt" in events[2]["input"]
    assert events[4]["status"] == "ok"
    assert events[4]["validation_summary"]["produced"] == 3
    assert events[-1]["status"] == {"requirements_agent": "ok", "quality_agent": "ok",
                                    "compliance_agent": "ok", "sdlc_agent": "ok",
                                    "workflow_agent": "ok"}


def test_document_excerpts_are_cited_and_checked(mock_llm):
    def answer(system, user):
        return {"scenario_summary": "x", "requirements": [
            make_requirement("FR-01", statement="The system shall refer loans above 50,000 to an underwriter.",
                             sources=["C1"]),
            make_requirement("FR-02", statement="The system shall decide within 99 seconds.",
                             sources=["C1", "C9"]),
        ]}
    mock_llm.responses["RequirementsBatch"] = answer
    result = run_pipeline("Loans", source_text="Loans above 50,000 need an underwriter.",
                          source_name="policy.md", options={"num_functional": 2, "num_non_functional": 1})

    prompt = mock_llm.calls_for("RequirementsBatch")[0].user_prompt
    assert "[C1] (policy.md, part 1 of 1)\nLoans above 50,000 need an underwriter." in prompt
    assert result.chunk_map["C1"]["document"] == "policy.md"

    fr1, fr2 = result.get("requirements_agent").parsed.requirements[:2]
    assert fr1.flags == [] and not fr1.needs_human_review
    assert fr2.sources == ["C1"]                       # invalid C9 removed
    types = [f.type for f in fr2.flags]
    assert "invalid_citation" in types
    assert "possible_hallucination" in types           # 99 is in no source
    assert fr2.needs_human_review


def test_kb_excerpts_are_cited_and_rules_validated(mock_llm):
    def answer(system, user):
        return {"scenario_summary": "x", "requirements": [make_requirement(
            "FR-01", sources=["KB-1"],
            applicable_rules=["kb-1", "[KB-1]", "C1", "Imaginary Lending Act 2019"])]}
    mock_llm.responses["RequirementsBatch"] = answer
    result = run_pipeline("Personal loan approval", options={"num_functional": 1, "num_non_functional": 1})

    prompt = mock_llm.calls_for("RequirementsBatch")[0].user_prompt
    assert "KNOWLEDGE BASE" in prompt and "[KB-1] (" in prompt
    assert result.chunk_map["KB-1"]["origin"] == "kb"

    fr1 = result.get("requirements_agent").parsed.requirements[0]
    assert fr1.applicable_rules == ["KB-1"]              # de-duplicated, only real KB IDs
    unsupported = [f.detail for f in fr1.flags if f.type == "unsupported_rule"]
    assert len(unsupported) == 2                         # "C1" and the invented act
    assert any("Imaginary Lending Act" in d for d in unsupported)
    # No document was given, so citing nothing extra is not "missing_citation".
    assert "missing_citation" not in [f.type for f in fr1.flags]


def test_large_document_uses_retrieval(mock_llm, fake_retrieval):
    result = run_pipeline("Payments", source_text="Payments rules. " * 1000, source_name="big.md")
    assert result.context_info["method"] == "retrieval"
    assert "[C1] (big.md, part 1 of" in mock_llm.calls_for("RequirementsBatch")[0].user_prompt


def test_sdlc_parse_failure_does_not_crash_the_run(mock_llm):
    mock_llm.responses["SDLCFactorsBatch"] = "Sorry, I am not sure."
    result = run_pipeline("Loans")
    sdlc = result.get("sdlc_agent")
    assert sdlc.parsed is None and sdlc.status == "failed"
    assert sdlc.parse_error
    assert sdlc.raw_output == "Sorry, I am not sure."     # explanation call was skipped
    assert result.get("requirements_agent").parsed is not None
    assert result.get("workflow_agent").status == "skipped"


def test_one_bad_batch_gives_partial_result(mock_llm):
    from tests.mock_llm import requirements_batch
    answers = iter(["not json at all"])
    mock_llm.responses["RequirementsBatch"] = \
        lambda s, u: next(answers, None) or requirements_batch(s, u)
    result = run_pipeline("Loans", options={"num_functional": 3, "num_non_functional": 3})
    requirements = result.get("requirements_agent")
    assert requirements.status == "partial"
    assert [r.id for r in requirements.parsed.requirements] == ["NFR-01", "NFR-02", "NFR-03"]
    assert requirements.parsed.validation_summary["failed_batches"] == 1
    assert result.get("sdlc_agent").status == "ok"


def test_failed_requirements_skip_the_sdlc_agent(mock_llm):
    mock_llm.responses["RequirementsBatch"] = "garbage"
    result = run_pipeline("Loans")
    assert result.get("requirements_agent").status == "failed"
    assert result.get("sdlc_agent").status == "skipped"
    assert mock_llm.calls_for("SDLCFactorsBatch") == []     # no wasted model call


def test_results_are_json_serialisable(mock_llm):
    result = run_pipeline("Loans")
    json.dumps({r.key: r.parsed.model_dump() for r in result.agent_results})


def test_claim_support_flags_irrelevant_citation_and_feeds_quality(mock_llm, fake_retrieval):
    def answer(system, user):
        return {"scenario_summary": "x", "requirements": [
            make_requirement("FR-01", statement="The system shall refer loans above 50,000 to an underwriter.",
                             sources=["C1", "C2"]),
            make_requirement("FR-02", statement="The system shall send monthly statements by email.",
                             sources=["C2"])]}
    mock_llm.responses["RequirementsBatch"] = answer
    doc = "Loans above 50,000 need an underwriter.\n\n" + "x" * 900 + "\n\nMonthly statements are emailed."
    result = run_pipeline("Loans", source_text=doc, source_name="p.md",
                          options={"num_functional": 2, "num_non_functional": 1})
    output = result.get("requirements_agent").parsed
    fr1 = output.requirements[0]
    assert any(f.type == "weak_citation" and f.detail.startswith("C2") for f in fr1.flags)
    assert len(output.statement_similarity) == len(output.requirements)
    # The Quality Agent reused the matrix: only ONE similarity job was sent to the worker.
    assert sum(1 for job in fake_retrieval if job.get("similarity_texts")) == 1
    assert result.get("quality_agent").parsed.summary["duplicate_method"] == "embedding"


def test_optional_agents_can_be_turned_off(mock_llm):
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1,
                                            "disabled_agents": ["quality_agent", "compliance_agent",
                                                                "workflow_agent", "sdlc_agent"]})
    statuses = {r.key: r.status for r in result.agent_results}
    assert statuses["quality_agent"] == statuses["compliance_agent"] == "skipped"
    assert statuses["workflow_agent"] == "skipped"
    # The SDLC Agent is not optional, and quality/compliance are only optional inputs to it.
    assert statuses["sdlc_agent"] == "ok"
    assert "(not available for this run)" in mock_llm.calls_for("SDLCFactorsBatch")[0].user_prompt
    assert mock_llm.calls_for("QualityBatch") == [] and mock_llm.calls_for("ComplianceBatch") == []
