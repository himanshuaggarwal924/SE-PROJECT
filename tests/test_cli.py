"""Phase 11: run_demo.py command-line options."""

import run_demo


def test_run_demo_auto_approve_with_artefacts(mock_llm, tmp_path, capsys):
    assert run_demo.main(["--auto-approve", "--fast", "--functional", "1", "--non-functional", "1",
                          "--artefacts", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Review: auto-approve" in out and "Run id:" in out
    assert "review_requirements" in out and "review_sdlc" in out         # review steps ran
    assert (tmp_path / "srs.docx").exists() and (tmp_path / "traceability_matrix.csv").exists()
    rtm = (tmp_path / "traceability_matrix.csv").read_text(encoding="utf-8-sig")
    assert "(auto)" in rtm                                                # auto-approval is visible


def test_run_demo_default_leaves_items_pending(mock_llm, tmp_path, capsys):
    doc = tmp_path / "spec.md"
    doc.write_text("Loans above 50,000 need an underwriter.", encoding="utf-8")
    assert run_demo.main([str(doc), "Loan approval", "--fast", "--functional", "1",
                          "--non-functional", "1"]) == 0
    out = capsys.readouterr().out
    assert "Review: none (items stay pending)" in out and "review_requirements" not in out
    assert '"approval_status": "pending"' in out


def test_saved_run_roundtrip_and_listing(mock_llm, tmp_path, monkeypatch):
    import config
    from pipeline import load_saved_result, run_pipeline, save_result, saved_runs
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1, "review_mode": "auto"})
    save_result(result, tmp_path / "demo_run" / "result.json")
    loaded = load_saved_result(tmp_path / "demo_run" / "result.json")
    assert loaded.run_id == result.run_id and loaded.status == "done"
    assert [r.key for r in loaded.agent_results] == [r.key for r in result.agent_results]
    assert loaded.get("requirements_agent").parsed == result.get("requirements_agent").parsed
    assert loaded.chunk_map == result.chunk_map and loaded.versions == result.versions
    monkeypatch.setattr(config, "SAVED_RUNS_DIR", tmp_path)
    assert saved_runs() == [tmp_path / "demo_run" / "result.json"]


def test_replay_rebuilds_a_run_from_its_audit_log(mock_llm):
    import audit_log
    import config
    from pathlib import Path
    from pipeline import run_pipeline
    from tools.replay_run import replay
    doc = Path(config.DOCUMENTS_DIR / "loan_approval_policy.md")
    options = {"num_functional": 2, "num_non_functional": 1, "review_mode": "auto"}
    original = run_pipeline("Loans", doc.read_text(encoding="utf-8"), doc.name, options=options)
    calls_before = len(mock_llm.calls)
    replayed = replay(config.AUDIT_LOG_FILE, doc, "Loans", options)
    assert len(mock_llm.calls) == calls_before                    # no model call during the replay
    assert replayed.run_id == original.run_id

    def content(result):          # everything except the auto-approval timestamps
        data = result.get("requirements_agent").parsed.model_dump()
        for r in data["requirements"]:
            r.pop("reviewed_at")
        return data
    assert content(replayed) == content(original)
    assert replayed.get("sdlc_agent").parsed.ranking == original.get("sdlc_agent").parsed.ranking


def test_shipped_demo_run_loads():
    import config
    from pipeline import load_saved_result
    result = load_saved_result(config.PROJECT_ROOT / "demo" / "final_run" / "result.json")
    assert result.status == "done" and len(result.get("requirements_agent").parsed.requirements) == 9
    assert all(r.status == "ok" for r in result.agent_results)
