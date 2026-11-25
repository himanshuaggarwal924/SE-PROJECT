"""Phase 12: encryption at rest (Fernet, key file outside the repository)."""

import sqlite3

import pytest
import yaml

import config
from auth import user_store
from security import crypto
from storage import db, projects


def test_key_file_is_created_outside_the_repository():
    crypto.encrypt_text("x")
    assert config.ENCRYPTION_KEY_FILE.exists()
    assert config.PROJECT_ROOT not in config.ENCRYPTION_KEY_FILE.parents
    from pathlib import Path
    default = Path.home() / ".finreq_agents" / "secret.key"
    assert config.PROJECT_ROOT not in default.parents


def test_roundtrip_prefix_and_plaintext_passthrough():
    token = crypto.encrypt_text("secret value")
    assert token.startswith("enc:v1:") and "secret value" not in token
    assert crypto.decrypt_text(token) == "secret value"
    assert crypto.decrypt_text("old plaintext") == "old plaintext"          # older data still readable
    assert crypto.encrypt_text(token) == token                               # never double-encrypted
    assert crypto.decrypt_bytes(crypto.encrypt_bytes(b"\x00\x01")) == b"\x00\x01"


def test_wrong_key_gives_a_clear_error(tmp_path, monkeypatch):
    token = crypto.encrypt_text("x")
    monkeypatch.setattr(config, "ENCRYPTION_KEY_FILE", tmp_path / "other.key")
    crypto.reset_cache()
    with pytest.raises(ValueError, match="wrong or missing key"):
        crypto.decrypt_text(token)


def test_mfa_secret_is_encrypted_in_users_yaml():
    user_store.register_user("ana", "Ana", "ana@example.com", "secret123", user_store.SECURITY_QUESTIONS[0], "x y")
    user_store.set_mfa_secret("ana", "JBSWY3DPEHPK3PXP")
    stored = yaml.safe_load(config.USERS_FILE.read_text(encoding="utf-8"))["credentials"]["usernames"]["ana"]
    assert stored["mfa_secret"].startswith("enc:v1:") and "JBSWY3DPEHPK3PXP" not in stored["mfa_secret"]
    assert user_store.get_mfa_secret("ana") == "JBSWY3DPEHPK3PXP"


def test_database_rows_are_encrypted(mock_llm):
    from artefacts.bundle import generate
    from interview import engine, store
    from pipeline import run_pipeline
    session = engine.start_session("operations", "Payments", "Ravi Secretname", "ana")
    store.save(session)
    result = run_pipeline("Loans", options={"num_functional": 1, "num_non_functional": 1, "review_mode": "auto"})
    projects.store_artefacts(result.run_id, generate(result), "ana")
    raw = sqlite3.connect(config.APP_DB)
    for table, column in [("transcripts", "content_json"), ("approvals", "after_json"),
                          ("requirement_versions", "content_json")]:
        values = [row[0] for row in raw.execute(f"SELECT {column} FROM {table}")]
        assert values and all(v.startswith("enc:v1:") for v in values), table
    assert all(bytes(c).startswith(b"enc:v1:") for (c,) in raw.execute("SELECT content FROM artefacts"))
    assert "Secretname" not in config.APP_DB.read_bytes().decode("latin-1")
    # ...and everything still reads back normally.
    assert store.load(session["id"])["stakeholder_name"] == "Ravi Secretname"
    assert projects.stored_artefacts(result.run_id)["srs.md"].startswith(b"# Software Requirements Specification")


def test_checkpoints_are_encrypted(mock_llm):
    from pipeline import load_result, reset_checkpointer, run_pipeline
    result = run_pipeline("Loans with a SECRETSCENARIO marker",
                          options={"num_functional": 1, "num_non_functional": 1, "review_mode": "interactive"})
    reset_checkpointer()
    assert b"SECRETSCENARIO" not in config.CHECKPOINT_DB.read_bytes()
    assert load_result(result.run_id).review_stage == "requirements_review"     # still resumable


def test_encrypt_existing_plaintext_rows():
    config.ENCRYPT_AT_REST, before = False, config.ENCRYPT_AT_REST
    try:
        projects.save_transcript({"id": "old", "created_by": "ana", "created_at": "2026-01-01", "status": "ended"})
    finally:
        config.ENCRYPT_AT_REST = before
    assert not db.query("SELECT content_json FROM transcripts")[0]["content_json"].startswith("enc:v1:")
    assert crypto.encrypt_existing()["transcripts"] == 1
    assert db.query("SELECT content_json FROM transcripts")[0]["content_json"].startswith("enc:v1:")
    assert projects.load_transcript("old")["status"] == "ended"


def test_key_creation_is_safe_under_concurrency():
    """Regression: checkpoint saves from several threads once read a half-written key."""
    import threading
    errors, tokens = [], []

    def work():
        try:
            tokens.append(crypto.encrypt_text("x"))
        except Exception as error:          # noqa: BLE001
            errors.append(error)
    threads = [threading.Thread(target=work) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(tokens) == 16
    crypto.reset_cache()
    assert all(crypto.decrypt_text(t) == "x" for t in tokens)       # one key for all
    assert not list(config.ENCRYPTION_KEY_FILE.parent.glob("*.tmp"))
