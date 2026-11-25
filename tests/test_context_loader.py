import config
from context_loader import (NO_KB_TEXT, NO_SOURCE_TEXT, build_reference_context,
                            list_sample_documents, load_sample_documents)


def test_no_document_uses_description_and_kb_only(fake_retrieval):
    result = build_reference_context("   ", "x.md", "Personal loan approval")
    assert result.method == "none"
    assert result.text == NO_SOURCE_TEXT
    assert fake_retrieval[0]["document"] is None          # no document retrieval
    assert "loan_processing" in fake_retrieval[0]["kb"]["applicability"]
    assert result.kb_text.startswith("[KB-1] (")
    assert all(c["origin"] == "kb" for c in result.chunk_map.values())


def test_kb_can_be_switched_off(fake_retrieval, monkeypatch):
    monkeypatch.setattr(config, "KB_ENABLED", False)
    result = build_reference_context("", "", "loans")
    assert fake_retrieval == []                          # worker not started at all
    assert result.kb_text == NO_KB_TEXT and result.chunk_map == {}


def test_kb_failure_does_not_stop_a_run_without_retrieval(monkeypatch):
    import context_loader

    def broken(job):
        raise RuntimeError("torch exploded")
    monkeypatch.setattr(context_loader, "_run_retrieval_worker", broken)
    result = build_reference_context("Small doc.", "d.md", "loans")
    assert result.method == "direct"
    assert "torch exploded" in result.details["kb_error"]
    assert result.kb_text == NO_KB_TEXT


def test_document_at_limit_is_used_whole_as_labelled_excerpts(fake_retrieval):
    text = ("Loans need checks. " * 400)[: config.MAX_CONTEXT_CHARS]
    result = build_reference_context(text, "spec.md", "loans")
    assert result.method == "direct"
    assert fake_retrieval[0]["document"] is None
    assert result.text.startswith("[C1] (spec.md, part 1 of")
    doc_chunks = [c for c in result.chunk_map.values() if c["origin"] == "document"]
    # Nothing is lost: the excerpts together are the whole document.
    assert "".join(c["text"] for c in doc_chunks).replace(" ", "") == text.replace(" ", "")
    assert all(c["similarity"] is None for c in doc_chunks)
    assert all(f"[{cid}]" in result.text for cid, c in result.chunk_map.items()
               if c["origin"] == "document")


def test_document_over_limit_uses_retrieval(fake_retrieval):
    text = "Loans above limits need review. " * 400  # ~12,800 chars
    result = build_reference_context(text, "policy.md", "Loan approval")
    assert result.method == "retrieval"
    queries = fake_retrieval[0]["queries"]
    assert queries[0] == "Loan approval"
    assert all("{focus}" not in q for q in queries)
    assert result.text.startswith("[C1] (policy.md, part 1 of")
    assert len(result.text) <= config.MAX_CONTEXT_CHARS
    doc_ids = [cid for cid, c in result.chunk_map.items() if c["origin"] == "document"]
    assert result.details["chunks_used"] == len(doc_ids) <= config.MAX_RETRIEVED_CHUNKS
    # Only excerpts really shown to the model are in the chunk map.
    assert all(f"[{cid}]" in result.text for cid in doc_ids)


def test_retrieval_similarity_and_kb_metadata_in_chunk_map(monkeypatch):
    import context_loader
    monkeypatch.setattr(context_loader, "_run_retrieval_worker", lambda job: {
        "chunk_count": 10, "reused": True,
        "chunks": [[3, "Limit is 50,000.", 0.55], [7, "Retain for 5 years.", 0.41]],
        "kb_chunks": [{"text": "Encrypt data.", "kb_id": "KB-SEC-001", "title": "Std",
                       "section": "Encryption", "type": "security_standard",
                       "source": "S", "version": "1.0", "kb_file": "s.md", "similarity": 0.7}]})
    result = build_reference_context("x" * (config.MAX_CONTEXT_CHARS + 1), "p.md", "loans")
    assert result.chunk_map["C1"] == {"text": "Limit is 50,000.", "origin": "document",
                                      "document": "p.md", "position": 3, "similarity": 0.55}
    assert result.chunk_map["KB-1"]["kb_id"] == "KB-SEC-001"
    assert result.chunk_map["KB-1"]["origin"] == "kb"
    assert "part 8 of 10" in result.text
    assert result.kb_text.startswith("[KB-1] (Std v1.0, security_standard, section: Encryption)")
    assert result.details["kb_items_used"] == ["KB-SEC-001"]


def test_huge_document_is_truncated(fake_retrieval, monkeypatch):
    monkeypatch.setattr(config, "MAX_DOCUMENT_CHARS", 20_000)
    result = build_reference_context("b " * 50_000, "big.txt", "x")
    assert result.details["truncated_to_chars"] == 20_000
    assert len(fake_retrieval[0]["document"]["text"]) == 20_000


def test_sample_documents_are_listed_and_loaded():
    names = list_sample_documents()
    assert "loan_approval_policy.md" in names
    text = load_sample_documents(names[:1])
    assert text.startswith(f"# {names[0]}")
