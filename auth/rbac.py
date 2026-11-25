"""
auth/rbac.py - Role-based access control (Phase 7).

Who may do what:
  approve_requirement     analyst, project_manager, architect, security_officer,
                          compliance_officer, admin - PLUS, for mandatory items,
                          the role that owns the reason (see MANDATORY_REASON_ROLE)
  approve_mapping         compliance_officer (regulatory interpretations)
  decide_suggestion       security_officer, compliance_officer
  vote_sdlc               project_manager, architect, security_officer, compliance_officer
                          - the SDLC choice needs an approving vote from EACH of
                          these four roles (joint approval)
  lock_baseline           project_manager
  request_change          any role except admin-only accounts
  decide_change_request   project_manager
  manage_kb, manage_users, purge_data   admin

The graph-level functions (orchestration/review.py, storage/baselines.py)
stay role-agnostic; the app enforces these rules before calling them, and
every denied action is written to the audit log ("access_denied").
"""

import audit_log
from auth import user_store

REVIEWER_ROLES = {"analyst", "project_manager", "architect", "security_officer", "compliance_officer"}
PERMISSIONS = {
    "approve_requirement": REVIEWER_ROLES | {"admin"},
    "approve_mapping": {"compliance_officer"},
    "decide_suggestion": {"security_officer", "compliance_officer"},
    "vote_sdlc": {"project_manager", "architect", "security_officer", "compliance_officer"},
    "lock_baseline": {"project_manager"},
    "request_change": REVIEWER_ROLES,
    "decide_change_request": {"project_manager"},
    "manage_kb": {"admin"},
    "manage_users": {"admin"},
    "purge_data": {"admin"},
}
SDLC_JOINT_ROLES = ["project_manager", "architect", "security_officer", "compliance_officer"]
MANDATORY_REASON_ROLE = {
    "high-risk security requirement": "security_officer",
    "architecture-critical requirement": "architect",
    "conflicting stakeholder decision": "project_manager",
    "regulatory interpretation": "compliance_officer",
}
ROLE_LABELS = {"analyst": "Analyst", "compliance_officer": "Compliance officer",
               "security_officer": "Security officer", "project_manager": "Project manager",
               "architect": "Architect", "admin": "Administrator"}


def roles(user: str | None) -> set[str]:
    return set(user_store.get_roles(user))


def can(user: str | None, permission: str) -> bool:
    return bool(roles(user) & PERMISSIONS[permission])


def deny(user: str | None, action: str, item: str = "", run_id: str = "access") -> None:
    audit_log.log_event(run_id, "access_denied", user=user, action=action, item=item)


def can_decide_requirement(user: str | None, reasons: list[str] | None) -> bool:
    """General reviewer right + the owning role for every mandatory reason."""
    if not can(user, "approve_requirement"):
        return False
    needed = {MANDATORY_REASON_ROLE[r] for r in (reasons or []) if r in MANDATORY_REASON_ROLE}
    return needed <= roles(user)


def filter_requirement_decisions(decisions: dict, mandatory: list[dict], user: str | None,
                                 run_id: str) -> tuple[dict, list[str]]:
    """Keep only the decisions this user may make; returns (allowed, denied item labels).
    Denials are audited."""
    reasons = {(i["type"], i["id"]): i["reasons"] for i in mandatory}
    allowed = {"reviewer": user, "requirements": {}, "mappings": {}, "suggested": {}}
    denied = []
    for rid, decision in decisions.get("requirements", {}).items():
        if can_decide_requirement(user, reasons.get(("requirement", rid))):
            allowed["requirements"][rid] = decision
        else:
            denied.append(f"requirement {rid}")
    for rid, decision in decisions.get("mappings", {}).items():
        if can(user, "approve_mapping"):
            allowed["mappings"][rid] = decision
        else:
            denied.append(f"mapping {rid}")
    for sid, decision in decisions.get("suggested", {}).items():
        if can(user, "decide_suggestion"):
            allowed["suggested"][sid] = decision
        else:
            denied.append(f"suggestion {sid}")
    for item in denied:
        deny(user, "review decision", item, run_id)
    return allowed, denied


def missing_roles_for(user: str | None, mandatory_reasons: list[str]) -> list[str]:
    """Roles the user lacks to decide an item (for the UI's explanation)."""
    needed = {MANDATORY_REASON_ROLE[r] for r in mandatory_reasons if r in MANDATORY_REASON_ROLE}
    return sorted(ROLE_LABELS[r] for r in needed - roles(user))
