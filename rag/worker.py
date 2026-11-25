"""
rag/worker.py - Does the embedding + retrieval in a SEPARATE Python process.

Why? The embedding libraries (PyTorch + Sentence Transformers) use about
600 MB of RAM once loaded. On an 8 GB laptop that also runs Ollama, keeping
them loaded inside the web app would slow the LLM down. Running them in a
short-lived process means all that memory is given back as soon as the
retrieval is done.

context_loader.py starts this with:  python -m rag.worker
It reads a JSON job from stdin and writes a JSON result to stdout.

Job:    {"queries": [...],
         "document": {"text", "source_name", "max_chunks", "segments" (optional:
                      ready-made chunks, e.g. one per interview answer)} or null,
         "kb": {"applicability": [...], "types": [...], "max_chunks"} or null,
         "similarity_texts": [...] (optional),
         "topic_texts": {name: text} (optional: best KB section per text)}
Result: {"chunk_count", "reused", "chunks": [[position, text, similarity], ...],
         "kb_chunks": [{text, kb_id, title, section, ..., similarity}, ...],
         "kb_index": {"files", "reindexed", "removed"},
         "similarity_matrix": [[cosine, ...], ...] (if similarity_texts was given),
         "topic_hints": {name: {kb_id, title, section, similarity}} (if topic_texts was given)}
"""

import json
import sys


def run_job(job: dict) -> dict:
    from rag import vector_store

    result = {"chunk_count": 0, "reused": False, "chunks": [], "kb_chunks": [], "kb_index": None}
    document = job.get("document")
    if document:
        collection, chunk_count, reused = vector_store.index_document(
            document["text"], document["source_name"], chunks=document.get("segments"))
        result.update(chunk_count=chunk_count, reused=reused,
                      chunks=vector_store.retrieve(collection, job["queries"], document["max_chunks"]))

    texts = job.get("similarity_texts")
    if texts:
        # Embeddings are normalised, so the dot product is the cosine similarity.
        vectors = vector_store.embed(texts)
        result["similarity_matrix"] = [[round(sum(x * y for x, y in zip(a, b)), 4) for b in vectors]
                                       for a in vectors]

    kb = job.get("kb")
    if kb or job.get("topic_texts"):
        from rag.knowledge_base import load_items
        result["kb_index"] = vector_store.index_knowledge_base(load_items())
    if job.get("topic_texts"):
        result["topic_hints"] = vector_store.best_kb_sections(job["topic_texts"])
    if kb:
        result["kb_chunks"] = vector_store.retrieve_knowledge_base(
            job["queries"], kb["applicability"], kb["types"], kb["max_chunks"])
    return result


def main() -> None:
    # Libraries sometimes print progress messages; send ALL of that to stderr
    # so stdout contains nothing but our JSON result.
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    result = run_job(json.loads(sys.stdin.read()))
    real_stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
