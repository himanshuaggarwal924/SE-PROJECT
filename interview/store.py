"""
interview/store.py - Saves interview transcripts in the SQLite database
(transcripts table, Phase 7). Each user only sees their own transcripts.
Transcripts kept as JSON files before Phase 7 are imported with
`python -m storage.migrate`.
"""

from storage import projects


def save(session: dict, project: str = "default") -> None:
    projects.save_transcript(session, project)


def load(session_id: str) -> dict:
    session = projects.load_transcript(session_id)
    if session is None:
        raise KeyError(session_id)
    return session


def list_sessions(user: str | None, project: str | None = None) -> list[dict]:
    """The user's transcripts, newest first (optionally of one project)."""
    return projects.list_transcripts(user, project)
