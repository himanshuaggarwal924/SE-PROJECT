"""
storage/feedback.py - Stakeholder satisfaction ratings (1-5 + comment), shown
on the Evaluation page next to the measured metrics.
"""

import audit_log
from auth.user_store import get_roles
from security.crypto import decrypt_text, encrypt_text
from storage import db


def submit(user: str | None, score: int, comment: str = "", run_id: str | None = None) -> int:
    score = int(score)
    if not 1 <= score <= 5:
        raise ValueError("The score must be between 1 and 5.")
    comment = comment.strip()[:2000]
    feedback_id = db.execute(
        "INSERT INTO satisfaction (run_id, user, roles, score, comment, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id or None, user, ",".join(get_roles(user)), score, encrypt_text(comment), db.now()))
    audit_log.log_event(run_id or "feedback", "satisfaction_submitted", user=user, score=score,
                        has_comment=bool(comment))
    return feedback_id


def entries() -> list[dict]:
    rows = db.query("SELECT * FROM satisfaction ORDER BY id DESC")
    return [{**r, "comment": decrypt_text(r["comment"]) or ""} for r in rows]


def summary() -> dict:
    rows = entries()
    distribution = {n: sum(r["score"] == n for r in rows) for n in range(1, 6)}
    return {"responses": len(rows), "mean": round(sum(r["score"] for r in rows) / len(rows), 2) if rows else None,
            "distribution": distribution}
