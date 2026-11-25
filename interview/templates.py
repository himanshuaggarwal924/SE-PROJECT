"""
interview/templates.py - Loads the topic checklist and the role templates,
and finds knowledge-base hints for a topic (deterministic keyword match).
"""

from functools import lru_cache

import yaml

import config
from rag.knowledge_base import is_evidence, item_sections, load_items


@lru_cache(maxsize=1)
def topics() -> dict[str, dict]:
    with open(config.INTERVIEW_TEMPLATES_DIR / "topics.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def role_templates() -> dict[str, dict]:
    """{role key: {"role", "display_name", "topics": {topic: starter question}}}."""
    found = {}
    for path in sorted(config.INTERVIEW_TEMPLATES_DIR.glob("*.yaml")):
        if path.name == "topics.yaml":
            continue
        with open(path, encoding="utf-8") as f:
            template = yaml.safe_load(f)
        unknown = set(template["topics"]) - set(topics())
        if unknown:
            raise ValueError(f"{path.name} uses unknown topics: {', '.join(sorted(unknown))}")
        found[template["role"]] = template
    return found


def kb_hints(topic: str, limit: int | None = None) -> list[dict]:
    """KB sections (active, allowlisted) that mention the topic's keywords,
    most matches first. Used to make questions context-aware."""
    keywords = [k.lower() for k in topics()[topic].get("kb_keywords", [])]
    if not keywords:
        return []
    scored = []
    for item in load_items():
        if not is_evidence(item):
            continue
        for heading, text in item_sections(item):
            hits = sum(text.lower().count(k) for k in keywords)
            if hits:
                scored.append((hits, item.title, heading, text))
    scored.sort(key=lambda s: -s[0])
    return [{"title": t, "section": h, "text": x} for _, t, h, x in scored[: limit or config.INTERVIEW_KB_HINTS]]


# ------------------------------------------------- embedding-based KB pointers --
def _topic_texts() -> dict[str, str]:
    return {key: f"{t['label']}: {t['description']}" for key, t in topics().items()}


def _hints_fingerprint() -> str:
    """Changes whenever the topic list or any KB item (or the allowlist) changes."""
    import hashlib
    import json
    parts = [json.dumps(_topic_texts(), sort_keys=True),
             json.dumps(sorted((i.path, i.content_hash) for i in load_items())),
             json.dumps([config.KB_EVIDENCE_TYPES, config.KB_ALLOWED_SOURCES])]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def _hints_file():
    return config.VECTOR_DB_DIR / "kb_topic_hints.json"


def ensure_topic_hints() -> dict[str, dict]:
    """The best KB section per topic (MiniLM), computed once per KB/topic
    version in the worker process and cached. {} if it can't be computed."""
    import json
    fingerprint = _hints_fingerprint()
    path = _hints_file()
    if path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fingerprint:
                return cached["hints"]
        except (OSError, ValueError, KeyError):
            pass
    from context_loader import _run_retrieval_worker
    try:
        found = _run_retrieval_worker({"queries": [], "document": None, "kb": None,
                                       "topic_texts": _topic_texts()})
    except Exception:
        return {}                       # no embeddings available: no pointers
    hints = found.get("topic_hints", {})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fingerprint": fingerprint, "hints": hints}, indent=2), encoding="utf-8")
    return hints


def topic_pointer(topic: str) -> dict | None:
    """The cached best KB section for a topic, if it passes the similarity
    threshold (INTERVIEW_KB_HINT_MIN_SIMILARITY); otherwise None."""
    import json
    path = _hints_file()
    if not path.exists():
        return None
    try:
        hint = json.loads(path.read_text(encoding="utf-8"))["hints"].get(topic)
    except (OSError, ValueError, KeyError):
        return None
    if hint and hint.get("similarity", 0) >= config.INTERVIEW_KB_HINT_MIN_SIMILARITY:
        return hint
    return None
