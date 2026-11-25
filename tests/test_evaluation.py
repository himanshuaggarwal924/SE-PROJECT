"""Phase 10: gold format, matching, metrics, baseline, runner, CLI, dashboard."""

import csv
import json
import subprocess
import sys

import pytest

import config
from evaluation import gold as gold_files
from evaluation import metrics
from evaluation.baseline import run_baseline
from evaluation.matching import match
from evaluation.runner import run_evaluation


@pytest.fixture
def loan():
    return gold_files.load(config.EVAL_GOLD_DIR / "loan_approval_policy.yaml")


def output(requirements, **kw):
    return metrics.SystemOutput(system="full", requirements=requirements, **kw)


def req(statement, categories=("functional",), sources=(), flags=(), criteria=()):
    return {"statement": statement, "categories": list(categories), "sources": list(sources),
            "flags": list(flags), "acceptance_criteria": list(criteria)}


# -------------------------------------------------------------------- gold --
def test_shipped_gold_files_are_valid_drafts():
    golds = gold_files.load_all()
    assert {g.name for g in golds} == {"loan_approval_policy", "kyc_aml_onboarding_standard",
                                       "payments_platform_spec"}
    for g in golds:
        assert g.is_draft and g.expected_requirements and g.expected_sdlc["top1"]
        assert (config.DOCUMENTS_DIR / g.document).exists()
        assert any(s["ambiguous"] for s in g.seeded_requirements)
        assert any(c["conflict"] for c in g.seeded_conflicts)


def test_gold_rejects_unknown_controls(tmp_path):
    (tmp_path / "bad.yaml").write_text("document: x.md\nscenario: s\nexpected_requirements: [{statement: a}]\n"
                                       "expected_controls: [teleportation]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown controls"):
        gold_files.load(tmp_path / "bad.yaml")


# ---------------------------------------------------------------- matching --
def test_matching_is_one_to_one_and_thresholded():
    gold = ["The system shall encrypt customer data at rest.", "The system shall log every decision."]
    generated = ["The system shall encrypt customer data at rest.", "The system shall encrypt customer data.",
                 "The system shall send newsletters."]
    found = match(generated, gold)
    assert found["method"] == "embedding"          # fake worker (word overlap) in tests
    pairs = {(i, j) for i, j, _ in found["pairs"]}
    assert (0, 0) in pairs and not any(i == 1 and j == 0 for i, j in pairs)     # gold 0 used once
    assert not any(i == 2 for i, _ in pairs)                                     # unrelated: no match


def test_matching_falls_back_to_lexical(monkeypatch):
    import context_loader
    monkeypatch.setattr(context_loader, "_run_retrieval_worker", lambda job: (_ for _ in ()).throw(RuntimeError()))
    found = match(["The system shall log every decision."], ["The system shall log every decision."])
    assert found["method"] == "lexical" and len(found["pairs"]) == 1


# ----------------------------------------------------------------- metrics --
def test_extraction_precision_recall_f1(loan):
    generated = [req(g["statement"], g["categories"]) for g in loan.expected_requirements[:6]]
    generated.append(req("The system shall play music in the lobby."))
    scores = metrics.extraction(output(generated), loan)
    assert scores["matched"] == 6
    assert scores["precision"] == round(6 / 7, 3) and scores["recall"] == round(6 / 12, 3)
    assert scores["category_accuracy"] == 1.0
    assert 0 < scores["completeness"] < 1


def test_ambiguity_and_conflict_detection_on_seeded_items(loan):
    assert metrics.ambiguity_detection(loan) == {"ambiguity_accuracy": 1.0, "ambiguity_precision": 1.0,
                                                 "ambiguity_recall": 1.0}
    assert metrics.conflict_detection(loan) == {"conflict_accuracy": 1.0}


def test_conflict_metric_reports_real_misses():
    """Plain numbers without a unit (25,000 vs 50,000) are not compared by the
    conflict rule - the metric must show that honestly, not hide it."""
    payments = gold_files.load(config.EVAL_GOLD_DIR / "payments_platform_spec.yaml")
    assert metrics.conflict_detection(payments)["conflict_accuracy"] == 0.5


