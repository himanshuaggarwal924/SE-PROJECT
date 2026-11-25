"""Phase 7: roles (RBAC), joint SDLC approval, MFA, projects, requirement
history and diffs, transcripts and artefacts in SQLite, migration."""

import json

import pyotp
import pytest

import audit_log
import config
from auth import mfa, rbac, user_store
from pipeline import resume_pipeline, run_pipeline, run_state
from storage import baselines, db, migrate, projects
from tests.mock_llm import make_requirement


def register(username, roles):
    user_store.register_user(username, username.title(), f"{username}@example.com", "secret123",
                             user_store.SECURITY_QUESTIONS[0], "answer")
    user_store.set_roles(username, roles)


@pytest.fixture
def team():
    register("ana", ["analyst"])
    register("carl", ["compliance_officer"])
    register("sam", ["security_officer"])
    register("pam", ["project_manager"])
    register("arch", ["architect"])
    register("root", ["admin"])


# --------------------------------------------------------------------- RBAC --
def test_permissions(team):
    assert rbac.can("carl", "approve_mapping") and not rbac.can("ana", "approve_mapping")
    assert rbac.can("pam", "lock_baseline") and not rbac.can("ana", "lock_baseline")
    assert rbac.can("root", "manage_kb") and not rbac.can("pam", "manage_kb")
    assert not rbac.can("nobody", "approve_requirement")


def test_mandatory_items_need_the_owning_role(team):
    reasons = ["high-risk security requirement"]
    assert not rbac.can_decide_requirement("ana", reasons)
    assert rbac.can_decide_requirement("sam", reasons)
    assert rbac.can_decide_requirement("ana", [])
    assert rbac.missing_roles_for("ana", reasons) == ["Security officer"]


def test_filter_requirement_decisions_and_audit(team):
    decisions = {"requirements": {"FR-01": {"action": "accept"}, "NFR-01": {"action": "accept"}},
                 "mappings": {"FR-01": {"action": "accept"}}, "suggested": {"SUG-01": "accept"}}
    mandatory = [{"type": "requirement", "id": "NFR-01", "reasons": ["high-risk security requirement"]}]
    allowed, denied = rbac.filter_requirement_decisions(decisions, mandatory, "ana", "run-1")
    assert allowed["requirements"] == {"FR-01": {"action": "accept"}} and allowed["reviewer"] == "ana"
    assert denied == ["requirement NFR-01", "mapping FR-01", "suggestion SUG-01"]
    assert len([e for e in audit_log.read_events("run-1") if e["event"] == "access_denied"]) == 3
    allowed, denied = rbac.filter_requirement_decisions(decisions, mandatory, "carl", "run-1")
    assert set(allowed["mappings"]) == {"FR-01"} and "suggestion SUG-01" not in denied


# --------------------------------------------------------- joint SDLC approval --
def test_sdlc_needs_all_four_roles(team):
    with pytest.raises(PermissionError):
        projects.record_sdlc_vote("r1", "ana", "approve")
    for user in ("pam", "arch", "sam"):
        projects.record_sdlc_vote("r1", user, "approve", "Agile + DevSecOps")
        assert projects.sdlc_joint_decision("r1", "Agile + DevSecOps") is None      # still waiting
    projects.record_sdlc_vote("r1", "carl", "approve", "Agile + DevSecOps", "ok for compliance")
    decision = projects.sdlc_joint_decision("r1", "Agile + DevSecOps")
    assert decision["action"] == "approve" and "compliance_officer: carl" in decision["reviewer"]


def test_sdlc_votes_disagreeing_models_wait_and_any_reject_rejects(team):
    for user in ("pam", "arch", "sam"):
        projects.record_sdlc_vote("r2", user, "approve", "Agile + DevSecOps")
    projects.record_sdlc_vote("r2", "carl", "override", "V-Model")
    assert projects.sdlc_joint_decision("r2", "Agile + DevSecOps") is None
    projects.record_sdlc_vote("r2", "carl", "override", "Agile + DevSecOps")       # vote changed
    assert projects.sdlc_joint_decision("r2", "Agile + DevSecOps")["action"] == "approve"
    projects.record_sdlc_vote("r3", "sam", "reject", comment="too risky")
    assert projects.sdlc_joint_decision("r3", "Agile + DevSecOps")["action"] == "reject"


def test_one_user_with_several_roles_votes_for_each(team):
    register("multi", ["project_manager", "architect"])
    assert projects.record_sdlc_vote("r4", "multi", "approve") == ["project_manager", "architect"]
    assert set(projects.sdlc_votes("r4")) == {"project_manager", "architect"}


# ----------------------------------------------------------------------- MFA --
def test_totp_enrolment_and_verification(team):
    secret = mfa.new_secret()
    assert mfa.verify(secret, pyotp.TOTP(secret).now())
    assert not mfa.verify(secret, "000000") or pyotp.TOTP(secret).now() == "000000"
    assert not mfa.verify(secret, "abc")
    assert mfa.qr_png(mfa.provisioning_uri(secret, "ana")).startswith(b"\x89PNG")
    user_store.set_mfa_secret("ana", secret)
    assert user_store.get_mfa_secret("ana") == secret
    user_store.set_mfa_secret("ana", None)
    assert user_store.get_mfa_secret("ana") is None


