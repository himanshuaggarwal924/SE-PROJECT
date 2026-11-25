"""
rag/vector_store.py - Embeds document chunks and searches them (ChromaDB).

  * Embeddings: Sentence Transformers "all-MiniLM-L6-v2" - a small (~90 MB),
    CPU-friendly model that turns text into 384 numbers capturing its meaning.
  * Storage: ChromaDB, saved on disk in the vector_store/ folder, so the same
    document is only embedded once even across app restarts.

This module is normally run inside rag/worker.py (a separate process), so
the web app itself never loads the heavy embedding libraries.
"""

import hashlib
import json
import os

# Keep the embedding libraries fully local and quiet.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import chromadb
from chromadb.config import Settings

import config
from rag.chunker import chunk_text

_embedder = None   # loaded on first use, then reused (loading takes a few seconds)
_client = None


def get_embedder():
    """Load the embedding model once. The first time ever, it is downloaded
    (~90 MB) into the models/ folder; after that it loads from disk offline."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer  # slow import, so do it lazily
        try:
            _embedder = SentenceTransformer(config.EMBEDDING_MODEL, device="cpu",
                                            cache_folder=str(config.MODELS_DIR),
                                            local_files_only=True)
        except Exception:
            # Not downloaded yet - fetch it once.
            _embedder = SentenceTransformer(config.EMBEDDING_MODEL, device="cpu",
                                            cache_folder=str(config.MODELS_DIR))
    return _embedder


def embed(texts: list[str]) -> list[list[float]]:
    """Turn texts into embedding vectors (normalised, so distance = meaning gap)."""
    vectors = get_embedder().encode(texts, batch_size=16, normalize_embeddings=True,
                                    show_progress_bar=False)
    return vectors.tolist()


def get_client():
    """Open (once) the ChromaDB database stored in the vector_store/ folder."""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(config.VECTOR_DB_DIR),
                                            settings=Settings(anonymized_telemetry=False))
    return _client


def index_document(text: str, source_name: str, chunks: list[str] | None = None):
    """Chunk + embed + store a document. Returns (collection, number of chunks,
    reused?) - if this exact text was indexed before, the stored copy is reused.

    chunks: ready-made chunks (e.g. one per interview answer) instead of
            splitting the text; positions then match the list order.
    """
    # The collection name is a fingerprint of the content: same content = same name.
    key = text if chunks is None else "\x1e".join(chunks)
    prefix = "doc" if chunks is None else "seg"
    fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    collection = get_client().get_or_create_collection(
        name=f"{prefix}_{fingerprint}", metadata={"source_name": source_name}
    )
    if collection.count() > 0:
        return collection, collection.count(), True

    if chunks is None:
        chunks = chunk_text(text, config.CHUNK_SIZE, config.CHUNK_OVERLAP)
    collection.add(
        ids=[f"chunk-{i}" for i in range(len(chunks))],
        documents=chunks,
        embeddings=embed(chunks),
        metadatas=[{"position": i} for i in range(len(chunks))],
    )
    return collection, len(chunks), False


def distance_to_similarity(distance: float) -> float:
    """ChromaDB's default distance is the SQUARED L2 distance. For normalised
    vectors that equals 2 - 2*cosine, so cosine similarity = 1 - distance/2."""
    return round(min(max(1 - distance / 2, 0.0), 1.0), 4)


def retrieve(collection, queries: list[str], max_chunks: int) -> list[tuple[int, str, float]]:
    """Find the chunks most relevant to ANY of the queries.

    Returns up to `max_chunks` (position, text, cosine similarity) tuples, in
    the order they appear in the document so the excerpts read naturally.
    """
    per_query = min(config.CHUNKS_PER_QUERY, collection.count())
    results = collection.query(query_embeddings=embed(queries), n_results=per_query)

    # Keep each chunk's best (smallest) distance across all the queries.
    best = {}  # position -> (distance, text)
    # Chroma returns one list of matches per query.
    for distances, texts, metas in zip(results["distances"], results["documents"], results["metadatas"]):
        for distance, text, meta in zip(distances, texts, metas):
            position = meta["position"]
            if position not in best or distance < best[position][0]:
                best[position] = (distance, text)

    closest = sorted(best.items(), key=lambda item: item[1][0])[:max_chunks]
    return sorted((position, text, distance_to_similarity(distance))
                  for position, (distance, text) in closest)


# ------------------------------------------------------------ knowledge base --
def _kb_manifest_file():
    return config.VECTOR_DB_DIR / "kb_manifest.json"


def index_knowledge_base(items) -> dict:
    """Bring the KB collection up to date with the kb/ folder.

    Only files whose content hash changed (or that are new) are re-embedded;
    chunks of deleted files are removed. Returns what was done.
    """
    from rag.knowledge_base import item_sections

    collection = get_client().get_or_create_collection(name=config.KB_COLLECTION)
    manifest_file = _kb_manifest_file()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}

    valid = {item.path: item for item in items if item.is_valid}
    changed = [item for path, item in valid.items() if manifest.get(path) != item.content_hash]
    removed = [path for path in manifest if path not in valid]

    for path in removed + [item.path for item in changed]:
        collection.delete(where={"kb_file": path})

    for item in changed:
        sections = item_sections(item)
        if not sections:
            continue
        flags = {f"app_{tag}": True for tag in item.applicability}
        collection.add(
            ids=[f"{item.path}#{n}" for n in range(len(sections))],
            documents=[text for _, text in sections],
            embeddings=embed([f"{item.title}. {heading}. {text}" for heading, text in sections]),
            metadatas=[{"kb_file": item.path, "kb_id": item.id, "title": item.title,
                        "section": heading, "type": item.type, "source": item.source,
                        "version": item.version, "status": item.status, **flags}
                       for heading, _ in sections],
        )

    manifest = {path: item.content_hash for path, item in valid.items()}
    config.VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"files": len(valid), "reindexed": [i.path for i in changed], "removed": removed}


def _all_of(conditions: list[dict]) -> dict:
    """ChromaDB needs $and/$or to have at least 2 parts."""
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


def kb_filter(applicability: list[str], types: list[str]) -> dict:
    """Metadata filter: active, allowlisted type + source, matching applicability."""
    allowed_types = [t for t in types if t in config.KB_EVIDENCE_TYPES]
    app = [{f"app_{tag}": True} for tag in applicability]
    return _all_of([
        {"status": "active"},
        {"type": {"$in": allowed_types or ["(none)"]}},
        {"source": {"$in": config.KB_ALLOWED_SOURCES or ["(none)"]}},
        app[0] if len(app) == 1 else {"$or": app},
    ])


def retrieve_knowledge_base(queries: list[str], applicability: list[str], types: list[str],
                            max_chunks: int) -> list[dict]:
    """The KB sections most relevant to ANY query, best first."""
    collection = get_client().get_or_create_collection(name=config.KB_COLLECTION)
    if collection.count() == 0:
        return []
    results = collection.query(query_embeddings=embed(queries),
                               n_results=min(config.CHUNKS_PER_QUERY, collection.count()),
                               where=kb_filter(applicability, types))
    best = {}  # chunk id -> (distance, text, metadata)
    for ids, distances, texts, metas in zip(results["ids"], results["distances"],
                                            results["documents"], results["metadatas"]):
        for cid, distance, text, meta in zip(ids, distances, texts, metas):
            if cid not in best or distance < best[cid][0]:
                best[cid] = (distance, text, meta)
    closest = sorted(best.values(), key=lambda item: item[0])[:max_chunks]
    return [{"text": text, "kb_id": meta["kb_id"], "title": meta["title"],
             "section": meta["section"], "type": meta["type"], "source": meta["source"],
             "version": meta["version"], "kb_file": meta["kb_file"],
             "similarity": distance_to_similarity(distance)}
            for distance, text, meta in closest]


def best_kb_sections(texts: dict[str, str]) -> dict[str, dict]:
    """For each named text (e.g. an interview topic description), the single
    most similar active, allowlisted KB section - any applicability."""
    collection = get_client().get_or_create_collection(name=config.KB_COLLECTION)
    if collection.count() == 0 or not texts:
        return {}
    where = _all_of([
        {"status": "active"},
        {"type": {"$in": config.KB_EVIDENCE_TYPES or ["(none)"]}},
        {"source": {"$in": config.KB_ALLOWED_SOURCES or ["(none)"]}},
    ])
    keys = list(texts)
    results = collection.query(query_embeddings=embed([texts[k] for k in keys]), n_results=1, where=where)
    found = {}
    for key, distances, metas in zip(keys, results["distances"], results["metadatas"]):
        if distances:
            meta = metas[0]
            found[key] = {"kb_id": meta["kb_id"], "title": meta["title"], "section": meta["section"],
                          "similarity": distance_to_similarity(distances[0])}
    return found
