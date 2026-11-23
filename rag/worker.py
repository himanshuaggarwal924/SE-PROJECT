"""
rag/worker.py - Does the embedding + retrieval in a SEPARATE Python process.

Why? The embedding libraries (PyTorch + Sentence Transformers) use about
600 MB of RAM once loaded. On an 8 GB laptop that also runs Ollama, keeping
them loaded inside the web app would slow the LLM down. Running them in a
short-lived process means all that memory is given back as soon as the
retrieval is done.

context_loader.py starts this with:  python -m rag.worker
It reads a JSON job from stdin and writes a JSON result to stdout.
"""

import json
import sys


def main() -> None:
    # Libraries sometimes print progress messages; send ALL of that to stderr
    # so stdout contains nothing but our JSON result.
    real_stdout = sys.stdout
    sys.stdout = sys.stderr

    from rag import vector_store

    job = json.loads(sys.stdin.read())
    collection, chunk_count, reused = vector_store.index_document(job["text"], job["source_name"])
    chunks = vector_store.retrieve(collection, job["queries"], job["max_chunks"])

    real_stdout.write(json.dumps({"chunk_count": chunk_count, "reused": reused, "chunks": chunks}))


if __name__ == "__main__":
    main()
