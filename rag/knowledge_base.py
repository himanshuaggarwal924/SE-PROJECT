"""
rag/knowledge_base.py - Reads the version-controlled knowledge base in kb/.

Pure Python (no embeddings here, so it is fast and easy to test):
  load_items()           parse every kb/**/*.md file with YAML front-matter
  item_sections()        split an item into "## section" pieces for indexing
  is_evidence()          the allowlist: active + allowed type + allowed source
  detect_applicability() which applicability tags fit this run (keyword rules)

The embedding/indexing side lives in rag/vector_store.py.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import config
from rag.chunker import chunk_text

REQUIRED_FIELDS = ["id", "title", "type", "source", "jurisdiction", "effective_date",
                   "version", "applicability", "status"]
KB_TYPES = ["regulation", "policy", "security_standard", "re_guideline", "sdlc_rule", "template"]
FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)


@dataclass
class KBItem:
    id: str
    title: str
    type: str
    source: str
    jurisdiction: str
    effective_date: str
    version: str
    applicability: list[str]
    status: str
    body: str
    path: str                        # relative to kb/, e.g. "policies/x.md"
    content_hash: str
    problems: list[str] = field(default_factory=list)   # front-matter errors

    @property
    def is_valid(self) -> bool:
        return not self.problems


def parse_item(path: Path, root: Path) -> KBItem | None:
    """Parse one KB file. Returns None for files without front-matter (e.g. README)."""
    raw = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(raw)
    if not match:
        return None
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as error:
        meta = {}
        problems = [f"Invalid YAML front-matter: {error}"]
    else:
        problems = [f"Missing field '{f}'" for f in REQUIRED_FIELDS if meta.get(f) in (None, "", [])]

    if meta.get("type") and meta["type"] not in KB_TYPES:
        problems.append(f"Unknown type '{meta['type']}'")
    if meta.get("status") and meta["status"] not in ("active", "superseded"):
        problems.append(f"Unknown status '{meta['status']}'")
    applicability = meta.get("applicability") or []
    if isinstance(applicability, str):
        applicability = [applicability]

    # The hash covers the content AND the chunking setting, so changing
    # KB_CHUNK_SIZE also triggers a re-index.
    digest = hashlib.sha256(f"{config.KB_CHUNK_SIZE}\n{raw}".encode("utf-8")).hexdigest()[:16]
    return KBItem(
        id=str(meta.get("id", "")), title=str(meta.get("title", path.stem)),
        type=str(meta.get("type", "")), source=str(meta.get("source", "")),
        jurisdiction=str(meta.get("jurisdiction", "")),
        effective_date=str(meta.get("effective_date", "")), version=str(meta.get("version", "")),
        applicability=[str(a) for a in applicability], status=str(meta.get("status", "")),
        body=match.group(2).strip(), path=path.relative_to(root).as_posix(),
        content_hash=digest, problems=problems,
    )


def load_items(root: Path | None = None) -> list[KBItem]:
    """Every KB item (valid or not - the admin page shows the problems)."""
    root = root or config.KB_DIR
    if not root.exists():
        return []
    items = [parse_item(p, root) for p in sorted(root.rglob("*.md"))]
    return [i for i in items if i is not None]


def item_sections(item: KBItem) -> list[tuple[str, str]]:
    """(section heading, text) pieces of an item, ready to embed. Text before
    the first ## heading (e.g. the SAMPLE banner) is not indexed."""
    sections = []
    for block in re.split(r"^##\s+", item.body, flags=re.MULTILINE)[1:]:
        heading, _, text = block.partition("\n")
        for piece in chunk_text(text.strip(), config.KB_CHUNK_SIZE, 0):
            sections.append((heading.strip(), piece))
    return sections


def is_evidence(item: KBItem) -> bool:
    """The allowlist: only these items may be retrieved and cited."""
    return (item.is_valid and item.status == "active"
            and item.type in config.KB_EVIDENCE_TYPES
            and item.source in config.KB_ALLOWED_SOURCES)


def detect_applicability(*texts: str) -> list[str]:
    """Applicability tags whose keywords appear in the texts, plus "all"."""
    haystack = " ".join(t or "" for t in texts).lower()
    found = [tag for tag, words in config.KB_APPLICABILITY_KEYWORDS.items()
             if any(word in haystack for word in words)]
    return found + ["all"]
