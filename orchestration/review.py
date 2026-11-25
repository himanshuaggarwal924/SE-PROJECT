"""
orchestration/review.py - Human-in-the-loop review steps (Phase 6).

Two graph nodes pause the run with LangGraph's interrupt():
  review_requirements  after the Compliance Agent: every requirement, every
                       compliance mapping and every suggested requirement can
                       be accepted, rejected or edited (regenerate = an edit
                       whose new text came from the model, see regenerate.py)
  review_sdlc          after the SDLC Agent: approve the recommendation,
                       choose another ranked model, or reject

The paused state is saved by the checkpointer; the run continues when the
graph is invoked again with Command(resume=decisions) on the same thread.
In review_mode "auto" (run_demo --auto-approve) every item is approved
without pausing and marked auto_approved.

Every decision is written to the audit log as "human_review" with before/after
values, and to the approvals table.
"""

from langgraph.types import interrupt

import audit_log
from agents.requirements_agent import build_output, check_requirement, render_for_next
from agents.schemas import (ComplianceMapping, ComplianceOutput, Requirement, RequirementsOutput,
                            SDLCOutput)
from context_loader import chunks_visible_to
from security.crypto import seal_json
from storage import db

REVIEW_REQUIREMENTS = "review_requirements"
REVIEW_SDLC = "review_sdlc"
AUTO_REVIEWER = "auto-approve (non-interactive run)"
EDITABLE_REQUIREMENT_FIELDS = ["statement", "categories", "priority", "risk_level", "business_justification",
                               "acceptance_criteria", "assumptions", "dependencies", "sources",
                               "applicable_rules", "source_stakeholder"]
EDITABLE_MAPPING_FIELDS = ["applicable_rules", "required_controls", "evidence", "compliance_gaps",
                           "approval_checkpoints", "retention_reporting_obligations", "impact"]


def _parsed(state, key: str) -> dict | None:
    return (state.get("agent_outputs", {}).get(key) or {}).get("parsed")


# ----------------------------------------------------------- mandatory items --
def mandatory_items(state) -> list[dict]:
    """Items that need an explicit human decision before a baseline can be
    locked (problem statement: regulatory interpretations, high-risk security
    requirements, conflicting stakeholder decisions, architecture-critical
    requirements, the SDLC selection; the baseline itself is the final one)."""
    items = []
    requirements = (_parsed(state, "requirements_agent") or {}).get("requirements", [])
    quality = _parsed(state, "quality_agent") or {}
    conflicted = {rid for pair in quality.get("conflicts", []) for rid in pair["ids"]}
    for r in requirements:
        cats = set(r.get("categories", []))
        reasons = []
        if r.get("risk_level") == "High" and cats & {"security", "privacy"}:
            reasons.append("high-risk security requirement")
        if "integration" in cats or ("availability/reliability" in cats and r.get("priority") == "High"):
            reasons.append("architecture-critical requirement")
        if r["id"] in conflicted:
            reasons.append("conflicting stakeholder decision")
        if reasons:
            items.append({"type": "requirement", "id": r["id"], "reasons": reasons,
                          "status": r.get("approval_status", "pending")})
    for m in (_parsed(state, "compliance_agent") or {}).get("mappings", []):
        if m.get("requires_compliance_officer_approval"):
            items.append({"type": "mapping", "id": m["requirement_id"],
                          "reasons": ["regulatory interpretation"], "status": m.get("approval_status", "pending")})
    sdlc = _parsed(state, "sdlc_agent")
    if sdlc:
        items.append({"type": "sdlc", "id": "SDLC", "reasons": ["SDLC selection"],
                      "status": sdlc.get("approval_status", "pending")})
    return items


def blocking_items(state) -> list[dict]:
    """Mandatory items not yet decided. A requirement or mapping is decided
    when approved or rejected; the SDLC choice must be approved or overridden."""
    decided = {"requirement": {"approved", "rejected"}, "mapping": {"approved", "rejected"},
               "sdlc": {"approved", "overridden"}}
    return [i for i in mandatory_items(state) if i["status"] not in decided[i["type"]]]


# ------------------------------------------------------------- recording --
def _record(run_id: str, item_type: str, item_id: str, action: str, before, after,
            reviewer: str, comment: str = "") -> None:
    audit_log.log_event(run_id, "human_review", item_type=item_type, item_id=item_id, action=action,
                        reviewer=reviewer, comment=comment, before=before, after=after)
    db.execute("INSERT INTO approvals (run_id, item_type, item_id, action, before_json, after_json, "
               "reviewer, comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (run_id, item_type, item_id, action, seal_json(before), seal_json(after),
                reviewer, comment, db.now()))


