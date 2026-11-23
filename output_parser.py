"""
output_parser.py - Turns an agent's raw text answer into validated data.

We ask each agent for JSON, but small local models sometimes wrap it in
```json fences, add a sentence before it, or miss a comma. This module
cleans that up before validating against the agent's Pydantic schema.
"""

import json

import json_repair
from pydantic import BaseModel, ValidationError


def extract_json_text(raw: str) -> str:
    """Cut out the part of the text between the first '{' and the last '}'."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return raw  # no braces found - let the parser report the problem
    return raw[start : end + 1]


def parse_agent_output(raw: str, schema: type[BaseModel]) -> tuple[BaseModel | None, str | None]:
    """Parse and validate an agent's answer.

    Returns (parsed_object, None) on success, or (None, error_message) if the
    answer can't be understood. The raw text is always kept elsewhere, so a
    parse failure never loses the agent's work.
    """
    json_text = extract_json_text(raw)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        # Try to fix common mistakes (missing commas, trailing commas, etc.).
        data = json_repair.loads(json_text)

    if not isinstance(data, dict):
        return None, "The agent's answer did not contain a JSON object."

    try:
        return schema.model_validate(data), None
    except ValidationError as error:
        return None, f"The JSON did not match the expected structure:\n{error}"
