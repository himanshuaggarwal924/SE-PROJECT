"""
The RAG (Retrieval-Augmented Generation) package.

  chunker.py        - split long text into overlapping chunks
  vector_store.py   - embed chunks locally (MiniLM) and search them with ChromaDB
  knowledge_base.py - load the versioned kb/ items, allowlist, applicability
  worker.py         - runs embedding work in a short-lived separate process

It is used through context_loader.py, so agents never need to know whether
their context came from retrieval or was loaded directly.
"""