def _stamp(reviewer: str, comment: str, auto: bool) -> dict:
    return {"reviewer": reviewer, "reviewed_at": db.now(), "review_comment": comment, "auto_approved": auto}


# --------------------------------------------------- applying decisions --
def apply_requirement_decisions(state, decisions: dict) -> dict:
    """Apply review decisions to requirements, mappings and suggestions.
    Returns the state update (agent_outputs for the three agents)."""
    run_id = state["run_id"]
    reviewer = decisions.get("reviewer") or "unknown"
    auto = reviewer == AUTO_REVIEWER
    updates = {}

    req_out = state["agent_outputs"].get("requirements_agent", {})
    if req_out.get("parsed"):
        output = RequirementsOutput.model_validate(req_out["parsed"])
        chunk_map = chunks_visible_to(state.get("chunk_map") or {}, "requirements")
        new_list = []
        for r in output.requirements:
            decision = decisions.get("requirements", {}).get(r.id) or {}
            new_list.append(_decide_requirement(run_id, r, decision, reviewer, auto, chunk_map, state["scenario"]))
        new_list += _accepted_suggestions(state, decisions, reviewer, auto, chunk_map)
        summary = output.validation_summary
        updated = build_output(output.scenario_summary, new_list, summary.get("requested", len(new_list)),
                               summary.get("failed_batches", 0))
        updated.statement_similarity = output.statement_similarity if len(new_list) == len(output.requirements) else []
        updated.validation_summary["reviewed"] = sum(r.approval_status != "pending" for r in new_list)
        visible = updated.model_copy(update={"requirements": [r for r in new_list
                                                              if r.approval_status != "rejected"]})
        updates["requirements_agent"] = {**req_out, "parsed": updated.model_dump(),
                                         "rendered": render_for_next(visible)}

    comp_out = state["agent_outputs"].get("compliance_agent", {})
    if comp_out.get("parsed"):
        compliance = ComplianceOutput.model_validate(comp_out["parsed"])
        mappings = [_decide_mapping(run_id, m, decisions.get("mappings", {}).get(m.requirement_id) or {},
                                    reviewer, auto) for m in compliance.mappings]
        suggestions = []
        for s in compliance.suggested_requirements:
            action = decisions.get("suggested", {}).get(s.id)
            if action in ("accept", "reject"):
                status = "accepted" if action == "accept" else "rejected"
                _record(run_id, "suggested", s.id, action, {"status": s.status}, {"status": status}, reviewer)
                s = s.model_copy(update={"status": status})
            suggestions.append(s)
        compliance = compliance.model_copy(update={"mappings": mappings, "suggested_requirements": suggestions})
        updates["compliance_agent"] = {**comp_out, "parsed": compliance.model_dump()}
    return {"agent_outputs": updates}


def _decide_requirement(run_id, r: Requirement, decision: dict, reviewer, auto, chunk_map, scenario) -> Requirement:
    action = decision.get("action", "pending")
    comment = decision.get("comment", "")
    before = r.model_dump()
    if action == "accept":
        after = r.model_copy(update={"approval_status": "approved", **_stamp(reviewer, comment, auto)})
    elif action == "reject":
        after = r.model_copy(update={"approval_status": "rejected", **_stamp(reviewer, comment, auto)})
    elif action in ("edit", "regenerate"):
        new_fields = {k: v for k, v in (decision.get("new") or {}).items() if k in EDITABLE_REQUIREMENT_FIELDS}
        edited = Requirement.model_validate({**before, **new_fields})
        # Re-run the deterministic checks on the edited text (citations, numbers, confidence).
        edited = check_requirement(edited.model_copy(update={"model_confidence": r.model_confidence}),
                                   chunk_map, scenario)
        history = r.revision_history + [{"round": "review", "action": action, "statement": r.statement,
                                         "reviewer": reviewer, "comment": comment}]
        after = edited.model_copy(update={"approval_status": "approved", "version": r.version + 1,
                                          "revision_history": history, **_stamp(reviewer, comment, auto)})
    else:
        return r
    _record(run_id, "requirement", r.id, action, before, after.model_dump(), reviewer, comment)
    return after


