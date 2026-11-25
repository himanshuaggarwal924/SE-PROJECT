"""
llm_service.py - The ONLY place that talks to the Ollama server.

Every agent calls chat(). Keeping all LLM calls here means that switching
model, server or settings later only touches this one file.

We use Ollama's own REST API (http://localhost:11434/api/chat) with the
`requests` library - nothing is sent anywhere except your own machine.
"""

import time
from dataclasses import dataclass, field

import requests

import config


@dataclass
class LLMResponse:
    text: str                 # what the model wrote
    prompt_tokens: int        # how many tokens the prompt used
    output_tokens: int        # how many tokens the model generated
    seconds: float            # how long the call took
    masked: dict = field(default_factory=dict)   # sensitive values masked by the guard, per type


def chat(system_prompt: str, user_prompt: str, model_name: str = config.MODEL_NAME,
         json_schema: dict | None = None) -> LLMResponse:
    """Send one system + user message to the model and return its answer.

    json_schema: if given (and USE_JSON_SCHEMA_FORMAT is on), Ollama forces the
                 answer to be JSON matching this schema.

    Security guard (Phase 9): sensitive values still in the prompts (PAN,
    Aadhaar, card, account, IFSC, phone, email, names) are masked here, right
    before the call, whatever code built the prompt.
    """
    masked = {}
    if config.MASK_SENSITIVE_DATA:
        from security.masking import Masker
        masker = Masker()
        system_prompt, user_prompt = masker.mask(system_prompt), masker.mask(user_prompt)
        masked = masker.summary
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": config.TEMPERATURE,
            "num_ctx": config.NUM_CTX,
            "num_predict": config.MAX_OUTPUT_TOKENS,
        },
    }
    if json_schema is not None and config.USE_JSON_SCHEMA_FORMAT:
        payload["format"] = json_schema

    start = time.monotonic()
    response = requests.post(f"{config.OLLAMA_BASE_URL}/api/chat", json=payload,
                             timeout=config.LLM_TIMEOUT_SECONDS)
    if response.status_code != 200:
        raise RuntimeError(f"Ollama returned HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()

    return LLMResponse(
        text=data["message"]["content"],
        prompt_tokens=data.get("prompt_eval_count", 0),
        output_tokens=data.get("eval_count", 0),
        seconds=round(time.monotonic() - start, 1),
        masked=masked,
    )


def list_installed_models() -> list[str]:
    """Names of the models pulled into Ollama. Raises if Ollama isn't running."""
    response = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=3)
    response.raise_for_status()
    return [m["name"] for m in response.json().get("models", [])]
