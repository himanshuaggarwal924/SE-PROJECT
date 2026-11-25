"""
storage/projects.py - Projects, requirement history, run/baseline diffs,
joint SDLC votes, transcripts and stored artefacts (Phase 7, SQLite).

A project groups many runs, interviews and baselines.
"""

import difflib
import hashlib
import json

import audit_log
from auth.rbac import SDLC_JOINT_ROLES, roles
from security.crypto import decrypt_bytes, encrypt_bytes, open_json, seal_json
from storage import db


# ------------------------------------------------------------------ projects --
def list_projects() -> list[dict]:
    return db.query("SELECT * FROM projects ORDER BY name")


def create_project(name: str, description: str, user: str | None) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Please enter a project name.")
    if db.query("SELECT 1 FROM projects WHERE name = ?", (name,)):
        raise ValueError(f"A project called '{name}' already exists.")
    db.execute("INSERT INTO projects (name, description, created_by, created_at) VALUES (?, ?, ?, ?)",
               (name, description.strip(), user, db.now()))
    audit_log.log_event("projects", "project_created", project=name, user=user)


def set_run_project(run_id: str, project: str) -> None:
    db.execute("UPDATE runs SET project = ? WHERE run_id = ?", (project, run_id))


def run_project(run_id: str) -> str:
    rows = db.query("SELECT project FROM runs WHERE run_id = ?", (run_id,))
    return rows[0]["project"] if rows else "default"


def project_runs(project: str) -> list[dict]:
    return db.query("SELECT * FROM runs WHERE project = ? ORDER BY created_at DESC", (project,))


# ------------------------------------------------------- requirement history --
def record_versions(run_id: str, requirements: list[dict], source: str = "run", user: str | None = None) -> int:
    """Store each requirement's current version (ignored if already stored)."""
    project = run_project(run_id)
    added = 0
    for r in requirements:
        before = db.query("SELECT 1 FROM requirement_versions WHERE run_id = ? AND requirement_id = ? "
                          "AND version = ? AND source = ?", (run_id, r["id"], r.get("version", 1), source))
        if before:
            continue
        db.execute("INSERT INTO requirement_versions (project, run_id, requirement_id, version, source, "
                   "content_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (project, run_id, r["id"], r.get("version", 1), source, seal_json(r),
                    user or r.get("reviewer") or None, db.now()))
        added += 1
    return added


def requirement_history(project: str, requirement_id: str) -> list[dict]:
    rows = db.query("SELECT * FROM requirement_versions WHERE project = ? AND requirement_id = ? "
                    "ORDER BY created_at, version", (project, requirement_id))
    return [{**r, "content": open_json(r["content_json"])} for r in rows]


def requirement_ids(project: str) -> list[str]:
    return [r["requirement_id"] for r in db.query(
        "SELECT DISTINCT requirement_id FROM requirement_versions WHERE project = ? ORDER BY requirement_id",
        (project,))]


def run_requirements(run_id: str) -> list[dict]:
    """The latest stored version of each requirement of a run."""
    rows = db.query("SELECT * FROM requirement_versions WHERE run_id = ? ORDER BY version", (run_id,))
    latest = {}
    for row in rows:
        latest[row["requirement_id"]] = open_json(row["content_json"])
    return list(latest.values())


def diff_requirements(before: list[dict], after: list[dict]) -> list[dict]:
    """Requirement-level diff by ID: added / removed / changed / unchanged."""
    old = {r["id"]: r for r in before}
    new = {r["id"]: r for r in after}
    rows = []
    for rid in sorted(old.keys() | new.keys()):
        a, b = old.get(rid), new.get(rid)
        if a and not b:
            rows.append({"id": rid, "change": "removed", "before": a["statement"], "after": "", "details": ""})
        elif b and not a:
            rows.append({"id": rid, "change": "added", "before": "", "after": b["statement"], "details": ""})
        else:
            fields = [f for f in ("statement", "priority", "risk_level", "categories", "approval_status")
                      if a.get(f) != b.get(f)]
            words = "".join(_word_diff(a["statement"], b["statement"])) if "statement" in fields else ""
            rows.append({"id": rid, "change": "changed" if fields else "unchanged", "before": a["statement"],
                         "after": b["statement"], "details": (", ".join(fields) + (f": {words}" if words else ""))})
    return rows


