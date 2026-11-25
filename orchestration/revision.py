"""
orchestration/revision.py - The optional quality-driven revision round.

When QUALITY_REVISION_ENABLED is on and the Quality Agent found High-severity
issues, the graph goes  quality_agent -> revise_requirements -> quality_agent
(at most QUALITY_MAX_REVISIONS times). This node asks the Requirements Agent
(prompts/requirements_revision.yaml) to rewrite only the affected
requirements, re-runs the deterministic checks on them, and keeps the old
version in each requirement's revision_history.
"""

import time

import audit_log
import config
import llm_service
from agents.prompt_builder import build_messages
from agents.registry import REVISION_STEP
from agents.requirements_agent import adjust_schema, build_output, check_requirement, render_for_next
from agents.schemas import Requirement, RequirementsBatch, RequirementsOutput, strict_json_schema
from context_loader import chunks_visible_to
from orchestration.state import PipelineState
from output_parser import parse_agent_output
from security.injection import wrap_data

REVISE_REQUIREMENTS = "revise_requirements"


def _describe(requirement: Requirement, issues: list[dict]) -> str:
    lines = [f"{requirement.id}: {requirement.statement}"]
    lines += [f"  ISSUE ({i['severity']}, {i['type']}): {i['explanation']}" for i in issues]
    return "\n".join(lines)


def revise_requirements_node(state: PipelineState) -> dict:
    start = time.monotonic()
    run_id = state["run_id"]
    round_number = state.get("revision_count", 0) + 1
    outputs = state["agent_outputs"]
    requirements = RequirementsOutput.model_validate(outputs["requirements_agent"]["parsed"])
    quality = outputs["quality_agent"]["parsed"]
    high_ids = set(quality["summary"].get("high_severity_ids", []))
    issues_by_id = {r["requirement_id"]: [i for i in r["issues"] if i["severity"] == "High"]
                    for r in quality["reviews"]}
    targets = [r for r in requirements.requirements if r.id in high_ids]

    chunk_map = chunks_visible_to(state.get("chunk_map") or {}, "requirements")
    schema = strict_json_schema(RequirementsBatch)
    revised: dict[str, Requirement] = {}
    raws = []
    size = max(1, config.REQUIREMENTS_BATCH_SIZE)
    for start_index in range(0, len(targets), size):
        batch = targets[start_index:start_index + size]
        ids = [r.id for r in batch]
        variables = {
            "scenario": state["scenario"],
            "reference_context": wrap_data(state.get("reference_context", ""), "source document excerpts"),
            "kb_context": wrap_data(state.get("kb_context", ""), "knowledge-base excerpts"),
            "category_list": ", ".join(config.REQUIREMENT_CATEGORIES),
            "requirements_to_revise": "\n".join(_describe(r, issues_by_id.get(r.id, [])) for r in batch),
            "batch_instruction": f"Rewrite exactly these {len(ids)} requirements, keeping their ids: "
                                 f"{', '.join(ids)}.",
        }
        system_prompt, user_prompt = build_messages(REVISION_STEP, variables, {})
        response = llm_service.chat(system_prompt, user_prompt, state["model_name"],
                                    json_schema=adjust_schema(schema, {"ids": ids}))
        parsed, error = parse_agent_output(response.text, RequirementsBatch)
        raws.append(response.text)
        audit_log.log_event(run_id, "agent_call", agent=REVISION_STEP.display_name,
                            call=start_index // size + 1, spec={"ids": ids, "round": round_number},
                            seconds=response.seconds, prompt_tokens=response.prompt_tokens,
                            output_tokens=response.output_tokens,
                            input={"system_prompt": system_prompt, "user_prompt": user_prompt},
                            output=response.text, parse_error=error)
        if parsed is None:
            continue    # keep the original requirements of a failed batch
        for old, draft in zip(batch, parsed.requirements):
            new = Requirement(**{**draft.model_dump(), "id": old.id, "kind": old.kind,
                                 "model_confidence": draft.confidence,
                                 "revision_history": old.revision_history + [{
                                     "round": round_number, "statement": old.statement,
                                     "issues": issues_by_id.get(old.id, [])}]})
            revised[old.id] = check_requirement(new, chunk_map, state["scenario"])

    updated = [revised.get(r.id, r) for r in requirements.requirements]
    summary = requirements.validation_summary
    output = build_output(requirements.scenario_summary, updated, summary.get("requested", len(updated)),
                          summary.get("failed_batches", 0))
    output.validation_summary["revised_ids"] = sorted(revised)

    audit_log.log_event(run_id, "requirements_revised", round=round_number,
                        elapsed_seconds=round(time.monotonic() - start, 1),
                        changes=[{"id": rid, "before": next(r.statement for r in targets if r.id == rid),
                                  "after": revised[rid].statement} for rid in sorted(revised)])

    previous = outputs["requirements_agent"]
    return {
        "revision_count": round_number,
        "agent_outputs": {"requirements_agent": {
            **previous,
            "raw": previous["raw"] + "".join(f"\n\n----- revision round {round_number} -----\n\n{r}"
                                             for r in raws),
            "parsed": output.model_dump(),
            "rendered": render_for_next(output),
        }},
    }