def _accepted_suggestions(state, decisions, reviewer, auto, chunk_map) -> list[Requirement]:
    """Accepted suggested security/privacy requirements become real requirements (SEC-xx)."""
    compliance = _parsed(state, "compliance_agent") or {}
    accepted = [s for s in compliance.get("suggested_requirements", [])
                if decisions.get("suggested", {}).get(s["id"]) == "accept"]
    added = []
    for number, s in enumerate(accepted, start=1):
        requirement = Requirement(
            id=f"SEC-{number:02d}", kind="non_functional", statement=s["statement"],
            categories=s["categories"], sources=s["sources"], business_justification=s["rationale"][:200],
            source_stakeholder="Compliance & Security Agent (suggested, accepted by reviewer)",
            priority="High", risk_level="High", model_confidence=0.7)
        requirement = check_requirement(requirement, chunk_map, state["scenario"])
        added.append(requirement.model_copy(update={"approval_status": "approved",
                                                    **_stamp(reviewer, f"Accepted suggestion {s['id']}", auto)}))
    return added


def _decide_mapping(run_id, m: ComplianceMapping, decision: dict, reviewer, auto) -> ComplianceMapping:
    action = decision.get("action", "pending")
    comment = decision.get("comment", "")
    before = m.model_dump()
    if action == "accept":
        after = m.model_copy(update={"approval_status": "approved", **_stamp(reviewer, comment, auto)})
    elif action == "reject":
        after = m.model_copy(update={"approval_status": "rejected", **_stamp(reviewer, comment, auto)})
    elif action in ("edit", "regenerate"):
        new_fields = {k: v for k, v in (decision.get("new") or {}).items() if k in EDITABLE_MAPPING_FIELDS}
        after = ComplianceMapping.model_validate({**before, **new_fields, "approval_status": "approved",
                                                  **_stamp(reviewer, comment, auto)})
    else:
        return m
    _record(run_id, "mapping", m.requirement_id, action, before, after.model_dump(), reviewer, comment)
    return after


def apply_sdlc_decision(state, decision: dict) -> dict:
    run_id = state["run_id"]
    reviewer = decision.get("reviewer") or "unknown"
    auto = reviewer == AUTO_REVIEWER
    out = state["agent_outputs"].get("sdlc_agent", {})
    if not out.get("parsed"):
        return {}
    sdlc = SDLCOutput.model_validate(out["parsed"])
    action = decision.get("action", "pending")
    comment = decision.get("comment", "")
    ranked = [r.model for r in sdlc.ranking]
    if action == "approve":
        after = sdlc.model_copy(update={"approval_status": "approved", "selected_model": sdlc.recommended_model,
                                        **_stamp(reviewer, comment, auto)})
    elif action == "override" and decision.get("model") in ranked:
        after = sdlc.model_copy(update={"approval_status": "overridden", "selected_model": decision["model"],
                                        **_stamp(reviewer, comment, auto)})
    elif action == "reject":
        after = sdlc.model_copy(update={"approval_status": "rejected", "selected_model": "",
                                        **_stamp(reviewer, comment, auto)})
    else:
        return {}
    before = {k: sdlc.model_dump()[k] for k in ("approval_status", "selected_model", "recommended_model")}
    _record(run_id, "sdlc", "SDLC", action, before,
            {k: after.model_dump()[k] for k in ("approval_status", "selected_model", "review_comment")},
            reviewer, comment)
    return {"agent_outputs": {"sdlc_agent": {**out, "parsed": after.model_dump()}}}


# ------------------------------------------------------------- the nodes --
def auto_requirement_decisions(state) -> dict:
    requirements = (_parsed(state, "requirements_agent") or {}).get("requirements", [])
    mappings = (_parsed(state, "compliance_agent") or {}).get("mappings", [])
    return {"reviewer": AUTO_REVIEWER,
            "requirements": {r["id"]: {"action": "accept"} for r in requirements},
            "mappings": {m["requirement_id"]: {"action": "accept"} for m in mappings}}


def review_requirements_node(state) -> dict:
    mode = (state.get("options") or {}).get("review_mode", "none")
    if mode == "auto":
        decisions = auto_requirement_decisions(state)
    else:
        # Pauses here (state saved). On resume the node runs again from the top
        # and interrupt() returns the reviewer's decisions instead of pausing.
        decisions = interrupt({"stage": "requirements_review", "mandatory": mandatory_items(state)})
    return apply_requirement_decisions(state, decisions or {})


def review_sdlc_node(state) -> dict:
    mode = (state.get("options") or {}).get("review_mode", "none")
    if not _parsed(state, "sdlc_agent"):
        return {}                        # nothing to review (SDLC step failed or skipped)
    if mode == "auto":
        decision = {"reviewer": AUTO_REVIEWER, "action": "approve"}
    else:
        decision = interrupt({"stage": "sdlc_review"})
    return apply_sdlc_decision(state, decision or {})
