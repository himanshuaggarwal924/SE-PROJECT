"""
context_loader.py - Prepares the source material the Requirements Agent reads.

This is the "seam" between the agents and the RAG layer: agents only ever
receive strings of context, and never need to know how they were made.

The user's document:
    no document         -> method "none"       (the typed description is enough)
    small document      -> method "direct"     (whole text, split into excerpts)
    large document      -> method "retrieval"  (chunk -> embed -> ChromaDB -> best chunks)

The knowledge base (kb/, if KB_ENABLED): the most relevant active,
allowlisted items for this run's applicability (loan_processing, kyc...).

Document excerpts are labelled [C1], [C2]... and KB excerpts [KB-1], [KB-2]...
The chunk map (ID -> text, origin, document, position, similarity, KB
metadata) is returned too, so the agents can cite excerpts and Python can
check those citations.
"""

import json
import subprocess
import sys
from dataclasses import dataclass, field

import config
from rag.chunker import chunk_text
from rag.knowledge_base import detect_applicability
from security.injection import scan

NO_SOURCE_TEXT = "No source document was provided. Use the functionality description above."
NO_KB_TEXT = "No knowledge-base excerpts are available."

# Searches used to pull relevant chunks out of a large document and the KB.
# Several different searches give a balanced mix: features AND quality needs.
RETRIEVAL_QUERIES = [
    "{focus}",
    "{focus} business rules, workflow steps, decisions, limits and thresholds",
    "security, access control, encryption and data privacy requirements",
    "regulatory compliance, KYC, AML, audit trail and record retention",
    "performance, availability, response time and scalability targets",
]


@dataclass
class ContextResult:
    text: str                                   # document excerpts for the prompt
    method: str                                 # "none", "direct" or "retrieval"
    details: dict = field(default_factory=dict)  # numbers for the UI and audit log
    chunk_map: dict = field(default_factory=dict)  # "C1"/"KB-1" -> excerpt info
    kb_text: str = NO_KB_TEXT                   # KB excerpts for the Requirements Agent
    kb_text_full: str = NO_KB_TEXT              # more KB excerpts, for the Compliance Agent


def quarantine(items: list, text_of, source: str, details: dict) -> list:
    """Drop items whose text looks like prompt injection (QUARANTINE_INJECTION);
    record what was dropped in details["quarantined"] (shown in the UI and logged)."""
    if not config.QUARANTINE_INJECTION:
        return items
    kept = []
    for item in items:
        text = text_of(item)
        found = scan(text)
        if found:
            details.setdefault("quarantined", []).append(
                {"source": source, "patterns": found, "preview": " ".join(text.split())[:160]})
        else:
            kept.append(item)
    return kept


def label_excerpts(chunks: list[tuple[int, str, float | None]], source_name: str,
                   total_chunks: int, char_budget: int | None = None) -> tuple[str, dict]:
    """Label (position, text, similarity) chunks as [C1], [C2]... and build the
    chunk map. With a char_budget, chunks that don't fit are left out (so the
    map only ever contains excerpts the model really saw)."""
    parts, chunk_map = [], {}
    used = 0
    for position, text, similarity in chunks:
        cid = f"C{len(chunk_map) + 1}"
        block = f"[{cid}] ({source_name}, part {position + 1} of {total_chunks})\n{text}"
        if char_budget is not None and chunk_map and used + len(block) > char_budget:
            break
        parts.append(block)
        used += len(block) + 2
        chunk_map[cid] = {"text": text, "origin": "document", "document": source_name,
                          "position": position, "similarity": similarity}
    return "\n\n".join(parts), chunk_map


def label_kb_excerpts(kb_chunks: list[dict]) -> tuple[str, str, dict]:
    """Label KB sections (best first) as [KB-1], [KB-2]...

    Returns (text for the Requirements Agent, text for the Compliance Agent,
    chunk map). The Requirements Agent gets the first KB_MAX_CHUNKS within
    KB_CONTEXT_CHARS; the Compliance Agent gets up to KB_MAX_CHUNKS_COMPLIANCE
    within KB_CONTEXT_CHARS_COMPLIANCE. Each chunk records who saw it, so a
    citation is only valid for an agent that was actually shown the excerpt.
    """
    short, full, chunk_map = [], [], {}
    used_short = used_full = 0
    for chunk in kb_chunks[: config.KB_MAX_CHUNKS_COMPLIANCE]:
        cid = f"KB-{len(chunk_map) + 1}"
        block = (f"[{cid}] ({chunk['title']} v{chunk['version']}, {chunk['type']}, "
                 f"section: {chunk['section']})\n{chunk['text']}")
        if chunk_map and used_full + len(block) > config.KB_CONTEXT_CHARS_COMPLIANCE:
            break
        full.append(block)
        used_full += len(block) + 2
        for_requirements = (len(short) < config.KB_MAX_CHUNKS and len(short) == len(chunk_map)
                            and (not short or used_short + len(block) <= config.KB_CONTEXT_CHARS))
        if for_requirements:
            short.append(block)
            used_short += len(block) + 2
        chunk_map[cid] = {**chunk, "origin": "kb", "document": chunk["title"], "position": None,
                          "for_requirements": for_requirements}
    return "\n\n".join(short) or NO_KB_TEXT, "\n\n".join(full) or NO_KB_TEXT, chunk_map


