"""Smoke test: the results screen renders a real pipeline result without errors.

Uses Streamlit's built-in AppTest (runs the script headless, no browser).
"""

from streamlit.testing.v1 import AppTest

from pipeline import run_pipeline
from tests.mock_llm import make_requirement


def _render():
    # AppTest runs this function's source as a standalone script,
    # so the imports must be inside it.
    import streamlit as st
    from ui.results import render_results
    render_results(st.session_state["result"])


def test_results_screen_renders(mock_llm):
    mock_llm.responses["RequirementsBatch"] = lambda s, u: {"scenario_summary": "x", "requirements": [
        make_requirement("FR-01", sources=["C1"], statement="The system shall cap loans at 50,000."),
        make_requirement("FR-02", sources=["C5"], confidence=0.1),
    ]}
    result = run_pipeline("Loans", source_text="Loans are capped at 50,000.", source_name="p.md",
                          options={"num_functional": 2, "num_non_functional": 1})

    app = AppTest.from_function(_render)
    app.session_state["result"] = result
    app.run(timeout=120)

    assert not app.exception, app.exception
    assert any("needs review" in e.label for e in app.expander)
    assert any(m.label == "Need review" for m in app.metric)


def _kb_page():
    from ui.page_knowledge_base import render_knowledge_base_page
    render_knowledge_base_page()


def _register(username, roles):
    from auth import user_store
    user_store.register_user(username, username, f"{username}@example.com", "secret123",
                             user_store.SECURITY_QUESTIONS[0], "answer")
    user_store.set_roles(username, roles)


def test_kb_page_is_admin_only():
    _register("adminuser", ["admin"])
    _register("plainuser", ["analyst"])

    app = AppTest.from_function(_kb_page)
    app.session_state["username"] = "plainuser"
    app.run(timeout=120)
    assert not app.exception
    assert any("Only administrators" in e.value for e in app.error)
    assert len(app.dataframe) == 0

    app = AppTest.from_function(_kb_page)
    app.session_state["username"] = "adminuser"
    app.run(timeout=120)
    assert not app.exception, app.exception
    assert len(app.dataframe) == 1
    assert any("SAMPLE" in w.value for w in app.warning)


def _interview_page():
    from ui.page_interview import render_interview_page
    render_interview_page()


def test_interview_page_renders_start_form_and_active_chat(monkeypatch, tmp_path):
    import config
    import llm_service
    from interview import engine
    monkeypatch.setattr(config, "INTERVIEWS_DIR", tmp_path / "interviews")
    monkeypatch.setattr(llm_service, "list_installed_models", lambda: ["llama3.2:3b"])

    app = AppTest.from_function(_interview_page)
    app.session_state["username"] = "alice"
    app.run(timeout=120)
    assert not app.exception, app.exception
    assert any(b.label == "🎙️ Start interview" for b in app.button)

    app = AppTest.from_function(_interview_page)
    app.session_state["username"] = "alice"
    app.session_state["interview"] = engine.start_session("operations", "Payments", "Ravi", "alice")
    app.run(timeout=120)
    assert not app.exception, app.exception
    assert any("Topic coverage" in m.value for m in app.markdown)
    assert len(app.chat_input) == 1


def _analysis_results():
    import streamlit as st
    from ui.review_panel import render_baseline_panel, render_review
    from ui.results import render_results
    result = st.session_state["result"]
    if result.status == "awaiting_review":
        render_review(result)
        render_results(result)
    else:
        render_results(result)
        render_baseline_panel(result)


def test_review_screens_render(mock_llm):
    from pipeline import resume_pipeline
    _register("alice", ["analyst"])        # Phase 7: approving needs a reviewer role
    result = run_pipeline("Loans", user="alice", options={"num_functional": 1, "num_non_functional": 1,
                                                          "review_mode": "interactive"})
    app = AppTest.from_function(_analysis_results)
    app.session_state["username"] = "alice"
    app.session_state["result"] = result
    app.run(timeout=120)
    assert not app.exception, app.exception
    assert any("Review 1 of 2" in h.value for h in app.subheader)
    assert any("Submit review and continue" in b.label for b in app.button)
    assert any("waiting for review" in i.value for i in app.info)       # SDLC tab not run yet

    # Accept everything through the widgets, then submit -> a resume request is queued.
    app.button[0].click().run(timeout=120)                                 # "Set every Pending ... Accept"
    next(b for b in app.button if "Submit review" in b.label).click().run(timeout=120)
    assert not app.exception, app.exception
    request = app.session_state["resume_request"]
    assert request["decisions"]["requirements"] == {"FR-01": {"action": "accept", "comment": ""},
                                                    "NFR-01": {"action": "accept", "comment": ""}}

    result = resume_pipeline(result.run_id, request["decisions"])
    app = AppTest.from_function(_analysis_results)
    app.session_state["username"] = "alice"
    app.session_state["result"] = result
    app.run(timeout=120)
    assert not app.exception, app.exception
    assert any("Review 2 of 2" in h.value for h in app.subheader)

    result = resume_pipeline(result.run_id, {"reviewer": "alice", "action": "approve"})
    app = AppTest.from_function(_analysis_results)
    app.session_state["username"] = "alice"
    app.session_state["result"] = result
    app.run(timeout=120)
    assert not app.exception, app.exception
    assert any("Lock requirements baseline" in b.label for b in app.button)


