"""Phase 6: human-in-the-loop review (interrupts + SQLite checkpointer),
approvals, baselines, change requests and regeneration."""

import pytest

import audit_log
import pipeline
from orchestration.regenerate import regenerate_mapping, regenerate_requirement
from orchestration.review import AUTO_REVIEWER, blocking_items, mandatory_items
from pipeline import load_result, resume_pipeline, run_pipeline, run_state
from storage import baselines, db
from tests.mock_llm import make_requirement

OPTIONS = {"num_functional": 2, "num_non_functional": 1, "review_mode": "interactive"}


def start(mock_llm, **extra):
    return run_pipeline("Personal loan approval", user="alice", options={**OPTIONS, **extra})


def accept_all(result_or_state, reviewer="alice"):
    state = run_state(result_or_state.run_id) if hasattr(result_or_state, "run_id") else result_or_state
    reqs = state["agent_outputs"]["requirements_agent"]["parsed"]["requirements"]
    maps = state["agent_outputs"]["compliance_agent"]["parsed"]["mappings"]
    return {"reviewer": reviewer, "requirements": {r["id"]: {"action": "accept"} for r in reqs},
            "mappings": {m["requirement_id"]: {"action": "accept"} for m in maps}}


# ----------------------------------------------------------------- pausing --
def test_interactive_run_pauses_after_compliance(mock_llm):
    result = start(mock_llm)
    assert result.status == "awaiting_review" and result.review_stage == "requirements_review"
    statuses = {r.key: r.status for r in result.agent_results}
    assert statuses["compliance_agent"] == "ok"
    assert statuses["sdlc_agent"] == statuses["workflow_agent"] == "not_run"
    assert mock_llm.calls_for("SDLCFactorsBatch") == []
    assert db.query("SELECT status, stage FROM runs WHERE run_id = ?", (result.run_id,))[0] == \
        {"status": "awaiting_review", "stage": "requirements_review"}
    assert {"type": "requirement", "id": "NFR-01"} not in result.review_payload["mandatory"]   # dicts carry reasons


def test_review_decisions_are_applied_audited_and_feed_the_next_agent(mock_llm):
    result = start(mock_llm)
    decisions = {"reviewer": "alice",
                 "requirements": {"FR-01": {"action": "accept", "comment": "ok"},
                                  "FR-02": {"action": "reject", "comment": "out of scope"},
                                  "NFR-01": {"action": "edit", "new": {"statement": "The system shall encrypt data at rest."}}},
                 "mappings": {"FR-01": {"action": "accept"}}}
    result = resume_pipeline(result.run_id, decisions)
    assert result.status == "awaiting_review" and result.review_stage == "sdlc_review"

    reqs = {r.id: r for r in result.get("requirements_agent").parsed.requirements}
    assert reqs["FR-01"].approval_status == "approved" and reqs["FR-01"].reviewer == "alice"
    assert reqs["FR-02"].approval_status == "rejected" and reqs["FR-02"].review_comment == "out of scope"
    nfr = reqs["NFR-01"]
    assert nfr.statement == "The system shall encrypt data at rest." and nfr.version == 2
    assert nfr.revision_history[-1]["statement"] == "The system shall do thing NFR-01."
    assert result.get("compliance_agent").parsed.mapping_for("FR-01").approval_status == "approved"
    assert result.get("compliance_agent").parsed.mapping_for("FR-02").approval_status == "pending"

    # Rejected requirements are not sent to the SDLC Agent.
    sdlc_prompt = mock_llm.calls_for("SDLCFactorsBatch")[0].user_prompt
    assert "FR-02 [" not in sdlc_prompt and "FR-01 [" in sdlc_prompt

    events = [e for e in audit_log.read_events(result.run_id) if e["event"] == "human_review"]
    assert {(e["item_id"], e["action"]) for e in events} >= {("FR-01", "accept"), ("FR-02", "reject"),
                                                            ("NFR-01", "edit"), ("FR-01", "accept")}
    edit = next(e for e in events if e["action"] == "edit")
    assert edit["before"]["statement"] != edit["after"]["statement"]
    assert len(db.query("SELECT * FROM approvals WHERE run_id = ?", (result.run_id,))) == len(events)


def test_pending_items_stay_pending(mock_llm):
    result = start(mock_llm)
    result = resume_pipeline(result.run_id, {"reviewer": "alice", "requirements": {}, "mappings": {}})
    assert all(r.approval_status == "pending" for r in result.get("requirements_agent").parsed.requirements)


