"""
evaluation/metrics.py - The evaluation metrics (problem statement, Phase 10).

Both systems (full pipeline and single-prompt baseline) are first turned into
a SystemOutput, so every metric is computed the same way for both. A metric
that doesn't apply to a system (e.g. citation correctness for a baseline
without citations) is None and shown as "n/a".

  requirement extraction  precision / recall / F1 (MiniLM matching, threshold in config)
  category_accuracy       mean Jaccard of categories over matched pairs
  completeness            share of the gold's requirement categories that are covered
  ambiguity_*             detection on seeded ambiguous / clear requirements
  conflict_accuracy       detection on seeded conflicting / compatible pairs
  control_coverage        share of expected baseline controls covered
  hallucination_rate      requirements with a number not in the source, or an
                          invalid citation / unsupported rule
  citation_correctness    valid citations / all citations the model made
  sdlc_top1 / sdlc_top3   gold top-1 model ranked 1st / within the top 3
  traceability_coverage   requirements with a valid citation AND acceptance criteria
  stage_seconds           processing time per stage (from the audit log)
  human_correction_rate   edited / regenerated / rejected share of human decisions (audit log)
"""

from dataclasses import dataclass, field

import config
from checks.grounding import extract_numbers
from checks.quality import conflicts, rule_issues
from evaluation.gold import Gold
from evaluation.matching import match

AMBIGUITY_TYPES = {"ambiguity", "lack_of_testability"}
BAD_CITATION_FLAGS = {"invalid_citation", "unsupported_rule", "possible_hallucination"}


@dataclass
class SystemOutput:
    system: str                                  # "full" | "baseline"
    requirements: list[dict]                     # statement, categories, sources, flags, acceptance_criteria
    sdlc_ranking: list[str] = field(default_factory=list)
    controls_text: str = ""                      # where controls may be mentioned
    has_citations: bool = True
    has_quality_checks: bool = True
    stage_seconds: dict = field(default_factory=dict)


def _safe_div(a: float, b: float) -> float | None:
    return round(a / b, 3) if b else None


def extraction(output: SystemOutput, gold: Gold) -> dict:
    generated = [r["statement"] for r in output.requirements]
    expected = [g["statement"] for g in gold.expected_requirements]
    found = match(generated, expected)
    tp = len(found["pairs"])
    precision = _safe_div(tp, len(generated))
    recall = _safe_div(tp, len(expected))
    f1 = round(2 * precision * recall / (precision + recall), 3) if precision and recall else 0.0
    jaccards = []
    for i, j, _ in found["pairs"]:
        a = set(output.requirements[i].get("categories", []))
        b = set(gold.expected_requirements[j].get("categories", []))
        jaccards.append(len(a & b) / len(a | b) if a | b else 1.0)
    gold_categories = {c for g in gold.expected_requirements for c in g.get("categories", [])}
    covered = gold_categories & {c for r in output.requirements for c in r.get("categories", [])}
    return {"precision": precision or 0.0, "recall": recall or 0.0, "f1": f1,
            "matched": tp, "generated": len(generated), "expected": len(expected),
            "match_method": found["method"], "match_threshold": found["threshold"],
            "category_accuracy": round(sum(jaccards) / len(jaccards), 3) if jaccards else None,
            "completeness": _safe_div(len(covered), len(gold_categories)),
            "matches": [{"generated": generated[i], "gold": gold.expected_requirements[j]["id"], "similarity": s}
                        for i, j, s in found["pairs"]]}


def ambiguity_detection(gold: Gold) -> dict:
    """The system's deterministic quality rules on the seeded requirements."""
    if not gold.seeded_requirements:
        return {}
    correct = tp = fp = fn = 0
    for seeded in gold.seeded_requirements:
        requirement = {"id": "S", "statement": seeded["statement"], "kind": seeded.get("kind", "functional"),
                       "categories": seeded.get("categories", []), "sources": ["X"], "acceptance_criteria": []}
        predicted = any(i.type in AMBIGUITY_TYPES for i in rule_issues(requirement))
        actual = bool(seeded["ambiguous"])
        correct += predicted == actual
        tp += predicted and actual
        fp += predicted and not actual
        fn += actual and not predicted
    return {"ambiguity_accuracy": _safe_div(correct, len(gold.seeded_requirements)),
            "ambiguity_precision": _safe_div(tp, tp + fp), "ambiguity_recall": _safe_div(tp, tp + fn)}