def test_artefacts_tab_generates_downloads(mock_llm):
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1, "review_mode": "auto"})
    app = AppTest.from_function(_render)
    app.session_state["result"] = result
    app.run(timeout=120)
    next(b for b in app.button if b.label == "📦 Generate artefacts").click().run(timeout=120)
    assert not app.exception, app.exception
    downloads = app.get("download_button")
    assert len(downloads) >= 16            # results JSON + ZIP + 15 files


def _evaluation_page():
    from ui.page_evaluation import render_evaluation_page
    render_evaluation_page()


def test_evaluation_page_renders(mock_llm, tmp_path, monkeypatch):
    import config
    from evaluation import gold as gold_files
    from evaluation.runner import run_evaluation
    monkeypatch.setattr(config, "EVAL_RESULTS_DIR", tmp_path)
    app = AppTest.from_function(_evaluation_page)
    app.run(timeout=120)
    assert not app.exception and any("No evaluation results" in i.value for i in app.info)

    run_evaluation(gold_files.load_all(["loan_approval_policy"]), {"num_functional": 1, "num_non_functional": 1})
    app = AppTest.from_function(_evaluation_page)
    app.run(timeout=120)
    assert not app.exception, app.exception
    assert any("DRAFT" in w.value for w in app.warning)
    assert len(app.dataframe) >= 2


def _admin_page():
    from ui.page_admin import render_admin_page
    render_admin_page()


def test_admin_page_is_admin_only_and_verifies_the_log():
    import audit_log
    _register("boss", ["admin"])
    _register("worker", ["analyst"])
    audit_log.log_event("r", "something")
    app = AppTest.from_function(_admin_page)
    app.session_state["username"] = "worker"
    app.run(timeout=120)
    assert any("Only administrators" in e.value for e in app.error)
    app = AppTest.from_function(_admin_page)
    app.session_state["username"] = "boss"
    app.run(timeout=120)
    next(b for b in app.button if "Verify audit log" in b.label).click().run(timeout=120)
    assert not app.exception, app.exception
    assert any("Chain intact" in s.value for s in app.success)


def test_sdlc_joint_vote_and_role_locks(mock_llm):
    from pipeline import resume_pipeline
    _register("pmgr", ["project_manager"])
    _register("ana", ["analyst"])
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1,
                                            "review_mode": "interactive"})
    result = resume_pipeline(result.run_id, {"reviewer": "pmgr", "requirements": {}})
    app = AppTest.from_function(_analysis_results)
    app.session_state["username"] = "ana"                 # analyst: may not vote
    app.session_state["result"] = result
    app.run(timeout=120)
    assert not app.exception, app.exception
    assert next(b for b in app.button if "Submit my vote" in b.label).disabled
    app = AppTest.from_function(_analysis_results)
    app.session_state["username"] = "pmgr"
    app.session_state["result"] = result
    app.run(timeout=120)
    next(b for b in app.button if "Submit my vote" in b.label).click().run(timeout=120)
    assert not app.exception, app.exception
    assert "resume_request" not in app.session_state             # still waiting for 3 roles
    from storage import projects
    assert set(projects.sdlc_votes(result.run_id)) == {"project_manager"}


def _projects_page():
    from ui.page_projects import render_projects_page
    render_projects_page()


def _account_page():
    from ui.page_account import render_account_page
    render_account_page()


def test_projects_and_account_pages_render(mock_llm):
    _register("ana", ["analyst"])
    run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1})
    run_pipeline("Loans", options={"num_functional": 2, "num_non_functional": 1})
    app = AppTest.from_function(_projects_page)
    app.session_state["username"] = "ana"
    app.run(timeout=120)
    assert not app.exception, app.exception
    assert len(app.dataframe) >= 2
    app = AppTest.from_function(_account_page)
    app.session_state["username"] = "ana"
    app.run(timeout=120)
    assert not app.exception, app.exception
    assert any("Turn on two-factor" in b.label for b in app.button)


def _saved_loader():
    import streamlit as st
    from ui.page_analysis import render_saved_run_loader
    from ui.results import render_results
    render_saved_run_loader(False)
    if st.session_state.get("result"):
        render_results(st.session_state["result"])


def test_load_saved_run_without_the_model():
    app = AppTest.from_function(_saved_loader)
    app.run(timeout=120)
    assert not app.exception, app.exception
    next(b for b in app.button if b.label == "Load").click().run(timeout=120)
    assert not app.exception, app.exception
    assert app.session_state["result"].run_id == "20261125-193937-4995e9"
    assert any(m.label == "SDLC model" and m.value == "DevSecOps" for m in app.metric)