def _word_diff(a: str, b: str):
    for token in difflib.ndiff(a.split(), b.split()):
        if token.startswith("- "):
            yield f"[-{token[2:]}] "
        elif token.startswith("+ "):
            yield f"[+{token[2:]}] "


# ----------------------------------------------------------- joint SDLC votes --
def record_sdlc_vote(run_id: str, user: str, action: str, model: str = "", comment: str = "") -> list[str]:
    """Record the user's vote for every joint-approval role they hold.
    Returns the roles voted for; raises PermissionError if they hold none."""
    voting_roles = [r for r in SDLC_JOINT_ROLES if r in roles(user)]
    if not voting_roles:
        raise PermissionError("Only a project manager, architect, security officer or compliance "
                              "officer can vote on the SDLC choice.")
    for role in voting_roles:
        db.execute("INSERT INTO sdlc_votes (run_id, role, user, action, model, comment, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (run_id, role) DO UPDATE SET user = excluded.user, "
                   "action = excluded.action, model = excluded.model, comment = excluded.comment, "
                   "created_at = excluded.created_at",
                   (run_id, role, user, action, model, comment, db.now()))
    audit_log.log_event(run_id, "sdlc_vote", user=user, roles=voting_roles, action=action, model=model,
                        comment=comment)
    return voting_roles


def sdlc_votes(run_id: str) -> dict[str, dict]:
    return {r["role"]: r for r in db.query("SELECT * FROM sdlc_votes WHERE run_id = ?", (run_id,))}


def sdlc_joint_decision(run_id: str, recommended: str) -> dict | None:
    """The combined decision once it is final, else None:
      any reject                          -> reject
      all four roles approve the same model -> approve / override
      votes for different models          -> None (still waiting)"""
    votes = sdlc_votes(run_id)
    if any(v["action"] == "reject" for v in votes.values()):
        rejecting = [f"{role}: {v['user']}" for role, v in votes.items() if v["action"] == "reject"]
        return {"action": "reject", "reviewer": "; ".join(rejecting),
                "comment": " | ".join(v["comment"] for v in votes.values() if v["comment"])}
    if set(votes) != set(SDLC_JOINT_ROLES):
        return None
    models = {v["model"] or recommended for v in votes.values()}
    if len(models) != 1:
        return None
    model = models.pop()
    return {"action": "approve" if model == recommended else "override", "model": model,
            "reviewer": "; ".join(f"{role}: {votes[role]['user']}" for role in SDLC_JOINT_ROLES),
            "comment": " | ".join(v["comment"] for v in votes.values() if v["comment"])}


# ---------------------------------------------------------------- transcripts --
def save_transcript(session: dict, project: str = "default") -> None:
    existing = db.query("SELECT project FROM transcripts WHERE id = ?", (session["id"],))
    project = existing[0]["project"] if existing else session.get("project", project)
    db.execute("INSERT INTO transcripts (id, project, created_by, created_at, status, content_json) "
               "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET status = excluded.status, "
               "content_json = excluded.content_json",
               (session["id"], project, session.get("created_by"), session.get("created_at") or db.now(),
                session.get("status", ""), seal_json(session)))


def load_transcript(session_id: str) -> dict | None:
    rows = db.query("SELECT content_json FROM transcripts WHERE id = ?", (session_id,))
    return open_json(rows[0]["content_json"]) if rows else None


def list_transcripts(user: str | None, project: str | None = None) -> list[dict]:
    sql, params = "SELECT content_json, project FROM transcripts WHERE created_by IS ?", [user]
    if project:
        sql += " AND project = ?"
        params.append(project)
    rows = db.query(sql + " ORDER BY created_at DESC", tuple(params))
    return [{**open_json(r["content_json"]), "project": r["project"]} for r in rows]


# ------------------------------------------------------------------ artefacts --
def store_artefacts(run_id: str, files: dict[str, bytes], user: str | None) -> None:
    project = run_project(run_id)
    db.execute("DELETE FROM artefacts WHERE run_id = ?", (run_id,))
    for name, content in files.items():
        db.execute("INSERT INTO artefacts (run_id, project, name, content, sha256, created_by, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (run_id, project, name, encrypt_bytes(content), hashlib.sha256(content).hexdigest(),
                    user, db.now()))


def stored_artefacts(run_id: str) -> dict[str, bytes]:
    return {r["name"]: decrypt_bytes(r["content"]) for r in db.query(
        "SELECT name, content FROM artefacts WHERE run_id = ? ORDER BY id", (run_id,))}