def test_grounding_hallucination_citations_traceability(loan):
    good = req("The system shall refer loans above 50,000.", sources=["C1"],
               criteria=[{"given": "a", "when": "b", "then": "c"}])
    invented = req("The system shall decide within 13 seconds.", sources=["C2"], flags=["invalid_citation"])
    scores = metrics.grounding(output([good, invented]), loan)
    assert scores["hallucination_rate"] == 0.5
    assert scores["citation_correctness"] == round(2 / 3, 3)
    assert scores["traceability_coverage"] == 0.5
    baseline = metrics.grounding(output([good], has_citations=False), loan)
    assert baseline["citation_correctness"] is None


def test_control_coverage_and_sdlc_accuracy(loan):
    out = output([], controls_text="Data is encrypted. Role-based access control. Audit log of changes.",
                 sdlc_ranking=["Agile + V-Model", "Agile + DevSecOps", "V-Model"])
    coverage = metrics.control_coverage(out, loan)
    assert coverage["control_coverage"] == 0.75 and coverage["controls_missing"] == ["data_retention"]
    sdlc = metrics.sdlc_accuracy(out, loan)
    assert sdlc["sdlc_top1"] == 0.0 and sdlc["sdlc_top3"] == 1.0 and sdlc["sdlc_top1_acceptable"] == 1.0


def test_human_correction_rate_ignores_auto_approvals():
    events = [{"event": "human_review", "item_type": "requirement", "action": "accept", "reviewer": "alice"},
              {"event": "human_review", "item_type": "requirement", "action": "edit", "reviewer": "alice"},
              {"event": "human_review", "item_type": "mapping", "action": "reject", "reviewer": "bob"},
              {"event": "human_review", "item_type": "requirement", "action": "accept",
               "reviewer": "auto-approve (non-interactive run)"},
              {"event": "human_review", "item_type": "sdlc", "action": "approve", "reviewer": "bob"}]
    assert metrics.human_correction_rate(events) == {"human_decisions": 3, "human_corrections": 2,
                                                     "human_correction_rate": round(2 / 3, 3)}


# ------------------------------------------------------- baseline and runner --
def test_baseline_is_one_plain_call(mock_llm, loan):
    out = run_baseline(loan, count=4)
    assert len(mock_llm.calls) == 1 and len(out.requirements) == 4
    assert not out.has_citations and not out.has_quality_checks
    prompt = mock_llm.calls[0].user_prompt
    assert "KNOWLEDGE BASE" not in prompt and "[C1]" not in prompt and "Northbridge" in prompt


def test_runner_writes_json_and_csv(mock_llm, loan, tmp_path):
    results = run_evaluation([loan], {"num_functional": 2, "num_non_functional": 1}, out_dir=tmp_path)
    assert set(results["summary"]) == {"full", "baseline"}
    full = results["documents"]["loan_approval_policy"]["full"]
    assert full["sdlc_top1"] is not None and "Requirements Agent" in full["stage_seconds"]
    assert results["documents"]["loan_approval_policy"]["baseline"]["ambiguity_accuracy"] is None
    assert results["meta"]["gold_files"]["loan_approval_policy"].startswith("DRAFT")
    json_file = next(tmp_path.glob("eval_*.json"))
    assert json.loads(json_file.read_text(encoding="utf-8"))["summary"]
    rows = list(csv.reader(open(next(tmp_path.glob("eval_*.csv")), encoding="utf-8")))
    assert rows[0] == ["document", "system", "metric", "value"]
    assert any(r[0] == "ALL (mean)" and r[1] == "baseline" for r in rows)


def test_cli_mock_mode_never_touches_real_logs(tmp_path):
    real_log = config.PROJECT_ROOT / "logs" / "audit_log.jsonl"
    before = real_log.stat().st_size if real_log.exists() else None
    existing = set(config.EVAL_RESULTS_DIR.glob("eval_mock_*"))
    completed = subprocess.run([sys.executable, "run_eval.py", "--mock", "--docs", "loan_approval_policy",
                                "--functional", "1", "--non-functional", "1"],
                               cwd=config.PROJECT_ROOT, capture_output=True, text=True, timeout=300,
                               env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    created = set(config.EVAL_RESULTS_DIR.glob("eval_mock_*")) - existing
    try:
        assert completed.returncode == 0, completed.stderr[-2000:]
        assert "precision" in completed.stdout and len(created) == 2
        after = real_log.stat().st_size if real_log.exists() else None
        assert after == before                               # isolated in a temp folder
        data = json.loads(next(p for p in created if p.suffix == ".json").read_text(encoding="utf-8"))
        assert data["meta"]["mock"] is True
    finally:
        for path in created:
            path.unlink()
