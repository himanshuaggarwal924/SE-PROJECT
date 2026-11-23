"""
agents/schemas.py - The expected SHAPE of each agent's output.

These Pydantic models do two jobs:
  1. Validate the JSON the LLM returns (did it include the fields we need?).
  2. Give later phases a ready-made structure to save into a database.

Fields have defaults where reasonable, so a small model that forgets an
optional field doesn't cause the whole run to fail.
"""

import copy

from pydantic import BaseModel, Field


def strict_json_schema(schema_class: type[BaseModel]) -> dict:
    """The JSON schema sent to the model (Ollama "structured outputs").

    The Pydantic classes below are deliberately lenient (defaults for
    optional fields) so that parsing rarely fails. But if the model sees a
    field as optional it may leave it empty - so in the copy we send to the
    model, EVERY field is required and defaults are removed.
    """
    schema = copy.deepcopy(schema_class.model_json_schema())

    def make_strict(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
            node.pop("default", None)
            for value in node.values():
                make_strict(value)
        elif isinstance(node, list):
            for item in node:
                make_strict(item)

    make_strict(schema)
    return schema


# ----------------------------- Requirements Agent -----------------------------
class Requirement(BaseModel):
    id: str                       # e.g. "FR-01" or "NFR-03"
    category: str = ""            # e.g. "Security", "Credit Assessment"
    description: str              # "The system shall ..."
    priority: str = "Medium"      # High / Medium / Low
    reasoning: str = ""           # why this requirement exists


class RequirementsOutput(BaseModel):
    scenario_summary: str = ""
    functional_requirements: list[Requirement] = Field(default_factory=list)
    non_functional_requirements: list[Requirement] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


# --------------------------------- SDLC Agent ---------------------------------
class Characteristic(BaseModel):
    factor: str                   # e.g. "Regulatory criticality"
    rating: str = ""              # High / Medium / Low
    evidence: str = ""            # which requirements show this, and why


class Alternative(BaseModel):
    model: str                    # e.g. "Waterfall"
    reason_not_chosen: str = ""


class SDLCOutput(BaseModel):
    recommended_model: str
    confidence: str = ""
    characteristics: list[Characteristic] = Field(default_factory=list)
    justification: str = ""
    alternatives_considered: list[Alternative] = Field(default_factory=list)
    key_practices: list[str] = Field(default_factory=list)
