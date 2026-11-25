"""
agents/quality_agent.py - The Python side of the Quality & Clarification Agent.

  plan_calls()      run the deterministic checks once (checks/quality.py),
                    then split the requirements into review batches
  call_variables()  the batch's requirements + what the automatic checks found
  adjust_schema()   exactly one review per requirement, with valid IDs only
  combine()         merge rule findings + model reviews into QualityOutput
                    (rule findings survive even if the model's answer fails)
  route_after()     whether to send requirements back for one revision round
"""

import re

import config
from agents.schemas import QualityBatch, QualityIssue, QualityOutput, RequirementReview, ISSUE_TYPES
from checks import quality
from context_loader import text_similarities

SEVERITY_ORDER = {"High": 3, "Medium": 2, "Low": 1}


def requirements_from(state) -> list[dict]:
    parsed = (state.get("agent_outputs", {}).get("requirements_agent") or {}).get("parsed") or {}
    return parsed.get("requirements", [])


def _similarity_matrix(requirements: list[dict], state) -> tuple[list | None, str]:
    """Embedding similarities if configured and available, else None (lexical).
    Reuses the matrix the Requirements Agent already computed when it can."""
    if config.QUALITY_DUPLICATE_METHOD != "embedding" or len(requirements) < 2:
        return None, "lexical"
    parsed = state.get("agent_outputs", {}).get("requirements_agent", {}).get("parsed") or {}
    matrix = parsed.get("statement_similarity") or []
    if len(matrix) == len(requirements):
        return matrix, "embedding"
    try:
        return text_similarities([r["statement"] for r in requirements]), "embedding"
    except Exception:
        return None, "lexical (embedding unavailable)"


def plan_calls(state) -> list[dict]:
    """Deterministic pre-checks, then one spec per batch of requirements.
    Each spec carries the findings for its own requirements."""
    requirements = requirements_from(state)
    if not requirements:
        return []
    matrix, method = _similarity_matrix(requirements, state)
    duplicate_pairs = quality.duplicates(requirements, matrix)
    conflict_pairs = quality.conflicts(requirements)

    size = max(1, config.QUALITY_BATCH_SIZE)
    specs = []
    for start in range(0, len(requirements), size):
        batch = requirements[start:start + size]
        ids = [r["id"] for r in batch]
        specs.append({
            "ids": ids,
            "rule_issues": {r["id"]: [i.model_dump() for i in quality.rule_issues(r)] for r in batch},
            "duplicates": [p for p in duplicate_pairs if set(p["ids"]) & set(ids)],
            "conflicts": [p for p in conflict_pairs if set(p["ids"]) & set(ids)],
            "duplicate_method": method,
        })
    return specs


def _describe(requirement: dict) -> str:
    lines = [f"{requirement['id']} ({requirement.get('kind', '')}, "
             f"{', '.join(requirement.get('categories', []))}): {requirement['statement']}"]
    for c in requirement.get("acceptance_criteria", []):
        lines.append(f"  Acceptance: given {c.get('given')}, when {c.get('when')}, then {c.get('then')}")
    if requirement.get("source_stakeholder"):
        # Roles only - a person's name (kept locally) never goes into a prompt.
        roles = re.findall(r"\(([^)]+)\)", requirement["source_stakeholder"]) or [requirement["source_stakeholder"]]
        lines.append(f"  Stakeholder role: {', '.join(roles)}")
    return "\n".join(lines)


def call_variables(spec: dict, state, earlier) -> dict:
    by_id = {r["id"]: r for r in requirements_from(state)}
    findings = []
    for rid, issues in spec["rule_issues"].items():
        findings += [f"{rid}: {i['type']} ({i['severity']}) - {i['explanation']}" for i in issues]
    findings += [f"{' and '.join(p['ids'])}: possible duplicates (similarity {p['similarity']})"
                 for p in spec["duplicates"]]
    findings += [f"{' and '.join(p['ids'])}: possible conflict - {p['detail']}" for p in spec["conflicts"]]
    return {
        "batch_requirements": "\n".join(_describe(by_id[rid]) for rid in spec["ids"] if rid in by_id),
        "rule_findings": "\n".join(findings) or "None.",
        "issue_types": ", ".join(ISSUE_TYPES),
        "batch_instruction": (f"Review exactly these {len(spec['ids'])} requirements, one review each, "
                              f"in this order: {', '.join(spec['ids'])}."),
    }


