"""
security/retention.py - Purges data older than the retention period.

    python -m security.retention              # purge older than RETENTION_DAYS
    python -m security.retention --days 30 --dry-run

Purged: audit-log records, interview transcripts, runs (with their saved
LangGraph checkpoints in data/checkpoints.sqlite and their approval rows).
Kept: requirement baselines and change requests (formal, approved records).
The audit log is rewritten with a `retention_purge` anchor first, so the
hash chain of the remaining records still verifies.
"""

import argparse
import json
from datetime import datetime, timedelta

import audit_log
import config


def _older(timestamp: str, cutoff: datetime) -> bool:
    try:
        return datetime.fromisoformat(timestamp) < cutoff
    except (TypeError, ValueError):
        return False


def _purge_audit_log(cutoff: datetime, dry_run: bool) -> int:
    path = config.AUDIT_LOG_FILE
    if not path.exists():
        return 0
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    keep_from = 0
    for index, line in enumerate(lines):
        if _older(json.loads(line).get("timestamp", ""), cutoff):
            keep_from = index + 1
        else:
            break
    removed = keep_from
    if removed and not dry_run:
        anchor = {"timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                  "run_id": "retention", "event": "retention_purge", "anchor": True,
                  "removed_records": removed, "cutoff": cutoff.isoformat(timespec="seconds"),
                  "continues_from": audit_log._line_hash(lines[removed - 1]), "prev_hash": audit_log.GENESIS}
        anchor["hash"] = audit_log.record_hash(anchor)
        temp = path.with_suffix(".tmp")
        temp.write_text("\n".join([json.dumps(anchor, ensure_ascii=False)] + lines[removed:]) + "\n",
                        encoding="utf-8")
        temp.replace(path)
        audit_log.reset_cache()
    return removed


def _purge_transcripts(cutoff: datetime, dry_run: bool) -> int:
    removed = 0
    from storage import db
    for row in db.query("SELECT id, created_at FROM transcripts") if _has_table("transcripts") else []:
        if _older(row["created_at"], cutoff):
            removed += 1
            if not dry_run:
                db.execute("DELETE FROM transcripts WHERE id = ?", (row["id"],))
    if config.INTERVIEWS_DIR.exists():                       # JSON files (before the database)
        for file in config.INTERVIEWS_DIR.glob("*.json"):
            try:
                created = json.loads(file.read_text(encoding="utf-8")).get("created_at", "")
            except (OSError, ValueError):
                continue
            if _older(created, cutoff):
                removed += 1
                if not dry_run:
                    file.unlink()
    return removed


def _has_table(name: str) -> bool:
    from storage import db
    return bool(db.query("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)))


def _purge_runs(cutoff: datetime, dry_run: bool) -> int:
    from storage import db
    old = [r["run_id"] for r in db.query("SELECT run_id, updated_at FROM runs")
           if _older(r["updated_at"], cutoff)]
    if old and not dry_run:
        import pipeline
        saver = pipeline.persistent_checkpointer()
        for run_id in old:
            saver.delete_thread(run_id)
            db.execute("DELETE FROM approvals WHERE run_id = ?", (run_id,))
            for table in ("requirement_versions", "sdlc_votes"):
                if _has_table(table):
                    db.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
            if _has_table("artefacts"):
                db.execute("DELETE FROM artefacts WHERE run_id = ?", (run_id,))
            db.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
    return len(old)


def purge(days: int | None = None, dry_run: bool = False, user: str | None = None) -> dict:
    days = config.RETENTION_DAYS if days is None else days
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    counts = {"audit_records": _purge_audit_log(cutoff, dry_run),
              "transcripts": _purge_transcripts(cutoff, dry_run),
              "runs": _purge_runs(cutoff, dry_run)}
    if not dry_run:
        audit_log.log_event("retention", "retention_purge_done", user=user, days=days, **counts)
    return {"days": days, "cutoff": cutoff.isoformat(timespec="seconds"), "dry_run": dry_run, **counts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(purge(args.days, args.dry_run, user="cli"), indent=2))
