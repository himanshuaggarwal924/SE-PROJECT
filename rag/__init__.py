"""
The RAG (Retrieval-Augmented Generation) package.

  chunker.py      - split long text into overlapping chunks
  vector_store.py - embed chunks locally and search them with ChromaDB

It is used only through context_loader.py, so agents never need to know
whether their context came from retrieval or was loaded directly.
"""
