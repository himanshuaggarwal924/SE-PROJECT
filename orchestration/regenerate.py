"""
orchestration/regenerate.py - "Regenerate" one item during human review.

Re-runs the model for ONE requirement or ONE compliance mapping, with the
reviewer's optional comment, while the run stays paused. The result is not
applied directly: the review screen shows it, and it is submitted as an
"edit" (action "regenerate") so the reviewer still decides.
"""

import audit_log
import config
import llm_service
from agents import compliance_agent
from agents.prompt_builder import build_messages
from agents.registry import REVISION_STEP, get_agent
from agents.requirements_agent import adjust_schema, check_requirement
from agents.schemas import (ComplianceBatch, Requirement, RequirementsBatch, RequirementsOutput,
                            strict_json_schema)
from context_loader import chunks_visible_to
from output_parser import parse_agent_output
from security.injection import wrap_data


def regenerate_requirement(state: dict, requirement_id: str, comment: str = "",
                           model_name: str | None = None) -> dict | None:
    """A new version of one requirement (as a dict), or None if the model's
    answer could not be used."""
    output = RequirementsOutput.model_validate(state["agent_outputs"]["requirements_agent"]["parsed"])
    old = next(r for r in output.requirements if r.id == requirement_id)
    issue = comment.strip() or "Rewrite it to be clearer, more specific and testable."
    variables = {
        "scenario": state["scenario"],
        "reference_context": wrap_data(state.get("reference_context", ""), "source document excerpts"),
        "kb_context": wrap_data(state.get("kb_context", ""), "knowledge-base excerpts"),
        "category_list": ", ".join(config.REQUIREMENT_CATEGORIES),
        "requirements_to_revise": f"{old.id}: {old.statement}\n  ISSUE (reviewer): {issue}",
        "batch_instruction": f"Rewrite exactly this 1 requirement, keeping its id: {old.id}.",
    }
    system_prompt, user_prompt = build_messages(REVISION_STEP, variables, {})
    response = llm_service.chat(system_prompt, user_prompt, model_name or state.get("model_name"),
                                json_schema=adjust_schema(strict_json_schema(RequirementsBatch), {"ids": [old.id]}))
    parsed, error = parse_agent_output(response.text, RequirementsBatch)
    audit_log.log_event(state["run_id"], "agent_call", agent="Requirements Agent (regenerate)",
                        spec={"id": old.id, "comment": comment}, seconds=response.seconds,
                        input={"user_prompt": user_prompt}, output=response.text, parse_error=error)
    if parsed is None or not parsed.requirements:
        return None
    draft = parsed.requirements[0]
    new = Requirement(**{**old.model_dump(), **draft.model_dump(), "id": old.id, "kind": old.kind,
                         "model_confidence": draft.confidence})
    checked = check_requirement(new, chunks_visible_to(state.get("chunk_map") or {}, "requirements"),
                                state["scenario"])
    return checked.model_dump()


def regenerate_mapping(state: dict, requirement_id: str, comment: str = "",
                       model_name: str | None = None) -> dict | None:
    """A new compliance mapping for one requirement (as a dict), or None."""
    definition = get_agent("compliance_agent")
    spec = {"ids": [requirement_id]}
    variables = {"scenario": state["scenario"],
                 "kb_context_full": wrap_data(state.get("kb_context_full", ""), "knowledge-base excerpts"),
                 **compliance_agent.call_variables(spec, state, [])}
    if comment.strip():
        variables["batch_requirements"] += f"\n  Reviewer comment: {comment.strip()}"
    system_prompt, user_prompt = build_messages(definition, variables, {})
    schema = compliance_agent.adjust_schema(strict_json_schema(ComplianceBatch), spec)
    response = llm_service.chat(system_prompt, user_prompt, model_name or state.get("model_name"),
                                json_schema=schema)
    parsed, error = parse_agent_output(response.text, ComplianceBatch)
    audit_log.log_event(state["run_id"], "agent_call", agent="Compliance & Security Agent (regenerate)",
                        spec={"id": requirement_id, "comment": comment}, seconds=response.seconds,
                        input={"user_prompt": user_prompt}, output=response.text, parse_error=error)
    if parsed is None or not parsed.mappings:
        return None
    requirements = {r["id"]: r for r in state["agent_outputs"]["requirements_agent"]["parsed"]["requirements"]}
    mapping = compliance_agent.check_mapping(parsed.mappings[0], requirements.get(requirement_id, {}),
                                             chunks_visible_to(state.get("chunk_map") or {}, "compliance"))
    return mapping.model_dump()
