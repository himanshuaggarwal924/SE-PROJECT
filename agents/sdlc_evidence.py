"""
agents/sdlc_evidence.py - Candidate evidence IDs for each SDLC decision factor.

The 3B model often rates a factor without citing any requirement, and
factors without evidence are not scored. So Python pre-computes, per factor,
which requirement / excerpt IDs are LIKELY relevant (from categories, risk
levels, rules, quality issues and compliance outputs) and shows them next to
the factor definition in the prompt. These are hints only: Python never adds
evidence the model did not cite itself.
"""

import config

MAX_CANDIDATES = 4
CHANGE_WORDS = ("configur", "rule", "threshold", "limit", "policy", "cut-off")
LEGACY_WORDS = ("legacy", "core banking", "existing", "mainframe", "batch")
SCHEDULE_WORDS = ("deadline", "budget", "go-live", "launch", "date")


def _parsed(state, key: str) -> dict:
    return (state.get("agent_outputs", {}).get(key) or {}).get("parsed") or {}


def _has(requirement: dict, *categories: str) -> bool:
    return bool(set(categories) & set(requirement.get("categories", [])))


def _mentions(requirement: dict, words) -> bool:
    text = (requirement.get("statement", "") + " " + requirement.get("business_justification", "")).lower()
    return any(w in text for w in words)


def candidate_evidence(state) -> dict[str, list[str]]:
    """{factor: [IDs]} - up to MAX_CANDIDATES per factor, most relevant first."""
    requirements = _parsed(state, "requirements_agent").get("requirements", [])
    quality = _parsed(state, "quality_agent")
    compliance = _parsed(state, "compliance_agent")
    issues = {r["requirement_id"]: r for r in quality.get("reviews", [])}
    officer = {m["requirement_id"] for m in compliance.get("mappings", [])
               if m.get("requires_compliance_officer_approval")}
    chunk_map = state.get("chunk_map") or {}
    kb_regulatory = [cid for cid, c in chunk_map.items()
                     if c.get("origin") == "kb" and c.get("type") in ("regulation", "policy")]

    def ids(predicate):
        return [r["id"] for r in requirements if predicate(r)]

    unclear = ids(lambda r: any(i["type"] in ("ambiguity", "incompleteness", "undefined_terminology")
                                for i in issues.get(r["id"], {}).get("issues", [])))
    candidates = {
        "requirement_stability": unclear or ids(lambda r: r.get("assumptions")),
        "regulatory_criticality": ids(lambda r: _has(r, "regulatory", "audit/reporting")
                                      or r.get("applicable_rules") or r["id"] in officer) + kb_regulatory,
        "security_risk": ids(lambda r: _has(r, "security", "privacy")),
        "complexity": ids(lambda r: r.get("dependencies") or _has(r, "integration")),
        "system_size": [r["id"] for r in requirements],
        "legacy_dependence": ids(lambda r: _has(r, "integration") or _mentions(r, LEGACY_WORDS)),
        "change_frequency": ids(lambda r: _has(r, "business", "stakeholder") or _mentions(r, CHANGE_WORDS)),
        "continuous_delivery_need": ids(lambda r: _has(r, "operational/maintenance", "availability/reliability")),
        "stakeholder_availability": ids(lambda r: r.get("source_stakeholder")),
        "testing_documentation_needs": ids(lambda r: _has(r, "audit/reporting", "regulatory")
                                           or len(r.get("acceptance_criteria", [])) > 1),
        "budget_schedule_constraints": ids(lambda r: _mentions(r, SCHEDULE_WORDS)),
        "formal_verification_need": ids(lambda r: _has(r, "regulatory") and r.get("risk_level") == "High"),
        "failure_consequences": ids(lambda r: r.get("risk_level") == "High"),
    }
    return {factor: list(dict.fromkeys(found))[:MAX_CANDIDATES] for factor, found in candidates.items()}


def coverage(factors) -> int:
    """How many factors have at least one valid evidence ID (FactorRating objects)."""
    return sum(1 for f in factors if f.scored)


__all__ = ["candidate_evidence", "coverage", "config"]
