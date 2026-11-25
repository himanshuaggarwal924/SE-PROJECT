"""
agents/compliance_agent.py - The Python side of the Compliance & Security Agent.

The model maps each requirement to knowledge-base rules, controls, evidence,
gaps, approval checkpoints and retention/reporting obligations. Python then:
  * keeps only rules that are real KB excerpts the agent was shown, and only
    evidence IDs that exist (everything else is removed and flagged),
  * marks every high-impact mapping requires_compliance_officer_approval,
  * adds a "not assessed" mapping for any requirement whose batch failed,
  * suggests missing baseline security/privacy requirements (encryption, MFA,
    audit logging, ...) with a deterministic checklist (config.py).

It never presents a legal determination (see COMPLIANCE_DISCLAIMER).
"""

import config
from agents.quality_agent import requirements_from
from agents.schemas import (ComplianceBatch, ComplianceMapping, ComplianceOutput, Flag,
                            SuggestedRequirement, normalise_citation)
from context_loader import chunks_visible_to

HIGH_IMPACT_CATEGORIES = {"regulatory", "security", "privacy"}


def plan_calls(state) -> list[dict]:
    ids = [r["id"] for r in requirements_from(state)]
    size = max(1, config.COMPLIANCE_BATCH_SIZE)
    return [{"ids": ids[i:i + size]} for i in range(0, len(ids), size)]


def call_variables(spec: dict, state, earlier) -> dict:
    by_id = {r["id"]: r for r in requirements_from(state)}
    lines = []
    for rid in spec["ids"]:
        r = by_id[rid]
        rules = f" Rules already linked: {', '.join(r['applicable_rules'])}." if r.get("applicable_rules") else ""
        lines.append(f"{rid} ({', '.join(r.get('categories', []))}; risk {r.get('risk_level')}): "
                     f"{r['statement']}{rules}")
    return {
        "batch_requirements": "\n".join(lines),
        "batch_instruction": (f"Map exactly these {len(spec['ids'])} requirements, one mapping each, "
                              f"in this order: {', '.join(spec['ids'])}."),
    }


def adjust_schema(schema: dict, spec: dict) -> dict:
    schema = {**schema, "properties": dict(schema["properties"]), "$defs": dict(schema["$defs"])}
    schema["properties"]["mappings"] = {**schema["properties"]["mappings"],
                                        "minItems": len(spec["ids"]), "maxItems": len(spec["ids"])}
    draft = dict(schema["$defs"]["ComplianceMappingDraft"])
    draft["properties"] = {**draft["properties"],
                           "requirement_id": {"type": "string", "enum": spec["ids"]}}
    schema["$defs"]["ComplianceMappingDraft"] = draft
    return schema


def check_mapping(mapping, requirement: dict, chunk_map: dict) -> ComplianceMapping:
    """Validate rules/evidence against the excerpts shown and set the approval flag."""
    flags, rules, evidence = [], [], []
    for rule in mapping.applicable_rules:
        rid = normalise_citation(rule)
        if chunk_map.get(rid, {}).get("origin") == "kb":
            rules.append(rid)
        else:
            flags.append(Flag(type="unsupported_rule", detail=f"'{rule}' is not a knowledge-base excerpt (removed)"))
    for cid in mapping.evidence:
        if cid in chunk_map:
            evidence.append(cid)
        else:
            flags.append(Flag(type="invalid_citation", detail=f"{cid} is not one of the excerpts shown (removed)"))
    if rules and not evidence:
        evidence = list(rules)       # a cited rule is its own evidence
    if not rules:
        flags.append(Flag(type="no_kb_rule", detail="No knowledge-base rule supports this mapping."))

    high_impact = (mapping.impact == "High" or requirement.get("risk_level") == "High"
                   or bool(HIGH_IMPACT_CATEGORIES & set(requirement.get("categories", []))))
    return ComplianceMapping(**{**mapping.model_dump(),
                                "applicable_rules": list(dict.fromkeys(rules)),
                                "evidence": list(dict.fromkeys(evidence)),
                                "flags": flags,
                                "requires_compliance_officer_approval": high_impact})


def suggest_missing_controls(requirements: list[dict], chunk_map: dict) -> list[SuggestedRequirement]:
    """Deterministic checklist: a baseline control that no requirement mentions
    becomes a suggested requirement (citing KB excerpts that mention it)."""
    texts = " ".join(
        " ".join([r.get("statement", "")] + [c.get("then", "") for c in r.get("acceptance_criteria", [])])
        for r in requirements).lower()
    suggestions = []
    for control, spec in config.COMPLIANCE_BASELINE_CONTROLS.items():
        if any(keyword in texts for keyword in spec["keywords"]):
            continue
        sources = [cid for cid, chunk in chunk_map.items() if chunk.get("origin") == "kb"
                   and any(k in chunk["text"].lower() for k in spec["keywords"])]
        rationale = f"No requirement covers the baseline control '{control.replace('_', ' ')}'."
        if sources:
            rationale += f" The knowledge base mentions it in {', '.join(sources)}."
        suggestions.append(SuggestedRequirement(
            id=f"SUG-{len(suggestions) + 1:02d}", control=control, statement=spec["statement"],
            categories=spec["categories"], sources=sources, rationale=rationale))
    return suggestions


def combine(calls: list[tuple[dict, ComplianceBatch | None]], state) -> ComplianceOutput:
    chunk_map = chunks_visible_to(state.get("chunk_map") or {}, "compliance")
    requirements = requirements_from(state)
    by_id = {r["id"]: r for r in requirements}

    mappings = []
    for spec, parsed in calls:
        drafts = {m.requirement_id: m for m in (parsed.mappings if parsed else [])}
        for rid in spec["ids"]:
            draft = drafts.get(rid)
            if draft is None:
                mappings.append(ComplianceMapping(
                    requirement_id=rid, impact="High", requires_compliance_officer_approval=True,
                    compliance_gaps=["Not assessed: the model's answer could not be used."],
                    flags=[Flag(type="not_assessed", detail="Batch failed to parse")]))
                continue
            mappings.append(check_mapping(draft, by_id.get(rid, {}), chunk_map))

    suggestions = suggest_missing_controls(requirements, chunk_map)
    return ComplianceOutput(
        mappings=mappings, suggested_requirements=suggestions,
        summary={
            "mapped": len(mappings),
            "need_compliance_officer_approval": sum(m.requires_compliance_officer_approval for m in mappings),
            "with_kb_rule": sum(bool(m.applicable_rules) for m in mappings),
            "gaps": sum(len(m.compliance_gaps) for m in mappings),
            "suggested_requirements": len(suggestions),
            "failed_batches": sum(1 for _, p in calls if p is None),
        },
    )


def render_for_next(output: ComplianceOutput) -> str:
    lines = [f"{m.requirement_id}: impact {m.impact}; rules {', '.join(m.applicable_rules) or 'none'}; "
             f"gaps: {'; '.join(m.compliance_gaps) or 'none'}" for m in output.mappings]
    lines += [f"{s.id} (suggested): {s.statement}" for s in output.suggested_requirements]
    return "\n".join(lines) or "No compliance mappings."
