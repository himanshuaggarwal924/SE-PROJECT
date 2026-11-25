"""
security/crypto.py - Encryption at rest (Fernet: AES-128-CBC + HMAC-SHA256).

The key lives in a file OUTSIDE the repository: config.ENCRYPTION_KEY_FILE
(default ~/.finreq_agents/secret.key, override with FINREQ_KEY_FILE). It is
created on first use. **Back it up: data encrypted with a lost key cannot be
recovered.**

Encrypted (when ENCRYPT_AT_REST is on):
  * 2FA (TOTP) secrets in auth/users.yaml
  * transcripts, approvals (before/after), baselines, change requests,
    requirement history and stored artefacts in data/app.sqlite
  * LangGraph run states in data/checkpoints.sqlite (EncryptedSerde)
Not encrypted: the audit log (must stay verifiable; it holds masked text only)
and saved demo runs.

Older plaintext values stay readable (values without the "enc:v1:" prefix are
returned as they are); `python -m security.crypto encrypt-existing` encrypts
them in place.
"""

import json
import os
import sys
import threading

from cryptography.fernet import Fernet, InvalidToken

import config

PREFIX = "enc:v1:"
BYTES_PREFIX = PREFIX.encode()
_cache: dict[str, Fernet] = {}
_lock = threading.Lock()


def _create_key_file(path) -> None:
    """Create the key atomically: written to a temp file and renamed into
    place only if no key exists yet, so a reader never sees a half-written
    file and a key created by another thread/process is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temp.write_bytes(Fernet.generate_key())
    try:
        os.chmod(temp, 0o600)              # owner-only where the OS supports it
    except OSError:
        pass
    try:
        os.link(temp, path)                # fails if the key already exists
    except FileExistsError:
        pass
    except OSError:                        # no hard links: exclusive create instead
        try:
            with open(path, "xb") as f:
                f.write(temp.read_bytes())
        except FileExistsError:
            pass
    finally:
        temp.unlink(missing_ok=True)


def _fernet() -> Fernet:
    path = config.ENCRYPTION_KEY_FILE
    key = str(path)
    with _lock:                            # checkpoints are saved from several threads
        if key not in _cache:
            if not path.exists():
                _create_key_file(path)
            _cache[key] = Fernet(path.read_bytes().strip())
        return _cache[key]


def reset_cache() -> None:
    _cache.clear()


def enabled() -> bool:
    return config.ENCRYPT_AT_REST


def encrypt_text(value: str | None) -> str | None:
    if value is None or not enabled() or value.startswith(PREFIX):
        return value
    return PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(value: str | None) -> str | None:
    if isinstance(value, str) and value.startswith(PREFIX):
        try:
            return _fernet().decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
        except InvalidToken as error:
            raise ValueError("Encrypted data could not be decrypted - wrong or missing key file "
                             f"({config.ENCRYPTION_KEY_FILE}).") from error
    return value


def encrypt_bytes(value: bytes) -> bytes:
    if not enabled() or value.startswith(BYTES_PREFIX):
        return value
    return BYTES_PREFIX + _fernet().encrypt(value)


def decrypt_bytes(value: bytes) -> bytes:
    if isinstance(value, (bytes, memoryview)) and bytes(value).startswith(BYTES_PREFIX):
        return _fernet().decrypt(bytes(value)[len(BYTES_PREFIX):])
    return bytes(value)


def seal_json(value) -> str:
    """JSON text, encrypted."""
    return encrypt_text(json.dumps(value, ensure_ascii=False, default=str))


def open_json(text):
    return json.loads(decrypt_text(text)) if text is not None else None


class EncryptedSerde:
    """LangGraph checkpoint serializer that encrypts every saved state."""

    def __init__(self):
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        self.inner = JsonPlusSerializer()

    def dumps_typed(self, obj):
        kind, data = self.inner.dumps_typed(obj)
        if not enabled():
            return kind, data
        return f"fernet:{kind}", _fernet().encrypt(data)

    def loads_typed(self, data):
        kind, payload = data
        if kind.startswith("fernet:"):
            return self.inner.loads_typed((kind[len("fernet:"):], _fernet().decrypt(payload)))
        return self.inner.loads_typed(data)


# ------------------------------------------------------------- migration --
TEXT_COLUMNS = [("transcripts", "id", ["content_json"]), ("approvals", "id", ["before_json", "after_json"]),
                ("baselines", "id", ["content_json"]),
                ("change_requests", "id", ["before_json", "after_json"]),
                ("requirement_versions", "id", ["content_json"])]


def encrypt_existing() -> dict:
    """Encrypt plaintext values that were stored before encryption was on."""
    from auth import user_store
    from storage import db
    counts = {}
    for table, key, columns in TEXT_COLUMNS:
        for row in db.query(f"SELECT {key}, {', '.join(columns)} FROM {table}"):
            changes = {c: encrypt_text(row[c]) for c in columns
                       if isinstance(row[c], str) and not row[c].startswith(PREFIX)}
            if changes:
                db.execute(f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in changes)} WHERE {key} = ?",
                           (*changes.values(), row[key]))
                counts[table] = counts.get(table, 0) + 1
    for row in db.query("SELECT id, content FROM artefacts"):
        if not bytes(row["content"]).startswith(BYTES_PREFIX):
            db.execute("UPDATE artefacts SET content = ? WHERE id = ?", (encrypt_bytes(bytes(row["content"])), row["id"]))
            counts["artefacts"] = counts.get("artefacts", 0) + 1
    for user in user_store.list_users():
        secret = user_store.get_mfa_secret(user["username"])
        if secret:
            user_store.set_mfa_secret(user["username"], secret)      # re-saved encrypted
            counts["mfa_secrets"] = counts.get("mfa_secrets", 0) + 1
    return counts


if __name__ == "__main__":
    if sys.argv[1:] == ["encrypt-existing"]:
        print(json.dumps(encrypt_existing(), indent=2))
    elif sys.argv[1:] == ["status"]:
        print(f"Encryption at rest: {'on' if enabled() else 'off'}; key file: {config.ENCRYPTION_KEY_FILE} "
              f"({'exists' if config.ENCRYPTION_KEY_FILE.exists() else 'will be created on first use'})")
    else:
        print("Usage: python -m security.crypto status | encrypt-existing")
        sys.exit(2)