def adjust_schema(schema: dict, spec: dict) -> dict:
    """Exactly one review per requirement in the batch, and only valid IDs."""
    schema = {**schema, "properties": dict(schema["properties"]), "$defs": dict(schema["$defs"])}
    schema["properties"]["reviews"] = {**schema["properties"]["reviews"],
                                       "minItems": len(spec["ids"]), "maxItems": len(spec["ids"])}
    draft = dict(schema["$defs"]["RequirementReviewDraft"])
    draft["properties"] = {**draft["properties"],
                           "requirement_id": {"type": "string", "enum": spec["ids"]}}
    schema["$defs"]["RequirementReviewDraft"] = draft
    return schema


def _max_severity(issues) -> str:
    return max((i.severity for i in issues), key=lambda s: SEVERITY_ORDER.get(s, 0), default="")


def combine(calls: list[tuple[dict, QualityBatch | None]], state) -> QualityOutput:
    """Merge the deterministic findings and the model's reviews."""
    duplicates, conflicts, reviews = [], [], []
    for spec, parsed in calls:
        for pair in spec["duplicates"]:
            if pair not in duplicates:
                duplicates.append(pair)
        for pair in spec["conflicts"]:
            if pair not in conflicts:
                conflicts.append(pair)

    for spec, parsed in calls:
        drafts = {d.requirement_id: d for d in (parsed.reviews if parsed else [])}
        for rid in spec["ids"]:
            issues = [QualityIssue(**i) for i in spec["rule_issues"].get(rid, [])]
            for pair in duplicates:
                if rid in pair["ids"]:
                    other = [x for x in pair["ids"] if x != rid]
                    issues.append(QualityIssue(type="duplication", severity="Medium", origin="rule",
                                               related_ids=other,
                                               explanation=f"Very similar to {other[0]} "
                                                           f"(similarity {pair['similarity']})."))
            for pair in conflicts:
                if rid in pair["ids"]:
                    other = [x for x in pair["ids"] if x != rid]
                    issues.append(QualityIssue(type="inconsistency", severity="High", origin="rule",
                                               related_ids=other,
                                               explanation=f"Possible conflict with {other[0]}: {pair['detail']}"))
            draft = drafts.get(rid)
            questions = []
            if draft is not None:
                issues += [QualityIssue(**i.model_dump(), origin="llm") for i in draft.issues
                           if i.explanation.strip()]
                questions = [q for q in draft.clarification_questions if q.question.strip()]
            reviews.append(RequirementReview(requirement_id=rid, issues=issues,
                                             clarification_questions=questions,
                                             max_severity=_max_severity(issues)))

    by_type, by_severity = {}, {}
    for review in reviews:
        for issue in review.issues:
            by_type[issue.type] = by_type.get(issue.type, 0) + 1
            by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
    return QualityOutput(
        reviews=reviews, duplicates=duplicates, conflicts=conflicts,
        summary={
            "requirements_reviewed": len(reviews),
            "issues_by_type": by_type,
            "issues_by_severity": by_severity,
            "high_severity_ids": [r.requirement_id for r in reviews if r.max_severity == "High"],
            "clarification_questions": sum(len(r.clarification_questions) for r in reviews),
            "failed_batches": sum(1 for _, p in calls if p is None),
            "duplicate_method": calls[0][0]["duplicate_method"] if calls else "",
        },
    )


def render_for_next(output: QualityOutput) -> str:
    lines = []
    for review in output.reviews:
        if review.issues:
            kinds = ", ".join(sorted({i.type for i in review.issues}))
            lines.append(f"{review.requirement_id}: {len(review.issues)} issue(s), "
                         f"worst {review.max_severity} ({kinds})")
    return "\n".join(lines) or "No quality issues found."


def route_after(state) -> str:
    """'revise' if one revision round is allowed and needed, else 'continue'."""
    if not config.QUALITY_REVISION_ENABLED:
        return "continue"
    if state.get("revision_count", 0) >= config.QUALITY_MAX_REVISIONS:
        return "continue"
    parsed = (state.get("agent_outputs", {}).get("quality_agent") or {}).get("parsed") or {}
    return "revise" if parsed.get("summary", {}).get("high_severity_ids") else "continue"
