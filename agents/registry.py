"""
agents/registry.py - The list of agents in the pipeline, in the order they run.

HOW TO ADD A NEW AGENT (e.g. a "Compliance Agent" in a later phase):
  1. Create  prompts/compliance_agent.yaml  (copy an existing YAML as a template).
  2. Add a Pydantic output schema for it in  agents/schemas.py.
  3. Add one AgentDefinition to AGENT_PIPELINE below, listing whose output
     it needs in `receives_output_from`.
The LangGraph builder (orchestration/builder.py) turns every entry into a
graph node automatically, and the audit log and UI pick it up too.

OPTIONAL HOOKS (for agents that need more than one plain model call):
  llm_schema       what ONE model call returns, if different from the final
                   output_schema (e.g. a batch of requirements)
  plan_calls       state -> list of call specs; one model call per spec
                   (default: a single call)
  call_variables   (spec, state, earlier [(spec, parsed)]) -> extra prompt variables,
                   or None to skip the call (e.g. its input failed). It may add
                   keys to `spec` for adjust_schema to use.
  schema_for       spec -> the Pydantic schema of that call (when calls differ)
  adjust_schema    (json_schema, spec) -> json_schema for that call (e.g. force
                   exactly N items, since Ollama's grammar can enforce it)
  A spec may also contain "prompt" (use prompts/<prompt>.yaml for that call)
  and "include_previous": False (don't append earlier agents' outputs).
  combine          ([(spec, parsed or None)], state) -> final output_schema object
                   (or None if nothing usable); this is where deterministic
                   checks run (default: the single call's parsed answer)
  render_for_next  final object -> the text later agents receive
                   (default: its JSON)
"""

from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel

from agents import compliance_agent, quality_agent, requirements_agent, sdlc_agent, workflow_agent
from agents.schemas import (BaselineOutput, ComplianceBatch, ComplianceOutput, InterviewTurnDraft,
                            QualityBatch, QualityOutput,
                            RequirementsBatch, RequirementsOutput, SDLCOutput,
                            WorkflowCustomisation, WorkflowOutput)


@dataclass
class AgentDefinition:
    key: str                         # node name AND prompt file name: prompts/<key>.yaml
    display_name: str                # shown in the UI and the audit log
    output_schema: type[BaseModel]   # the final, stored output
    # Keys of earlier agents whose output is given to this agent as input.
    receives_output_from: list[str] = field(default_factory=list)
    # Of those, the ones this agent can do without (turned off or failed).
    # A missing REQUIRED input makes the agent skip itself.
    optional_inputs: list[str] = field(default_factory=list)
    # Can the user turn this agent off for a run (to save time)?
    optional: bool = False
    # state -> reason to skip this agent (e.g. reviewers rejected its input), or None.
    skip_reason: Callable | None = None
    # Agent-level permissions (Phase 9): the state fields this agent may READ,
    # besides ALWAYS_READABLE and the outputs of `receives_output_from`. It may
    # only WRITE its own entry in agent_outputs (enforced in orchestration/nodes.py).
    reads: list[str] = field(default_factory=list)
    llm_schema: type[BaseModel] | None = None
    plan_calls: Callable | None = None
    call_variables: Callable | None = None
    schema_for: Callable | None = None
    adjust_schema: Callable | None = None
    combine: Callable | None = None
    render_for_next: Callable | None = None

    @property
    def call_schema(self) -> type[BaseModel]:
        """The schema of one model call's answer."""
        return self.llm_schema or self.output_schema


# Every agent may read these (no document content, no personal data).
ALWAYS_READABLE = ["run_id", "model_name", "scenario", "options"]


# The order of this list is the order the agents run in.
AGENT_PIPELINE: list[AgentDefinition] = [
    AgentDefinition(
        key="requirements_agent",
        reads=["reference_context", "kb_context", "chunk_map"],
        display_name="Requirements Agent",
        output_schema=RequirementsOutput,
        llm_schema=RequirementsBatch,
        plan_calls=requirements_agent.plan_calls,
        schema_for=requirements_agent.schema_for,
        call_variables=requirements_agent.call_variables,
        adjust_schema=requirements_agent.adjust_schema,
        combine=requirements_agent.combine,
        render_for_next=requirements_agent.render_for_next,
    ),
    AgentDefinition(
        key="quality_agent",
        reads=[],
        display_name="Quality & Clarification Agent",
        output_schema=QualityOutput,
        optional=True,
        llm_schema=QualityBatch,
        receives_output_from=["requirements_agent"],
        plan_calls=quality_agent.plan_calls,
        call_variables=quality_agent.call_variables,
        adjust_schema=quality_agent.adjust_schema,
        combine=quality_agent.combine,
        render_for_next=quality_agent.render_for_next,
    ),
    AgentDefinition(
        key="compliance_agent",
        reads=["kb_context_full", "chunk_map"],
        display_name="Compliance & Security Agent",
        output_schema=ComplianceOutput,
        optional=True,
        llm_schema=ComplianceBatch,
        receives_output_from=["requirements_agent"],
        plan_calls=compliance_agent.plan_calls,
        call_variables=compliance_agent.call_variables,
        adjust_schema=compliance_agent.adjust_schema,
        combine=compliance_agent.combine,
        render_for_next=compliance_agent.render_for_next,
    ),
    AgentDefinition(
        key="sdlc_agent",
        reads=["chunk_map"],
        display_name="SDLC Agent",
        output_schema=SDLCOutput,
        receives_output_from=["requirements_agent", "quality_agent", "compliance_agent"],
        optional_inputs=["quality_agent", "compliance_agent"],
        plan_calls=sdlc_agent.plan_calls,
        schema_for=sdlc_agent.schema_for,
        call_variables=sdlc_agent.call_variables,
        adjust_schema=sdlc_agent.adjust_schema,
        combine=sdlc_agent.combine,
        render_for_next=sdlc_agent.render_for_next,
    ),
    AgentDefinition(
        key="workflow_agent",
        reads=[],
        display_name="Workflow Agent",
        output_schema=WorkflowOutput,
        optional=True,
        llm_schema=WorkflowCustomisation,
        receives_output_from=["requirements_agent", "compliance_agent", "sdlc_agent"],
        optional_inputs=["compliance_agent"],
        skip_reason=workflow_agent.skip_reason,
        plan_calls=workflow_agent.plan_calls,
        call_variables=workflow_agent.call_variables,
        adjust_schema=workflow_agent.adjust_schema,
        combine=workflow_agent.combine,
        render_for_next=workflow_agent.render_for_next,
    ),
]

# Interactive agent (not a pipeline node): the adaptive stakeholder interviewer,
# called once per answer by interview/engine.py. Its prompt: prompts/interview_agent.yaml.
INTERVIEW_AGENT = AgentDefinition(
    key="interview_agent",
    display_name="Stakeholder Interview Agent",
    output_schema=InterviewTurnDraft,
)

# Evaluation only (not a pipeline node): the "single prompt, no RAG" baseline
# that the full system is compared against (evaluation/baseline.py).
BASELINE_AGENT = AgentDefinition(
    key="baseline_single_prompt",
    display_name="Single-prompt baseline (evaluation)",
    output_schema=BaselineOutput,
)

# Not a pipeline node of its own: the prompt the Requirements Agent uses in
# the optional quality-driven revision round (orchestration/revision.py).
REVISION_STEP = AgentDefinition(
    key="requirements_revision",
    display_name="Requirements Agent (revision)",
    output_schema=RequirementsBatch,
)


def get_agent(key: str) -> AgentDefinition:
    """Look up an agent definition by its key."""
    return next(d for d in AGENT_PIPELINE if d.key == key)