def test_edit_reruns_deterministic_checks(mock_llm):
    result = start(mock_llm)
    result = resume_pipeline(result.run_id, {"reviewer": "alice", "requirements": {
        "FR-01": {"action": "edit", "new": {"statement": "The system shall approve loans within 17 minutes."}}}})
    fr1 = result.get("requirements_agent").parsed.requirements[0]
    assert any(f.type == "possible_hallucination" and "17" in f.detail for f in fr1.flags)


def test_accepted_suggestion_becomes_a_requirement(mock_llm):
    result = start(mock_llm)
    state = run_state(result.run_id)
    suggestion = state["agent_outputs"]["compliance_agent"]["parsed"]["suggested_requirements"][0]
    result = resume_pipeline(result.run_id, {"reviewer": "alice", "suggested": {suggestion["id"]: "accept"}})
    added = [r for r in result.get("requirements_agent").parsed.requirements if r.id.startswith("SEC-")]
    assert len(added) == 1 and added[0].statement == suggestion["statement"]
    assert added[0].approval_status == "approved"
    status = {s.id: s.status for s in result.get("compliance_agent").parsed.suggested_requirements}
    assert status[suggestion["id"]] == "accepted"


# ------------------------------------------------------------ SDLC review --
def test_sdlc_approval_finishes_the_run(mock_llm):
    result = start(mock_llm)
    result = resume_pipeline(result.run_id, accept_all(result))
    result = resume_pipeline(result.run_id, {"reviewer": "bob", "action": "approve", "comment": "agreed"})
    assert result.status == "done"
    sdlc = result.get("sdlc_agent").parsed
    assert sdlc.approval_status == "approved" and sdlc.selected_model == sdlc.recommended_model
    assert sdlc.reviewer == "bob"
    assert result.get("workflow_agent").parsed.model == sdlc.recommended_model
    assert db.query("SELECT status FROM runs WHERE run_id = ?", (result.run_id,))[0]["status"] == "done"


def test_sdlc_override_changes_the_workflow(mock_llm):
    result = start(mock_llm)
    result = resume_pipeline(result.run_id, accept_all(result))
    other = result.get("sdlc_agent").parsed.ranking[2].model
    result = resume_pipeline(result.run_id, {"reviewer": "bob", "action": "override", "model": other})
    assert result.get("sdlc_agent").parsed.approval_status == "overridden"
    assert result.get("workflow_agent").parsed.model == other


def test_sdlc_rejection_skips_the_workflow(mock_llm):
    result = start(mock_llm)
    result = resume_pipeline(result.run_id, accept_all(result))
    result = resume_pipeline(result.run_id, {"reviewer": "bob", "action": "reject", "comment": "no"})
    workflow = result.get("workflow_agent")
    assert workflow.status == "skipped" and "rejected" in workflow.parse_error
    assert mock_llm.calls_for("WorkflowCustomisation") == []


# ------------------------------------------------ resume after a restart --
def test_run_can_be_resumed_after_restart(mock_llm):
    result = start(mock_llm)
    pipeline.reset_checkpointer()                       # simulate a fresh app process
    reloaded = load_result(result.run_id)
    assert reloaded.status == "awaiting_review" and reloaded.review_stage == "requirements_review"
    assert [r.id for r in reloaded.get("requirements_agent").parsed.requirements] == ["FR-01", "FR-02", "NFR-01"]
    pipeline.reset_checkpointer()
    resumed = resume_pipeline(result.run_id, accept_all(reloaded))
    assert resumed.review_stage == "sdlc_review"
    assert pipeline.runs_for("alice", "awaiting_review")[0]["run_id"] == result.run_id
    assert load_result("no-such-run") is None


# ---------------------------------------------------------------- auto mode --
def test_auto_approve_runs_through_and_labels_items(mock_llm):
    steps = []
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1, "review_mode": "auto"},
                          on_step_finished=lambda node, s, u: steps.append(node))
    assert result.status == "done"
    assert steps == ["prepare_context", "requirements_agent", "quality_agent", "compliance_agent",
                     "review_requirements", "sdlc_agent", "review_sdlc", "workflow_agent"]
    for r in result.get("requirements_agent").parsed.requirements:
        assert r.approval_status == "approved" and r.auto_approved and r.reviewer == AUTO_REVIEWER
    assert result.get("sdlc_agent").parsed.approval_status == "approved"
    assert result.get("sdlc_agent").parsed.auto_approved


def test_default_mode_has_no_review_steps(mock_llm):
    steps = []
    run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1},
                 on_step_finished=lambda node, s, u: steps.append(node))
    assert "review_requirements" not in steps


