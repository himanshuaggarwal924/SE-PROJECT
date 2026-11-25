"""
storage/db.py - The local SQLite application database (data/app.sqlite).

Versioned migrations: MIGRATIONS is an ordered list of SQL scripts; each is
applied once and recorded in schema_version. Later phases only APPEND to the
list, so existing data is never rebuilt.

(LangGraph's own checkpoints live in a separate file, data/checkpoints.sqlite.)
"""

import json
import sqlite3
import threading
from datetime import datetime

import config

MIGRATIONS = [
    # 1 - Phase 6: runs, human approvals, baselines, change requests
    """
    CREATE TABLE runs (
        run_id      TEXT PRIMARY KEY,
        user        TEXT,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        status      TEXT NOT NULL,          -- running | awaiting_review | done | failed
        stage       TEXT DEFAULT '',        -- requirements_review | sdlc_review | ''
        scenario    TEXT DEFAULT '',
        source_name TEXT DEFAULT '',
        model       TEXT DEFAULT '',
        review_mode TEXT DEFAULT 'none'
    );
    CREATE TABLE approvals (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id      TEXT,
        item_type   TEXT NOT NULL,          -- requirement | mapping | suggested | sdlc | baseline | change_request
        item_id     TEXT NOT NULL,
        action      TEXT NOT NULL,          -- accept | reject | edit | regenerate | approve | override
        before_json TEXT,
        after_json  TEXT,
        reviewer    TEXT,
        comment     TEXT DEFAULT '',
        created_at  TEXT NOT NULL
    );
    CREATE TABLE baselines (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        project      TEXT NOT NULL DEFAULT 'default',
        version      INTEGER NOT NULL,
        run_id       TEXT,
        created_by   TEXT,
        created_at   TEXT NOT NULL,
        content_json TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        note         TEXT DEFAULT ''
    );
    CREATE TABLE change_requests (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        baseline_id     INTEGER NOT NULL REFERENCES baselines(id),
        requirement_id  TEXT NOT NULL,
        before_json     TEXT NOT NULL,
        after_json      TEXT NOT NULL,
        reason          TEXT DEFAULT '',
        requested_by    TEXT,
        requested_at    TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected
        decided_by      TEXT,
        decided_at      TEXT,
        new_baseline_id INTEGER
    );
    """,
    # 2 - Phase 7: projects, requirement history, transcripts, artefacts, joint SDLC votes
    """
    CREATE TABLE projects (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL UNIQUE,
        description TEXT DEFAULT '',
        created_by  TEXT,
        created_at  TEXT NOT NULL
    );
    INSERT INTO projects (name, description, created_at)
        VALUES ('default', 'Default project', strftime('%Y-%m-%dT%H:%M:%S', 'now'));
    ALTER TABLE runs ADD COLUMN project TEXT NOT NULL DEFAULT 'default';
    CREATE TABLE requirement_versions (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        project        TEXT NOT NULL DEFAULT 'default',
        run_id         TEXT,
        requirement_id TEXT NOT NULL,
        version        INTEGER NOT NULL,
        source         TEXT NOT NULL,        -- run | review | change_request
        content_json   TEXT NOT NULL,
        created_by     TEXT,
        created_at     TEXT NOT NULL,
        UNIQUE (run_id, requirement_id, version, source)
    );
    CREATE TABLE transcripts (
        id           TEXT PRIMARY KEY,
        project      TEXT NOT NULL DEFAULT 'default',
        created_by   TEXT,
        created_at   TEXT NOT NULL,
        status       TEXT NOT NULL,
        content_json TEXT NOT NULL
    );
    CREATE TABLE artefacts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id     TEXT NOT NULL,
        project    TEXT NOT NULL DEFAULT 'default',
        name       TEXT NOT NULL,
        content    BLOB NOT NULL,
        sha256     TEXT NOT NULL,
        created_by TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE sdlc_votes (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id     TEXT NOT NULL,
        role       TEXT NOT NULL,
        user       TEXT NOT NULL,
        action     TEXT NOT NULL,             -- approve | override | reject
        model      TEXT DEFAULT '',
        comment    TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        UNIQUE (run_id, role)
    );
    """,
    # 3 - Phase 12: stakeholder satisfaction (1-5 + comment)
    """
    CREATE TABLE satisfaction (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id     TEXT,
        user       TEXT,
        roles      TEXT DEFAULT '',
        score      INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
        comment    TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );
    """,
]

_lock = threading.Lock()
_connections: dict[str, sqlite3.Connection] = {}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    """One shared connection per database file (thread-safe via _lock),
    migrated to the latest schema."""
    path = str(config.APP_DB)
    with _lock:
        conn = _connections.get(path)
        if conn is None:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            _migrate(conn)
            _connections[path] = conn
        return conn


def _migrate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current = row[0] or 0
    for number, script in enumerate(MIGRATIONS, start=1):
        if number > current:
            conn.executescript(script)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (number,))
    conn.commit()


def schema_version() -> int:
    return connect().execute("SELECT MAX(version) FROM schema_version").fetchone()[0]


def execute(sql: str, params: tuple = ()) -> int:
    """Run a write statement; returns lastrowid."""
    conn = connect()
    with _lock:
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor.lastrowid


def query(sql: str, params: tuple = ()) -> list[dict]:
    conn = connect()
    with _lock:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def to_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def close_all() -> None:
    """Close every connection (tests use a fresh database per test)."""
    with _lock:
        for conn in _connections.values():
            conn.close()
        _connections.clear()
