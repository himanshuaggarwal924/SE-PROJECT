"""
storage/baselines.py - Versioned requirement baselines and change requests.

  lock_baseline()          once every mandatory item is decided, freeze the
                           approved requirements (+ mappings, SDLC choice) as
                           version N of the project's baseline
  request_change()         a change to an APPROVED requirement in a locked
                           baseline becomes a change request (needs re-approval)
  decide_change_request()  approving it creates baseline version N+1

Every action is written to the audit log and the approvals table.
"""

import hashlib
import json

import audit_log
from security.crypto import open_json, seal_json
from storage import db


class BaselineError(ValueError):
    pass


def _content_hash(content: dict) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _approval(run_id, item_type, item_id, action, before, after, user, comment=""):
    audit_log.log_event(run_id or "baseline", "human_review", item_type=item_type, item_id=item_id,
                        action=action, reviewer=user, comment=comment, before=before, after=after)
    db.execute("INSERT INTO approvals (run_id, item_type, item_id, action, before_json, after_json, "
               "reviewer, comment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (run_id, item_type, str(item_id), action, seal_json(before), seal_json(after),
                user, comment, db.now()))


def baseline_content(state: dict) -> dict:
    """What goes into a baseline: approved requirements, approved mappings and
    the SDLC decision."""
    outputs = state.get("agent_outputs", {})
    requirements = ((outputs.get("requirements_agent") or {}).get("parsed") or {}).get("requirements", [])
    mappings = ((outputs.get("compliance_agent") or {}).get("parsed") or {}).get("mappings", [])
    sdlc = (outputs.get("sdlc_agent") or {}).get("parsed") or {}
    return {
        "scenario": state.get("scenario", ""),
        "requirements": [r for r in requirements if r.get("approval_status") == "approved"],
        "mappings": [m for m in mappings if m.get("approval_status") == "approved"],
        "sdlc": {k: sdlc.get(k) for k in ("recommended_model", "selected_model", "approval_status",
                                          "reviewer", "reviewed_at")} if sdlc else {},
    }


def latest_version(project: str) -> int:
    row = db.query("SELECT MAX(version) AS v FROM baselines WHERE project = ?", (project,))
    return row[0]["v"] or 0


def _insert(project, run_id, user, content, note) -> dict:
    version = latest_version(project) + 1
    baseline_id = db.execute(
        "INSERT INTO baselines (project, version, run_id, created_by, created_at, content_json, "
        "content_hash, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project, version, run_id, user, db.now(), seal_json(content), _content_hash(content), note))
    return get_baseline(baseline_id)


def lock_baseline(state: dict, user: str, project: str = "default") -> dict:
    """Freeze a new baseline version. Raises BaselineError if mandatory items
    are still undecided."""
    from orchestration.review import blocking_items
    blocking = blocking_items(state)
    if blocking:
        names = ", ".join(f"{b['id']} ({'; '.join(b['reasons'])})" for b in blocking)
        raise BaselineError(f"Mandatory items still need a decision: {names}")
    content = baseline_content(state)
    if not content["requirements"]:
        raise BaselineError("No approved requirements to baseline.")
    baseline = _insert(project, state.get("run_id"), user, content, "Locked after review")
    _approval(state.get("run_id"), "baseline", baseline["id"], "approve", None,
              {"version": baseline["version"], "hash": baseline["content_hash"],
               "requirements": len(content["requirements"])}, user)
    return baseline


def get_baseline(baseline_id: int) -> dict:
    row = db.query("SELECT * FROM baselines WHERE id = ?", (baseline_id,))[0]
    return {**row, "content": open_json(row["content_json"])}


def baselines_for(project: str = "default") -> list[dict]:
    return [{**r, "content": open_json(r["content_json"])}
            for r in db.query("SELECT * FROM baselines WHERE project = ? ORDER BY version DESC", (project,))]


def baselines_for_run(run_id: str) -> list[dict]:
    return [{**r, "content": open_json(r["content_json"])}
            for r in db.query("SELECT * FROM baselines WHERE run_id = ? ORDER BY version DESC", (run_id,))]


def request_change(baseline_id: int, requirement_id: str, new_fields: dict, reason: str, user: str) -> int:
    """Propose a change to an approved requirement of a locked baseline."""
    baseline = get_baseline(baseline_id)
    current = next((r for r in baseline["content"]["requirements"] if r["id"] == requirement_id), None)
    if current is None:
        raise BaselineError(f"{requirement_id} is not an approved requirement of baseline v{baseline['version']}.")
    after = {**current, **new_fields}
    if after == current:
        raise BaselineError("The change request does not change anything.")
    cr_id = db.execute(
        "INSERT INTO change_requests (baseline_id, requirement_id, before_json, after_json, reason, "
        "requested_by, requested_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (baseline_id, requirement_id, seal_json(current), seal_json(after), reason, user, db.now()))
    audit_log.log_event(baseline["run_id"] or "baseline", "change_requested", change_request=cr_id,
                        requirement=requirement_id, reason=reason, user=user,
                        before=current.get("statement"), after=after.get("statement"))
    return cr_id


def change_requests(status: str | None = None, project: str = "default") -> list[dict]:
    sql = ("SELECT cr.*, b.version AS baseline_version, b.project FROM change_requests cr "
           "JOIN baselines b ON b.id = cr.baseline_id WHERE b.project = ?")
    params = [project]
    if status:
        sql += " AND cr.status = ?"
        params.append(status)
    rows = db.query(sql + " ORDER BY cr.id DESC", tuple(params))
    return [{**r, "before": open_json(r["before_json"]), "after": open_json(r["after_json"])} for r in rows]


def decide_change_request(cr_id: int, approve: bool, user: str, comment: str = "") -> dict | None:
    """Approve (-> new baseline version with the change) or reject a change request."""
    rows = db.query("SELECT * FROM change_requests WHERE id = ?", (cr_id,))
    if not rows:
        raise BaselineError(f"No change request {cr_id}.")
    cr = rows[0]
    if cr["status"] != "pending":
        raise BaselineError(f"Change request {cr_id} was already {cr['status']}.")
    after = open_json(cr["after_json"])
    new_baseline = None
    if approve:
        base = get_baseline(cr["baseline_id"])
        latest = baselines_for(base["project"])[0]           # apply on top of the newest version
        content = dict(latest["content"])
        approved_after = {**after, "approval_status": "approved", "reviewer": user, "reviewed_at": db.now(),
                          "version": int(after.get("version", 1)) + 1,
                          "review_comment": comment or f"Change request {cr_id}"}
        content["requirements"] = [approved_after if r["id"] == cr["requirement_id"] else r
                                   for r in content["requirements"]]
        new_baseline = _insert(base["project"], base["run_id"], user, content,
                               f"Change request {cr_id}: {cr['requirement_id']}")
        from storage import projects
        projects.record_versions(base["run_id"], [approved_after], source="change_request", user=user)
    db.execute("UPDATE change_requests SET status = ?, decided_by = ?, decided_at = ?, new_baseline_id = ? "
               "WHERE id = ?", ("approved" if approve else "rejected", user, db.now(),
                                new_baseline["id"] if new_baseline else None, cr_id))
    before = open_json(cr["before_json"])
    _approval(get_baseline(cr["baseline_id"])["run_id"], "change_request", cr_id,
              "approve" if approve else "reject", before, after, user, comment)
    return new_baseline