def conflict_detection(gold: Gold) -> dict:
    if not gold.seeded_conflicts:
        return {}
    correct = 0
    for pair in gold.seeded_conflicts:
        found = conflicts([{"id": "A", "statement": pair["a"]}, {"id": "B", "statement": pair["b"]}])
        correct += bool(found) == bool(pair["conflict"])
    return {"conflict_accuracy": _safe_div(correct, len(gold.seeded_conflicts))}


def control_coverage(output: SystemOutput, gold: Gold) -> dict:
    if not gold.expected_controls:
        return {}
    text = output.controls_text.lower()
    covered = [c for c in gold.expected_controls
               if any(k in text for k in config.COMPLIANCE_BASELINE_CONTROLS[c]["keywords"])]
    return {"control_coverage": _safe_div(len(covered), len(gold.expected_controls)),
            "controls_missing": [c for c in gold.expected_controls if c not in covered]}


def grounding(output: SystemOutput, gold: Gold) -> dict:
    """Hallucination rate (both systems, same rule) and citation correctness."""
    source_numbers = extract_numbers(gold.document_text()) | extract_numbers(gold.scenario)
    hallucinated = valid = invalid = 0
    for r in output.requirements:
        text = " ".join([r["statement"]] + [" ".join(c.values()) for c in r.get("acceptance_criteria", [])])
        ungrounded = bool(extract_numbers(text) - source_numbers)
        bad_flag = any(f in BAD_CITATION_FLAGS for f in r.get("flags", []))
        hallucinated += ungrounded or bad_flag
        valid += len(r.get("sources", []))
        invalid += sum(1 for f in r.get("flags", []) if f == "invalid_citation")
    n = len(output.requirements)
    return {"hallucination_rate": _safe_div(hallucinated, n),
            "citation_correctness": _safe_div(valid, valid + invalid) if output.has_citations else None,
            "traceability_coverage": _safe_div(sum(1 for r in output.requirements
                                                   if r.get("sources") and r.get("acceptance_criteria")), n)}


def sdlc_accuracy(output: SystemOutput, gold: Gold) -> dict:
    top1 = gold.expected_sdlc.get("top1")
    if not top1 or not output.sdlc_ranking:
        return {"sdlc_top1": None, "sdlc_top3": None}
    return {"sdlc_top1": float(output.sdlc_ranking[0] == top1),
            "sdlc_top3": float(top1 in output.sdlc_ranking[:3]),
            "sdlc_top1_acceptable": float(output.sdlc_ranking[0] in gold.expected_sdlc.get("acceptable", [top1])),
            "sdlc_predicted": output.sdlc_ranking[0]}


def evaluate(output: SystemOutput, gold: Gold) -> dict:
    metrics = {**extraction(output, gold), **control_coverage(output, gold),
               **grounding(output, gold), **sdlc_accuracy(output, gold)}
    if output.has_quality_checks:
        metrics.update(ambiguity_detection(gold))
        metrics.update(conflict_detection(gold))
    else:
        metrics.update({"ambiguity_accuracy": None, "conflict_accuracy": None})
    metrics["stage_seconds"] = output.stage_seconds
    metrics["total_seconds"] = round(sum(output.stage_seconds.values()), 1)
    return metrics


def human_correction_rate(events: list[dict]) -> dict:
    """Share of human review decisions on requirements/mappings that changed or
    rejected the AI's output (edit, regenerate, reject) - from the audit log."""
    decisions = [e for e in events if e.get("event") == "human_review"
                 and e.get("item_type") in ("requirement", "mapping") and not e.get("reviewer", "").startswith("auto")]
    corrected = [e for e in decisions if e.get("action") in ("edit", "regenerate", "reject")]
    return {"human_decisions": len(decisions), "human_corrections": len(corrected),
            "human_correction_rate": _safe_div(len(corrected), len(decisions))}
