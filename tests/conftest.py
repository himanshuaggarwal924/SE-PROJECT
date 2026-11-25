"""
Shared pytest fixtures.

Every test runs with logs/ and auth/users.yaml redirected to a temporary
folder (autouse), so the tests never touch the real audit log or accounts.
"""

import pytest

import config
import llm_service
from tests.mock_llm import MockLLM


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    """Point every file the app writes at a temporary folder."""
    logs = tmp_path / "logs"
    monkeypatch.setattr(config, "LOGS_DIR", logs)
    monkeypatch.setattr(config, "AUDIT_LOG_FILE", logs / "audit_log.jsonl")
    monkeypatch.setattr(config, "USERS_FILE", tmp_path / "auth" / "users.yaml")
    monkeypatch.setattr(config, "VECTOR_DB_DIR", tmp_path / "vector_store")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "APP_DB", tmp_path / "data" / "app.sqlite")
    monkeypatch.setattr(config, "CHECKPOINT_DB", tmp_path / "data" / "checkpoints.sqlite")
    monkeypatch.setattr(config, "ENCRYPTION_KEY_FILE", tmp_path / "keys" / "secret.key")
    from security import crypto
    crypto.reset_cache()
    yield tmp_path
    # Close the per-test databases so the next test starts clean.
    import pipeline
    from storage import db
    db.close_all()
    pipeline.reset_checkpointer()


@pytest.fixture
def mock_llm(monkeypatch) -> MockLLM:
    """Replace the real Ollama call with canned JSON per agent."""
    mock = MockLLM()
    monkeypatch.setattr(llm_service, "chat", mock.chat)
    return mock


@pytest.fixture(autouse=True)
def fake_retrieval(monkeypatch):
    """Replace the RAG worker process (PyTorch + ChromaDB) with a stub (autouse,
    so no test ever starts the real worker). Document retrieval returns the
    first chunks of the text; KB retrieval returns the first sections of the
    allowlisted, matching KB items. Returns the list of jobs received."""
    import context_loader
    from rag.chunker import chunk_text
    from rag.knowledge_base import is_evidence, item_sections, load_items

    jobs = []

    def run(job):
        jobs.append(job)
        result = {"chunk_count": 0, "reused": False, "chunks": [], "kb_chunks": [],
                  "kb_index": {"files": 0, "reindexed": [], "removed": []}}
        if job.get("topic_texts"):
            # Best KB section by word overlap; similarity 0.6 if words overlap, else 0.1.
            from checks.quality import content_words, jaccard
            sections = [(item, heading, text) for item in load_items() if is_evidence(item)
                        for heading, text in item_sections(item)]
            hints = {}
            for key, topic_text in job["topic_texts"].items():
                words = content_words(topic_text)
                score, item, heading = max(((jaccard(words, content_words(text)), item, heading)
                                            for item, heading, text in sections), key=lambda x: x[0])
                hints[key] = {"kb_id": item.id, "title": item.title, "section": heading,
                              "similarity": 0.6 if score > 0 else 0.1}
            result["topic_hints"] = hints
        if job.get("similarity_texts"):
            from checks.quality import content_words, jaccard
            words = [content_words(t) for t in job["similarity_texts"]]
            result["similarity_matrix"] = [[1.0 if a is b else jaccard(a, b) for b in words]
                                           for a in words]
        if job.get("document"):
            chunks = job["document"].get("segments") or \
                chunk_text(job["document"]["text"], config.CHUNK_SIZE, config.CHUNK_OVERLAP)
            result["chunk_count"] = len(chunks)
            result["chunks"] = [[i, c, 0.5] for i, c in
                                enumerate(chunks[: job["document"]["max_chunks"]])]
        if job.get("kb"):
            kb = job["kb"]
            for item in load_items():
                if not (is_evidence(item) and item.type in kb["types"]
                        and set(item.applicability) & set(kb["applicability"])):
                    continue
                heading, text = item_sections(item)[0]
                result["kb_chunks"].append({
                    "text": text, "kb_id": item.id, "title": item.title, "section": heading,
                    "type": item.type, "source": item.source, "version": item.version,
                    "kb_file": item.path, "similarity": 0.5})
            result["kb_chunks"] = result["kb_chunks"][: kb["max_chunks"]]
        return result

    monkeypatch.setattr(context_loader, "_run_retrieval_worker", run)
    return jobs
