"""
evaluation/runner.py - Runs the full system and the baseline on every gold
document, computes the metrics and writes results JSON + CSV.
"""

import csv
import json
from datetime import datetime
from pathlib import Path

import audit_log
import config
from evaluation import metrics
from evaluation.baseline import run_baseline
from evaluation.gold import Gold
from pipeline import run_pipeline

SCALAR_METRICS = ["precision", "recall", "f1", "category_accuracy", "completeness", "ambiguity_accuracy",
                  "ambiguity_precision", "ambiguity_recall", "conflict_accuracy", "control_coverage",
                  "hallucination_rate", "citation_correctness", "sdlc_top1", "sdlc_top3",
                  "sdlc_top1_acceptable", "traceability_coverage", "total_seconds"]


def stage_seconds(run_id: str) -> dict:
    seconds = {}
    for event in audit_log.read_events(run_id):
        if event["event"] == "context_prepared":
            seconds["prepare_context"] = event.get("seconds", 0)
        elif event["event"] == "agent_completed":
            seconds[event["agent"]] = event.get("elapsed_seconds", 0)
    return seconds


def full_system_output(result) -> metrics.SystemOutput:
    requirements_output = result.get("requirements_agent").parsed
    requirements = [{"statement": r.statement, "categories": r.categories, "sources": r.sources,
                     "flags": [f.type for f in r.flags],
                     "acceptance_criteria": [c.model_dump() for c in r.acceptance_criteria]}
                    for r in (requirements_output.requirements if requirements_output else [])]
    texts = [r["statement"] for r in requirements]
    compliance = result.get("compliance_agent").parsed if result.get("compliance_agent") else None
    if compliance:
        texts += [c for m in compliance.mappings for c in m.required_controls]
        texts += [s.statement for s in compliance.suggested_requirements]
    sdlc = result.get("sdlc_agent").parsed if result.get("sdlc_agent") else None
    return metrics.SystemOutput(system="full", requirements=requirements,
                                sdlc_ranking=[r.model for r in sdlc.ranking] if sdlc else [],
                                controls_text=" ".join(texts), stage_seconds=stage_seconds(result.run_id))


def evaluate_document(gold: Gold, options: dict, with_baseline: bool, model_name: str) -> dict:
    result = run_pipeline(gold.scenario, gold.document_text(), gold.document, model_name,
                          user="evaluation", options={**options, "review_mode": "none"})
    scores = {"run_id": result.run_id, "full": metrics.evaluate(full_system_output(result), gold)}
    if with_baseline:
        count = options.get("num_functional", config.NUM_FUNCTIONAL_REQUIREMENTS) + \
            options.get("num_non_functional", config.NUM_NON_FUNCTIONAL_REQUIREMENTS)
        scores["baseline"] = metrics.evaluate(run_baseline(gold, count, model_name), gold)
    return scores


def _mean(values):
    numbers = [v for v in values if isinstance(v, (int, float))]
    return round(sum(numbers) / len(numbers), 3) if numbers else None


def run_evaluation(golds: list[Gold], options: dict | None = None, with_baseline: bool = True,
                   model_name: str = config.MODEL_NAME, out_dir: Path | None = None,
                   on_document=None, mock: bool = False) -> dict:
    options = dict(options or {})
    documents = {}
    for gold in golds:
        if on_document:
            on_document(gold)
        documents[gold.name] = evaluate_document(gold, options, with_baseline, model_name)
    systems = ["full"] + (["baseline"] if with_baseline else [])
    summary = {system: {m: _mean(d[system].get(m) for d in documents.values()) for m in SCALAR_METRICS}
               for system in systems}
    results = {
        "meta": {"created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                 "model": "MOCK (canned answers - numbers are meaningless)" if mock else model_name,
                 "mock": mock, "options": options,
                 "gold_files": {g.name: ("DRAFT - not reviewed" if g.is_draft else f"reviewed by {g.reviewed_by}")
                                for g in golds},
                 "match_threshold": config.EVAL_MATCH_THRESHOLD,
                 **metrics.human_correction_rate(audit_log.read_events())},
        "summary": summary, "documents": documents,
    }
    results["meta"]["files"] = [str(p) for p in write_results(results, out_dir or config.EVAL_RESULTS_DIR)]
    return results


def write_results(results: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = "eval_mock_" if results["meta"].get("mock") else "eval_"
    json_path = out_dir / f"{prefix}{stamp}.json"
    csv_path = out_dir / f"{prefix}{stamp}.csv"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["document", "system", "metric", "value"])
        for name, scores in results["documents"].items():
            for system in ("full", "baseline"):
                for metric in SCALAR_METRICS:
                    if system in scores:
                        writer.writerow([name, system, metric, scores[system].get(metric)])
        for system, values in results["summary"].items():
            for metric, value in values.items():
                writer.writerow(["ALL (mean)", system, metric, value])
    return json_path, csv_path


def load_results(out_dir: Path | None = None) -> list[tuple[Path, dict]]:
    """Saved evaluation results, newest first."""
    folder = out_dir or config.EVAL_RESULTS_DIR
    found = []
    for path in sorted(folder.glob("eval_*.json"), reverse=True):
        try:
            found.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return found
