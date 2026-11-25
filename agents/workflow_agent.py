"""
agents/workflow_agent.py - Generates the project-specific SDLC workflow.

  1. Start from the YAML template of the recommended model (config/sdlc_workflows/).
  2. Deterministic additions from earlier agents: the joint SDLC-approval
     gate, compliance-officer approvals for high-impact mappings, and a
     decision on the suggested security requirements.
  3. The model proposes up to 2 project-specific items per list per phase
     (activities, security, testing, compliance checkpoints) - bounded, and
     always marked as added. If that call fails, the template is still used.
"""

from agents.schemas import WorkflowCustomisation, WorkflowOutput, WorkflowPhase
from agents.sdlc_scoring import load_workflow_template

AI_FIELDS = {"extra_activities": "activities", "extra_security_activities": "security_activities",
             "extra_testing": "testing", "extra_compliance_checkpoints": "compliance_checkpoints"}


def _parsed(state, key: str) -> dict:
    return (state.get("agent_outputs", {}).get(key) or {}).get("parsed") or {}


def _template(state) -> dict | None:
    """The template of the model the reviewers chose (or the recommended one)."""
    sdlc = _parsed(state, "sdlc_agent")
    model = sdlc.get("selected_model") or sdlc.get("recommended_model")
    return load_workflow_template(model) if model else None


def skip_reason(state) -> str | None:
    if _parsed(state, "sdlc_agent").get("approval_status") == "rejected":
        return "Skipped: the reviewers rejected the SDLC selection."
    return None


def plan_calls(state) -> list[dict]:
    return [{"step": "customise"}]


def call_variables(spec: dict, state, earlier) -> dict | None:
    template = _template(state)
    if template is None:
        return None
    spec["phases"] = [p["name"] for p in template["phases"]]
    lines = []
    for phase in template["phases"]:
        lines.append(f"{phase['name']}: activities {', '.join(phase['activities'])}; "
                     f"security {', '.join(phase['security_activities']) or '-'}; "
                     f"testing {', '.join(phase['testing']) or '-'}; "
                     f"compliance {', '.join(phase['compliance_checkpoints']) or '-'}")
    return {"model": template["model"], "workflow_template": "\n".join(lines),
            "phase_list": ", ".join(spec["phases"])}


def adjust_schema(schema: dict, spec: dict) -> dict:
    names = spec.get("phases", [])
    schema = {**schema, "properties": dict(schema["properties"]), "$defs": dict(schema["$defs"])}
    schema["properties"]["phases"] = {**schema["properties"]["phases"],
                                      "minItems": len(names), "maxItems": len(names)}
    draft = dict(schema["$defs"]["PhaseCustomisationDraft"])
    draft["properties"] = {**draft["properties"], "phase": {"type": "string", "enum": names or ["-"]}}
    schema["$defs"]["PhaseCustomisationDraft"] = draft
    return schema


def _add(phase: WorkflowPhase, field: str, item: str) -> None:
    items = getattr(phase, field)
    if item.strip() and item.strip().lower() not in {i.lower() for i in items}:
        items.append(item.strip())
        phase.added.append(f"{field}: {item.strip()}")


def combine(calls, state) -> WorkflowOutput | None:
    template = _template(state)
    if template is None:
        return None
    phases = [WorkflowPhase(**{k: list(v) if isinstance(v, list) else v for k, v in p.items()})
              for p in template["phases"]]

    # Deterministic, project-specific additions from earlier agents.
    first = phases[0]
    _add(first, "approval_gates",
         "Joint approval of the SDLC choice (project manager, architect, security, compliance)")
    compliance = _parsed(state, "compliance_agent")
    officer_ids = [m["requirement_id"] for m in compliance.get("mappings", [])
                   if m.get("requires_compliance_officer_approval")]
    if officer_ids:
        _add(first, "compliance_checkpoints",
             f"Compliance-officer approval of mappings for {', '.join(officer_ids)}")
    suggested = [s["id"] for s in compliance.get("suggested_requirements", [])]
    if suggested:
        _add(first, "activities", f"Decide on suggested security requirements {', '.join(suggested)}")

    # The model's bounded additions.
    customisation: WorkflowCustomisation | None = calls[0][1] if calls else None
    by_name = {p.name: p for p in phases}
    if customisation is not None:
        for draft in customisation.phases:
            phase = by_name.get(draft.phase)
            if phase is None:
                continue
            for source, field in AI_FIELDS.items():
                for item in getattr(draft, source)[:2]:
                    _add(phase, field, item)
            phase.project_notes = draft.project_notes.strip()

    return WorkflowOutput(model=template["model"], summary=template.get("summary", ""),
                          phases=phases, customised_by_ai=customisation is not None)


def render_for_next(output: WorkflowOutput) -> str:
    return f"{output.model} workflow: " + " -> ".join(p.name for p in output.phases)