def label_segments(picked: list[tuple[int, float | None]], segments: list[dict],
                   char_budget: int) -> tuple[str, dict]:
    """Label transcript answers (index, similarity) as [C1], [C2]... Each
    chunk keeps its speaker, interview and turn, so a requirement citing it
    links back to the exact answer."""
    from interview.engine import segment_label
    parts, chunk_map, used = [], {}, 0
    for index, similarity in picked:
        segment = segments[index]
        cid = f"C{len(chunk_map) + 1}"
        block = f"[{cid}] ({segment_label(segment)})\n{segment['text']}"
        if chunk_map and used + len(block) > char_budget:
            break
        parts.append(block)
        used += len(block) + 2
        chunk_map[cid] = {**{k: v for k, v in segment.items() if k != "text"}, "text": segment["text"],
                          "origin": "transcript", "document": segment_label(segment),
                          "position": index, "similarity": similarity}
    return "\n\n".join(parts), chunk_map


def build_reference_context(source_text: str, source_name: str, focus: str,
                            segments: list[dict] | None = None) -> ContextResult:
    """Turn the user's document text (and the KB) into prompt-sized, labelled context.

    focus:    what the user wants requirements for - used as the search query.
    segments: interview answers (interview/engine.transcript_segments); used
              instead of source_text, one labelled excerpt per answer.
    """
    if segments:
        return _transcript_context(segments, source_name, focus)
    source_text = (source_text or "").strip()
    details: dict = {}
    if source_text:
        details = {"source": source_name, "document_chars": len(source_text)}
        if len(source_text) > config.MAX_DOCUMENT_CHARS:
            source_text = source_text[: config.MAX_DOCUMENT_CHARS]
            details["truncated_to_chars"] = config.MAX_DOCUMENT_CHARS

    if not source_text:
        method = "none"
    elif len(source_text) <= config.MAX_CONTEXT_CHARS:
        method = "direct"
    else:
        method = "retrieval"

    document_job = None
    if method == "retrieval":
        document_job = {"text": source_text, "source_name": source_name,
                        "max_chunks": config.MAX_RETRIEVED_CHUNKS}
    found = _retrieve(document_job, focus, source_text, details)

    # --- the document part ---
    if method == "none":
        text, chunk_map = NO_SOURCE_TEXT, {}
    elif method == "direct":
        # Use it whole - fastest and loses nothing. It is still split
        # (without overlap) into labelled excerpts so it can be cited.
        pieces = chunk_text(source_text, config.CHUNK_SIZE, 0)
        kept = quarantine([(i, p, None) for i, p in enumerate(pieces)], lambda c: c[1], source_name, details)
        text, chunk_map = label_excerpts(kept, source_name, len(pieces))
    else:
        chunks = [(c[0], c[1], c[2] if len(c) > 2 else None) for c in found["chunks"]]
        chunks = quarantine(chunks, lambda c: c[1], source_name, details)
        text, chunk_map = label_excerpts(chunks, source_name, found["chunk_count"],
                                         config.MAX_CONTEXT_CHARS)
        details.update({"chunks_in_document": found["chunk_count"],
                        "reused_existing_index": found["reused"]})
    if method != "none":
        details["chunks_used"] = len(chunk_map)

    kb_text, kb_text_full, kb_map = _kb_part(found, details)
    return ContextResult(text, method, details, {**chunk_map, **kb_map}, kb_text, kb_text_full)


