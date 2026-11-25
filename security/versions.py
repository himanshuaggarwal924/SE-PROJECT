"""
security/versions.py - Fingerprints recorded with every run: the model's
name and version (digest from Ollama), a hash of every prompt YAML file, and
a hash of the knowledge base. Together they make a run reproducible/auditable.
"""

import hashlib
from functools import lru_cache

import requests

import config


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


@lru_cache(maxsize=8)
def model_version(model_name: str) -> dict:
    """{"name", "digest", "parameter_size", "quantization"} from Ollama (cached)."""
    info = {"name": model_name, "digest": "unknown"}
    try:
        tags = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=3).json().get("models", [])
        for model in tags:
            if model["name"] in (model_name, f"{model_name}:latest"):
                details = model.get("details", {})
                info.update(digest=model.get("digest", "unknown")[:12],
                            parameter_size=details.get("parameter_size", ""),
                            quantization=details.get("quantization_level", ""))
    except (requests.RequestException, ValueError):
        pass
    return info


def prompt_versions() -> dict[str, str]:
    """{prompt file (relative): hash} for every YAML under prompts/."""
    return {path.relative_to(config.PROMPTS_DIR).as_posix(): _hash(path.read_bytes())
            for path in sorted(config.PROMPTS_DIR.rglob("*.yaml"))}


def kb_version() -> str:
    """One hash over every KB item (path + content hash) and the allowlist."""
    from rag.knowledge_base import load_items
    parts = sorted(f"{i.path}:{i.content_hash}" for i in load_items())
    parts.append(",".join(config.KB_EVIDENCE_TYPES) + "|" + ",".join(config.KB_ALLOWED_SOURCES))
    return _hash("\n".join(parts).encode("utf-8"))


def rules_version() -> str:
    return _hash(config.SDLC_RULES_FILE.read_bytes())


def run_versions(model_name: str) -> dict:
    prompts = prompt_versions()
    return {"model": model_version(model_name), "prompts": prompts,
            "prompts_combined": _hash("".join(f"{k}{v}" for k, v in prompts.items()).encode()),
            "kb": kb_version(), "sdlc_rules": rules_version()}