# ------------------------------------------------------------------ projects --
def test_projects_and_runs(mock_llm, team):
    assert [p["name"] for p in projects.list_projects()] == ["default"]
    projects.create_project("Loans 2026", "retail lending", "pam")
    with pytest.raises(ValueError, match="already exists"):
        projects.create_project("Loans 2026", "", "pam")
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1, "project": "Loans 2026"})
    assert projects.run_project(result.run_id) == "Loans 2026"
    assert [r["run_id"] for r in projects.project_runs("Loans 2026")] == [result.run_id]


def test_requirement_history_and_diff(mock_llm, team):
    options = {"num_functional": 2, "num_non_functional": 1, "review_mode": "interactive", "project": "default"}
    first = run_pipeline("Loans", options=options)
    resume_pipeline(first.run_id, {"reviewer": "ana", "requirements": {
        "FR-01": {"action": "edit", "new": {"statement": "The system shall do thing FR-01 faster."}}}})
    history = projects.requirement_history("default", "FR-01")
    assert [(h["version"], h["content"]["statement"]) for h in history] == [
        (1, "The system shall do thing FR-01."), (2, "The system shall do thing FR-01 faster.")]

    second = run_pipeline("Loans", options={**options, "num_functional": 1})
    rows = {r["id"]: r for r in projects.diff_requirements(projects.run_requirements(first.run_id),
                                                           projects.run_requirements(second.run_id))}
    assert rows["FR-02"]["change"] == "removed"
    assert rows["FR-01"]["change"] == "changed" and "[-faster.]" in rows["FR-01"]["details"]
    assert rows["NFR-01"]["change"] == "unchanged"


def test_change_request_is_recorded_in_history(mock_llm, team):
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1, "review_mode": "auto"})
    state = {"run_id": result.run_id, "scenario": "Loans", "agent_outputs": {
        k: {"parsed": result.get(k).parsed.model_dump()} for k in ("requirements_agent", "compliance_agent", "sdlc_agent")}}
    v1 = baselines.lock_baseline(state, "pam")
    cr = baselines.request_change(v1["id"], "FR-01", {"statement": "Changed by CR."}, "why", "ana")
    baselines.decide_change_request(cr, True, "pam")
    sources = [h["source"] for h in projects.requirement_history("default", "FR-01")]
    assert sources[-1] == "change_request"


# ------------------------------------------------- transcripts and artefacts --
def test_transcripts_live_in_the_database(mock_llm, team):
    from interview import engine, store
    session = engine.start_session("operations", "Payments", "Ravi", "ana")
    store.save(session)
    assert store.load(session["id"])["stakeholder_name"] == "Ravi"
    assert [s["id"] for s in store.list_sessions("ana")] == [session["id"]]
    assert store.list_sessions("carl") == []
    assert db.query("SELECT COUNT(*) AS n FROM transcripts")[0]["n"] == 1


def test_artefacts_are_stored(mock_llm, team):
    from artefacts.bundle import generate
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1})
    files = generate(result, "ana")
    projects.store_artefacts(result.run_id, files, "ana")
    assert projects.stored_artefacts(result.run_id) == files


def test_migration_imports_legacy_transcript_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "INTERVIEWS_DIR", tmp_path / "interviews")
    config.INTERVIEWS_DIR.mkdir()
    legacy = {"id": "iv-legacy", "created_by": "ana", "created_at": "2026-01-01T10:00:00+05:30",
              "status": "ended", "turns": [], "role_label": "Operations"}
    (config.INTERVIEWS_DIR / "iv-legacy.json").write_text(json.dumps(legacy), encoding="utf-8")
    assert migrate.migrate_transcripts(dry_run=True) == {"found": 1, "imported": 1, "skipped": 0, "dry_run": True}
    assert projects.load_transcript("iv-legacy") is None                 # dry run changed nothing
    assert migrate.migrate_transcripts()["imported"] == 1
    assert projects.load_transcript("iv-legacy")["role_label"] == "Operations"
    assert (config.INTERVIEWS_DIR / "iv-legacy.json.migrated").exists()  # nothing deleted
    assert migrate.migrate_transcripts()["found"] == 0                   # not imported twice


def test_pending_items_can_be_decided_after_the_run(mock_llm, team):
    from pipeline import apply_post_run_decisions
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1,
                                            "review_mode": "interactive"})
    result = resume_pipeline(result.run_id, {"reviewer": "ana", "requirements": {"FR-01": {"action": "accept"}}})
    result = resume_pipeline(result.run_id, {"reviewer": "pam", "action": "approve"})
    assert result.status == "done"
    mapping = result.get("compliance_agent").parsed.mapping_for("FR-01")
    assert mapping.approval_status == "pending"                      # analyst could not decide it
    allowed, denied = rbac.filter_requirement_decisions(
        {"mappings": {"FR-01": {"action": "accept"}}}, [], "carl", result.run_id)
    result = apply_post_run_decisions(result.run_id, allowed)
    mapping = result.get("compliance_agent").parsed.mapping_for("FR-01")
    assert mapping.approval_status == "approved" and mapping.reviewer == "carl"
    assert result.status == "done"                                   # still finished, nothing re-run
    assert result.get("workflow_agent").status == "ok"
