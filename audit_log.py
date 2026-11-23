"""
audit_log.py - A simple audit trail of every agent's input and output.

Each event is appended as one JSON object per line ("JSON Lines") to
logs/audit_log.jsonl, with a timestamp and a run_id that groups the events
of one pipeline run. It's also printed to the console.

EXTENSION POINT (later phase): write the same records to a database table
instead of (or as well as) the file - only log_event() needs to change.
"""

import json
import uuid
from datetime import datetime

import config


def new_run_id() -> str:
    """A short unique id for one pipeline run, e.g. '20260924-153012-a1b2c3'."""
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def log_event(run_id: str, event: str, **details) -> None:
    """Append one audit record to the log file and print a short summary."""
    record = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": run_id,
        "event": event,
        **details,
    }

    config.LOGS_DIR.mkdir(exist_ok=True)
    with open(config.AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    agent = f" [{details['agent']}]" if "agent" in details else ""
    print(f"[AUDIT {record['timestamp']}] run={run_id} {event}{agent}")


def read_events(run_id: str | None = None) -> list[dict]:
    """Read the log back (optionally only one run's events) - used by the UI."""
    if not config.AUDIT_LOG_FILE.exists():
        return []
    events = []
    with open(config.AUDIT_LOG_FILE, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                if run_id is None or record.get("run_id") == run_id:
                    events.append(record)
    return events
