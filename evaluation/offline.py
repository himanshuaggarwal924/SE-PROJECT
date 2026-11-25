"""
evaluation/offline.py - Fakes for `run_eval.py --mock`: a canned LLM (the same
mock the test suite uses) and a word-overlap "embedding" worker, so the whole
evaluation can be smoke-tested in seconds without Ollama or PyTorch.
The numbers it produces are meaningless - it only checks the wiring.
"""

import config
import context_loader
import llm_service
from checks.quality import content_words, jaccard
from rag.chunker import chunk_text


def _fake_worker(job: dict) -> dict:
    result = {"chunk_count": 0, "reused": False, "chunks": [], "kb_chunks": [], "kb_index": None}
    if job.get("similarity_texts"):
        words = [content_words(t) for t in job["similarity_texts"]]
        result["similarity_matrix"] = [[1.0 if a is b else min(1.0, 2 * jaccard(a, b)) for b in words]
                                       for a in words]
    if job.get("document"):
        chunks = chunk_text(job["document"]["text"], config.CHUNK_SIZE, config.CHUNK_OVERLAP)
        result["chunk_count"] = len(chunks)
        result["chunks"] = [[i, c, 0.5] for i, c in enumerate(chunks[: job["document"]["max_chunks"]])]
    return result


def install() -> None:
    """Fake the model and the worker, and send every log/database write to a
    temporary folder so a mock run never touches the real audit trail."""
    import tempfile
    from pathlib import Path

    from tests.mock_llm import MockLLM
    temp = Path(tempfile.mkdtemp(prefix="finreq_mock_eval_"))
    config.LOGS_DIR = temp / "logs"
    config.AUDIT_LOG_FILE = config.LOGS_DIR / "audit_log.jsonl"
    config.DATA_DIR = temp / "data"
    config.APP_DB = config.DATA_DIR / "app.sqlite"
    config.CHECKPOINT_DB = config.DATA_DIR / "checkpoints.sqlite"
    config.VECTOR_DB_DIR = temp / "vector_store"
    llm_service.chat = MockLLM().chat
    context_loader._run_retrieval_worker = _fake_worker
    config.KB_ENABLED = False
