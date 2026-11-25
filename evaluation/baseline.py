"""
evaluation/baseline.py - The "single prompt, no RAG" baseline system.

Same model, one plain call (prompts/baseline_single_prompt.yaml): the first
EVAL_BASELINE_MAX_CHARS characters of the document, no retrieval, no
knowledge base, no batching, no citations, no deterministic checks.
"""

import time

import config
import llm_service
from agents.prompt_builder import build_messages
from agents.registry import BASELINE_AGENT
from agents.schemas import BaselineOutput, strict_json_schema
from agents.sdlc_scoring import load_rules
from evaluation.gold import Gold
from evaluation.metrics import SystemOutput
from output_parser import parse_agent_output
from security.injection import wrap_data


def run_baseline(gold: Gold, count: int, model_name: str = config.MODEL_NAME) -> SystemOutput:
    models = list(load_rules()["models"])
    schema = strict_json_schema(BaselineOutput)
    schema["properties"]["requirements"] = {**schema["properties"]["requirements"],
                                            "minItems": count, "maxItems": count}
    schema["properties"]["sdlc_model"] = {"type": "string", "enum": models}
    variables = {"scenario": gold.scenario,
                 "document": wrap_data(gold.document_text()[:config.EVAL_BASELINE_MAX_CHARS], "document"),
                 "count": str(count), "models": ", ".join(models)}
    system_prompt, user_prompt = build_messages(BASELINE_AGENT, variables, {})
    start = time.monotonic()
    response = llm_service.chat(system_prompt, user_prompt, model_name, json_schema=schema)
    parsed, _ = parse_agent_output(response.text, BaselineOutput)
    seconds = round(time.monotonic() - start, 1)
    requirements = [{"statement": r.statement, "categories": r.categories, "sources": [], "flags": [],
                     "acceptance_criteria": []} for r in (parsed.requirements if parsed else [])]
    statements = " ".join(r["statement"] for r in requirements)
    return SystemOutput(system="baseline", requirements=requirements,
                        sdlc_ranking=[parsed.sdlc_model] if parsed and parsed.sdlc_model else [],
                        controls_text=statements, has_citations=False, has_quality_checks=False,
                        stage_seconds={"single_prompt": seconds})