# ------------------------------------------------- mandatory items, baseline --
def test_mandatory_items_and_baseline_lock(mock_llm):
    mock_llm.responses["RequirementsBatch"] = lambda s, u: {"scenario_summary": "x", "requirements": [
        make_requirement(rid, risk_level="High",
                         categories=["security"] if rid.startswith("NFR") else ["integration"])
        for rid in __import__("re").findall(r"\bN?FR-\d+\b", u.split("YOUR TASK NOW:")[-1].split("EXPECTED")[0])]}
    result = start(mock_llm)
    state = run_state(result.run_id)
    kinds = {(i["type"], i["id"]): i["reasons"] for i in mandatory_items(state)}
    assert "high-risk security requirement" in kinds[("requirement", "NFR-01")]
    assert "architecture-critical requirement" in kinds[("requirement", "FR-01")]
    assert ("mapping", "NFR-01") in kinds                 # security category -> officer approval

    result = resume_pipeline(result.run_id, accept_all(result))
    result = resume_pipeline(result.run_id, {"reviewer": "bob", "action": "approve"})
    state = run_state(result.run_id)
    assert blocking_items(state) == []
    baseline = baselines.lock_baseline(state, "alice")
    assert baseline["version"] == 1 and len(baseline["content"]["requirements"]) == 3
    assert baselines.lock_baseline(state, "alice")["version"] == 2


def test_baseline_blocked_while_mandatory_items_undecided(mock_llm):
    result = start(mock_llm)
    result = resume_pipeline(result.run_id, accept_all(result))      # SDLC still pending
    with pytest.raises(baselines.BaselineError, match="SDLC"):
        baselines.lock_baseline(run_state(result.run_id), "alice")


def test_change_request_creates_new_baseline_version(mock_llm):
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1, "review_mode": "auto"})
    state = run_state_auto = pipeline._graph("auto")  # noqa: F841 (auto runs keep state in memory)
    from orchestration.review import auto_requirement_decisions  # noqa: F401
    content_state = {"run_id": result.run_id, "scenario": "Loans", "agent_outputs": {
        "requirements_agent": {"parsed": result.get("requirements_agent").parsed.model_dump()},
        "compliance_agent": {"parsed": result.get("compliance_agent").parsed.model_dump()},
        "sdlc_agent": {"parsed": result.get("sdlc_agent").parsed.model_dump()}}}
    v1 = baselines.lock_baseline(content_state, "alice")

    with pytest.raises(baselines.BaselineError, match="not an approved requirement"):
        baselines.request_change(v1["id"], "FR-99", {"statement": "x"}, "why", "alice")
    cr = baselines.request_change(v1["id"], "FR-01", {"statement": "The system shall do it better."},
                                  "Clarified by product owner", "alice")
    assert baselines.change_requests("pending")[0]["id"] == cr
    v2 = baselines.decide_change_request(cr, True, "bob", "ok")
    assert v2["version"] == 2
    fr1 = next(r for r in v2["content"]["requirements"] if r["id"] == "FR-01")
    assert fr1["statement"] == "The system shall do it better." and fr1["reviewer"] == "bob"
    assert baselines.change_requests("approved")[0]["new_baseline_id"] == v2["id"]
    with pytest.raises(baselines.BaselineError, match="already approved"):
        baselines.decide_change_request(cr, True, "bob")

    cr2 = baselines.request_change(v2["id"], "FR-01", {"statement": "Something else."}, "", "carol")
    assert baselines.decide_change_request(cr2, False, "bob") is None
    assert baselines.latest_version("default") == 2
    actions = [e["action"] for e in audit_log.read_events(result.run_id) if e["event"] == "human_review"
               and e["item_type"] in ("baseline", "change_request")]
    assert actions == ["approve", "approve", "reject"]


# --------------------------------------------------------------- regenerate --
def test_regenerate_requirement_and_mapping(mock_llm):
    result = start(mock_llm)
    state = run_state(result.run_id)
    new = regenerate_requirement(state, "FR-02", comment="Mention the credit bureau")
    assert new["id"] == "FR-02" and "confidence_breakdown" in new
    prompt = mock_llm.calls[-1].user_prompt
    assert "ISSUE (reviewer): Mention the credit bureau" in prompt
    mapping = regenerate_mapping(state, "FR-01", comment="Check KB-1")
    assert mapping["requirement_id"] == "FR-01"
    assert "Reviewer comment: Check KB-1" in mock_llm.calls[-1].user_prompt
    # Submitted as a regenerate decision, it is recorded as such.
    result = resume_pipeline(result.run_id, {"reviewer": "alice",
                                             "requirements": {"FR-02": {"action": "regenerate", "new": new}}})
    fr2 = next(r for r in result.get("requirements_agent").parsed.requirements if r.id == "FR-02")
    assert fr2.approval_status == "approved" and fr2.revision_history[-1]["action"] == "regenerate"


def test_db_migrations_are_versioned():
    assert db.schema_version() == len(db.MIGRATIONS)
