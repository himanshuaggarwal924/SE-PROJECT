"""Knowledge base: loading, allowlist, applicability, and real ChromaDB
indexing/filtering (with a fake embedder, so no PyTorch is loaded)."""

import hashlib
import re

import pytest

import config
from rag import knowledge_base as kb

ITEM = """---
id: KB-T-001
title: Test policy
type: policy
source: SAMPLE internal policy
jurisdiction: SAMPLE
effective_date: 2026-01-01
version: "1.0"
applicability: [{app}]
status: {status}
---
> SAMPLE banner (not indexed)

## Limits
Loans above the limit need review.

## Records
Keep records.
"""


def write_item(root, name, app="loan_processing", status="active", text=None):
    path = root / name
    path.write_text(text or ITEM.format(app=app, status=status), encoding="utf-8")
    return path


# ------------------------------------------------------------- the shipped KB --
def test_shipped_kb_items_are_valid_and_labelled_sample():
    items = kb.load_items()
    assert len(items) >= 6
    for item in items:
        assert item.is_valid, (item.path, item.problems)
        assert "SAMPLE" in item.body, f"{item.path} must be labelled SAMPLE"
    assert not any(i.path == "README.md" for i in items)   # no front-matter -> skipped


def test_shipped_kb_has_no_clause_numbers():
    """Sample text must not look like it cites real clauses (e.g. 'Section 12(3)')."""
    pattern = re.compile(r"\b(section|clause|article|regulation|rule)\s+\d", re.IGNORECASE)
    for item in kb.load_items():
        assert not pattern.search(item.body), item.path


def test_allowlist_excludes_superseded_templates_and_unknown_sources(monkeypatch):
    items = {(i.id, i.version): i for i in kb.load_items()}
    assert kb.is_evidence(items[("KB-POL-LOAN-001", "2.0")])
    assert not kb.is_evidence(items[("KB-POL-LOAN-001", "1.0")])       # superseded
    assert not kb.is_evidence(items[("KB-TPL-SRS-001", "1.0")])        # template
    monkeypatch.setattr(config, "KB_ALLOWED_SOURCES", ["Someone else"])
    assert not kb.is_evidence(items[("KB-POL-LOAN-001", "2.0")])       # source not allowlisted


# --------------------------------------------------------------- parsing --
def test_parse_reports_problems(tmp_path):
    write_item(tmp_path, "bad.md", text="---\nid: X\ntype: memo\n---\n## A\nB")
    (item,) = kb.load_items(tmp_path)
    assert not item.is_valid
    assert any("Unknown type" in p for p in item.problems)
    assert any("Missing field 'title'" in p for p in item.problems)


def test_sections_skip_banner(tmp_path):
    write_item(tmp_path, "a.md")
    (item,) = kb.load_items(tmp_path)
    assert kb.item_sections(item) == [("Limits", "Loans above the limit need review."),
                                      ("Records", "Keep records.")]


def test_hash_changes_with_content(tmp_path):
    path = write_item(tmp_path, "a.md")
    before = kb.load_items(tmp_path)[0].content_hash
    path.write_text(path.read_text(encoding="utf-8") + "\nMore.", encoding="utf-8")
    assert kb.load_items(tmp_path)[0].content_hash != before


@pytest.mark.parametrize("text, expected", [
    ("Personal LOAN approval", ["loan_processing", "all"]),
    ("Customer onboarding with KYC", ["kyc", "all"]),
    ("UPI payment with KYC checks", ["kyc", "payments", "all"]),
    ("A to-do list app", ["all"]),
])
def test_detect_applicability(text, expected):
    assert kb.detect_applicability(text) == expected


# ------------------------------------------------- ChromaDB index & filter --
@pytest.fixture
def chroma(monkeypatch):
    """Real ChromaDB in a temp folder, with a cheap deterministic embedder."""
    from rag import vector_store

    def fake_embed(texts):
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            vector = [b / 255 for b in digest[:16]]
            norm = sum(v * v for v in vector) ** 0.5
            vectors.append([v / norm for v in vector])
        return vectors

    monkeypatch.setattr(vector_store, "embed", fake_embed)
    monkeypatch.setattr(vector_store, "_client", None)
    yield vector_store
    monkeypatch.setattr(vector_store, "_client", None)


def test_kb_reindexes_only_changed_files(tmp_path, chroma):
    root = tmp_path / "kb"
    root.mkdir()
    write_item(root, "a.md")
    b = write_item(root, "b.md", app="kyc")

    first = chroma.index_knowledge_base(kb.load_items(root))
    assert sorted(first["reindexed"]) == ["a.md", "b.md"]
    assert chroma.index_knowledge_base(kb.load_items(root))["reindexed"] == []   # unchanged

    b.write_text(b.read_text(encoding="utf-8") + "\nNew line.", encoding="utf-8")
    assert chroma.index_knowledge_base(kb.load_items(root))["reindexed"] == ["b.md"]

    b.unlink()
    result = chroma.index_knowledge_base(kb.load_items(root))
    assert result["removed"] == ["b.md"]
    collection = chroma.get_client().get_collection(config.KB_COLLECTION)
    assert collection.count() == 2      # only a.md's two sections remain


def test_kb_retrieval_filters_status_applicability_and_allowlist(tmp_path, chroma, monkeypatch):
    root = tmp_path / "kb"
    root.mkdir()
    write_item(root, "loan.md", app="loan_processing")
    write_item(root, "old.md", app="loan_processing", status="superseded")
    write_item(root, "kyc.md", app="kyc")
    write_item(root, "all.md", app="all")
    chroma.index_knowledge_base(kb.load_items(root))

    def files(applicability, types=("policy",)):
        found = chroma.retrieve_knowledge_base(["limits"], applicability, list(types), 10)
        return sorted({c["kb_file"] for c in found})

    assert files(["loan_processing", "all"]) == ["all.md", "loan.md"]   # no superseded, no kyc
    assert files(["all"]) == ["all.md"]
    assert files(["loan_processing", "all"], types=["regulation"]) == []
    monkeypatch.setattr(config, "KB_ALLOWED_SOURCES", ["Another publisher"])
    assert files(["loan_processing", "all"]) == []


def test_index_document_with_ready_made_chunks(chroma):
    collection, count, reused = chroma.index_document("ignored", "iv", chunks=["answer one", "answer two"])
    assert (count, reused) == (2, False)
    assert chroma.index_document("ignored", "iv", chunks=["answer one", "answer two"])[2] is True
    found = chroma.retrieve(collection, ["answer two"], 1)
    assert found[0][1] == "answer two" and found[0][0] == 1


def test_best_kb_section_per_topic(tmp_path, chroma):
    root = tmp_path / "kb"
    root.mkdir()
    write_item(root, "loan.md")
    write_item(root, "old.md", status="superseded")
    chroma.index_knowledge_base(kb.load_items(root))
    # Sections are embedded as "title. heading. text"; the fake embedder only
    # matches identical strings, so query with exactly that.
    hints = chroma.best_kb_sections({"limits": "Test policy. Limits. Loans above the limit need review."})
    assert hints["limits"]["section"] == "Limits"
    assert hints["limits"]["similarity"] > 0.99            # identical text with the fake embedder
