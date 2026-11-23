"""
context_loader.py - Prepares the source material the Requirements Agent reads.

This is the "seam" between the agents and the RAG layer: agents only ever
receive one string of context, and never need to know how it was made.

    no document         -> method "none"       (the typed description is enough)
    small document      -> method "direct"     (whole text pasted into the prompt)
    large document      -> method "retrieval"  (chunk -> embed -> ChromaDB -> best chunks)
"""

import json
import subprocess
import sys
from dataclasses import dataclass, field

import config

NO_SOURCE_TEXT = "No source document was provided. Use the functionality description above."

# Searches used to pull relevant chunks out of a large document. Several
# different searches give the agent a balanced mix: features AND quality needs.
RETRIEVAL_QUERIES = [
    "{focus}",
    "{focus} business rules, workflow steps, decisions, limits and thresholds",
    "security, access control, encryption and data privacy requirements",
    "regulatory compliance, KYC, AML, audit trail and record retention",
    "performance, availability, response time and scalability targets",
]


@dataclass
class ContextResult:
    text: str                                   # what goes into the prompt
    method: str                                 # "none", "direct" or "retrieval"
    details: dict = field(default_factory=dict)  # numbers for the UI and audit log


def build_reference_context(source_text: str, source_name: str, focus: str) -> ContextResult:
    """Turn the user's document text into prompt-sized context.

    focus: what the user wants requirements for - used as the search query.
    """
    source_text = (source_text or "").strip()
    if not source_text:
        return ContextResult(NO_SOURCE_TEXT, "none")

    details = {"source": source_name, "document_chars": len(source_text)}
    if len(source_text) > config.MAX_DOCUMENT_CHARS:
        source_text = source_text[: config.MAX_DOCUMENT_CHARS]
        details["truncated_to_chars"] = config.MAX_DOCUMENT_CHARS

    # Small enough to fit? Use it whole - fastest and loses nothing.
    if len(source_text) <= config.MAX_CONTEXT_CHARS:
        return ContextResult(f"--- DOCUMENT: {source_name} ---\n{source_text}", "direct", details)

    # Too big: retrieve only the most relevant chunks.
    queries = [q.format(focus=focus[:300]) for q in RETRIEVAL_QUERIES]
    found = _run_retrieval_worker(source_text, source_name, queries)
    chunk_count = found["chunk_count"]

    excerpts = [f"--- EXCERPT {n} of {source_name} (part {position + 1} of {chunk_count}) ---\n{text}"
                for n, (position, text) in enumerate(found["chunks"], start=1)]
    text = "\n\n".join(excerpts)[: config.MAX_CONTEXT_CHARS]

    details.update({"chunks_in_document": chunk_count, "chunks_used": len(found["chunks"]),
                    "reused_existing_index": found["reused"]})
    return ContextResult(text, "retrieval", details)


def _run_retrieval_worker(text: str, source_name: str, queries: list[str]) -> dict:
    """Run rag/worker.py in a separate Python process (see that file for why)
    and return its result: {"chunk_count", "reused", "chunks": [[position, text], ...]}."""
    job = {"text": text, "source_name": source_name, "queries": queries,
           "max_chunks": config.MAX_RETRIEVED_CHUNKS}
    completed = subprocess.run(
        [sys.executable, "-m", "rag.worker"],
        input=json.dumps(job), capture_output=True, text=True, encoding="utf-8",
        cwd=config.PROJECT_ROOT, timeout=1800,
    )
    if completed.returncode != 0:
        raise RuntimeError("Document retrieval failed:\n" + completed.stderr[-1500:])
    return json.loads(completed.stdout)


# ----------------------------------------------------- demo sample files --
def list_sample_documents() -> list[str]:
    """File names of the sample documents in /documents (demo examples only)."""
    if not config.DOCUMENTS_DIR.exists():
        return []
    return sorted(p.name for p in config.DOCUMENTS_DIR.iterdir()
                  if p.suffix.lower() in (".md", ".txt"))


def load_sample_documents(names: list[str]) -> str:
    """Join the chosen sample documents into one text, as if uploaded."""
    return "\n\n".join(
        f"# {name}\n{(config.DOCUMENTS_DIR / name).read_text(encoding='utf-8').strip()}"
        for name in names
    )
