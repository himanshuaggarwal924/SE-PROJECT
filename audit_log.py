"""
audit_log.py - A tamper-evident audit trail of every agent's input and output.

Each event is appended as one JSON object per line ("JSON Lines") to
logs/audit_log.jsonl, with a timestamp and a run_id that groups the events
of one pipeline run. It's also printed to the console.

Hash chain (Phase 9): every record stores the hash of the previous record
(`prev_hash`) and its own hash (`hash` = SHA-256 of prev_hash + the record's
canonical JSON). Changing, deleting or inserting a line breaks the chain, which
`python -m audit_log verify` (or the admin page) detects. Records written
before the chain existed ("legacy") are counted but cannot be verified.
A retention purge starts the file with a `retention_purge` anchor record.

Note: without a secret key this detects accidental or naive tampering, not an
attacker who recomputes every hash.
"""

import hashlib
import json
import os
import sys
import threading
import uuid
from datetime import datetime

import config

GENESIS = "0" * 64
_lock = threading.Lock()
_tail_cache: dict[str, tuple[int, str]] = {}      # path -> (file size, last hash)


def new_run_id() -> str:
    """A short unique id for one pipeline run, e.g. '20260924-153012-a1b2c3'."""
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def _canonical(record: dict) -> str:
    return json.dumps({k: v for k, v in record.items() if k != "hash"}, ensure_ascii=False,
                      sort_keys=True, default=str)


def record_hash(record: dict) -> str:
    return hashlib.sha256((record.get("prev_hash", "") + _canonical(record)).encode("utf-8")).hexdigest()


def _line_hash(line: str) -> str:
    """The chain value of a stored line: its own hash, or (legacy) a hash of the line."""
    try:
        record = json.loads(line)
        if record.get("hash"):
            return record["hash"]
    except ValueError:
        pass
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()


def _last_hash(path) -> str:
    """Hash of the last record in the file (cached by file size)."""
    if not path.exists():
        return GENESIS
    size = path.stat().st_size
    cached = _tail_cache.get(str(path))
    if cached and cached[0] == size:
        return cached[1]
    with open(path, "rb") as f:
        f.seek(max(0, size - 65536))
        lines = [line for line in f.read().decode("utf-8", errors="replace").splitlines() if line.strip()]
    if not lines:
        return GENESIS
    if size > 65536 and len(lines) == 1:          # one huge line: read the whole file
        with open(path, encoding="utf-8") as f:
            lines = [line for line in f if line.strip()]
    return _line_hash(lines[-1])


def log_event(run_id: str, event: str, **details) -> None:
    """Append one hash-chained audit record to the log file and print a short summary."""
    record = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run_id": run_id,
        "event": event,
        **details,
    }
    path = config.AUDIT_LOG_FILE
    with _lock:
        config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        record["prev_hash"] = _last_hash(path)
        record["hash"] = record_hash(record)
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
        _tail_cache[str(path)] = (path.stat().st_size, record["hash"])

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


def verify(path=None) -> dict:
    """Check the hash chain. Returns {"ok", "records", "chained", "legacy",
    "first_error_line", "error"}."""
    path = path or config.AUDIT_LOG_FILE
    result = {"ok": True, "records": 0, "chained": 0, "legacy": 0, "first_error_line": None, "error": ""}
    if not os.path.exists(path):
        return result
    previous = GENESIS
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            result["records"] += 1
            try:
                record = json.loads(line)
            except ValueError:
                return {**result, "ok": False, "first_error_line": number, "error": "not valid JSON"}
            if "hash" not in record:
                if result["chained"]:
                    return {**result, "ok": False, "first_error_line": number,
                            "error": "record without a hash after the chain started"}
                result["legacy"] += 1
                previous = _line_hash(line)
                continue
            if record_hash(record) != record["hash"]:
                return {**result, "ok": False, "first_error_line": number, "error": "record content was changed"}
            if record.get("event") == "retention_purge" and record.get("anchor"):
                previous = record.get("continues_from", record["hash"])
                result["chained"] += 1
                continue
            if record["prev_hash"] != previous:
                return {**result, "ok": False, "first_error_line": number,
                        "error": "chain broken (a record was removed, inserted or reordered)"}
            previous = record["hash"]
            result["chained"] += 1
    return result


def reset_cache() -> None:
    _tail_cache.clear()


if __name__ == "__main__":
    if sys.argv[1:] != ["verify"]:
        print("Usage: python -m audit_log verify")
        sys.exit(2)
    outcome = verify()
    print(json.dumps(outcome, indent=2))
    sys.exit(0 if outcome["ok"] else 1)
