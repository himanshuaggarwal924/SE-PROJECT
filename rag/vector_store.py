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


def index_document(text: str, source_name: str):
    """Chunk + embed + store a document. Returns (collection, number of chunks,
    reused?) - if this exact text was indexed before, the stored copy is reused."""
    # The collection name is a fingerprint of the text: same text = same name.
    fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    collection = get_client().get_or_create_collection(
        name=f"doc_{fingerprint}", metadata={"source_name": source_name}
    )
    if collection.count() > 0:
        return collection, collection.count(), True

    chunks = chunk_text(text, config.CHUNK_SIZE, config.CHUNK_OVERLAP)
    collection.add(
        ids=[f"chunk-{i}" for i in range(len(chunks))],
        documents=chunks,
        embeddings=embed(chunks),
        metadatas=[{"position": i} for i in range(len(chunks))],
    )
    return collection, len(chunks), False


def retrieve(collection, queries: list[str], max_chunks: int) -> list[tuple[int, str]]:
    """Find the chunks most relevant to ANY of the queries.

    Returns up to `max_chunks` (position, text) pairs, in the order they
    appear in the document so the excerpts read naturally.
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
    return sorted((position, text) for position, (_, text) in closest)