def _retrieve(document_job: dict | None, focus: str, source_text: str, details: dict) -> dict:
    """One worker call for whatever retrieval is needed (document and/or KB).
    A KB-only failure is noted in details; a document failure is raised."""
    queries = [q.format(focus=focus[:300]) for q in RETRIEVAL_QUERIES]
    job = {"queries": queries, "document": document_job, "kb": None}
    if config.KB_ENABLED:
        applicability = detect_applicability(focus, source_text[:20000])
        details["kb_applicability"] = applicability
        job["kb"] = {"applicability": applicability, "types": config.KB_TYPES_FOR_REQUIREMENTS,
                     "max_chunks": max(config.KB_MAX_CHUNKS, config.KB_MAX_CHUNKS_COMPLIANCE)}
    found = {"chunk_count": 0, "reused": False, "chunks": [], "kb_chunks": []}
    if job["document"] or job["kb"]:
        try:
            found = _run_retrieval_worker(job)
        except Exception as error:
            if document_job:
                raise   # without retrieval there is no usable document context
            details["kb_error"] = str(error)[-500:]   # KB only: carry on without it
    return found


def _kb_part(found: dict, details: dict) -> tuple[str, str, dict]:
    kb_text, kb_text_full, kb_map = NO_KB_TEXT, NO_KB_TEXT, {}
    kb_chunks = quarantine(found.get("kb_chunks") or [], lambda c: c["text"], "knowledge base", details)
    if kb_chunks:
        kb_text, kb_text_full, kb_map = label_kb_excerpts(kb_chunks)
    if config.KB_ENABLED:
        details["kb_chunks_used"] = len(kb_map)
        details["kb_chunks_for_requirements"] = sum(c["for_requirements"] for c in kb_map.values())
        details["kb_items_used"] = sorted({c["kb_id"] for c in kb_map.values()})
        if found.get("kb_index"):
            details["kb_reindexed"] = found["kb_index"].get("reindexed", [])
    return kb_text, kb_text_full, kb_map


def _transcript_context(segments: list[dict], source_name: str, focus: str) -> ContextResult:
    """Interview answers as context: all of them if they fit, otherwise the
    most relevant answers (embedded as-is, one chunk per answer)."""
    joined = "\n\n".join(s["text"] for s in segments)
    details = {"source": source_name, "document_chars": len(joined), "answers": len(segments),
               "interviews": sorted({s["interview_id"] for s in segments})}
    if len(joined) + 120 * len(segments) <= config.MAX_CONTEXT_CHARS:
        method, document_job = "transcript", None
    else:
        method = "transcript_retrieval"
        document_job = {"text": joined, "source_name": source_name, "segments": [s["text"] for s in segments],
                        "max_chunks": config.MAX_RETRIEVED_CHUNKS}
    found = _retrieve(document_job, focus, joined, details)

    if method == "transcript":
        picked = [(i, None) for i in range(len(segments))]
    else:
        picked = [(c[0], c[2] if len(c) > 2 else None) for c in found["chunks"]]
        details["reused_existing_index"] = found["reused"]
    picked = quarantine(picked, lambda p: segments[p[0]]["text"], "interview answers", details)
    text, chunk_map = label_segments(picked, segments, config.MAX_CONTEXT_CHARS)
    details["chunks_used"] = len(chunk_map)
    kb_text, kb_text_full, kb_map = _kb_part(found, details)
    return ContextResult(text, method, details, {**chunk_map, **kb_map}, kb_text, kb_text_full)


def chunks_visible_to(chunk_map: dict, audience: str) -> dict:
    """The part of the chunk map an agent was shown. audience: "requirements"
    (document excerpts + the first KB excerpts) or "compliance" (everything)."""
    if audience == "compliance":
        return dict(chunk_map)
    return {cid: c for cid, c in chunk_map.items()
            if c.get("origin") != "kb" or c.get("for_requirements", True)}


def _run_retrieval_worker(job: dict) -> dict:
    """Run rag/worker.py in a separate Python process (see that file for why)
    and return its result (format documented in rag/worker.py)."""
    completed = subprocess.run(
        [sys.executable, "-m", "rag.worker"],
        input=json.dumps(job), capture_output=True, text=True, encoding="utf-8",
        cwd=config.PROJECT_ROOT, timeout=1800,
    )
    if completed.returncode != 0:
        raise RuntimeError("Document retrieval failed:\n" + completed.stderr[-1500:])
    return json.loads(completed.stdout)


def text_similarities(texts: list[str]) -> list[list[float]]:
    """Cosine similarity between every pair of texts (MiniLM, in the worker)."""
    found = _run_retrieval_worker({"queries": [], "document": None, "kb": None,
                                   "similarity_texts": texts})
    return found["similarity_matrix"]


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
