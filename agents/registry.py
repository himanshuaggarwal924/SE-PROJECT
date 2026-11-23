"""
agents/registry.py - The list of agents in the pipeline, in the order they run.

HOW TO ADD A NEW AGENT (e.g. a "Compliance Agent" in a later phase):
  1. Create  prompts/compliance_agent.yaml  (copy an existing YAML as a template).
  2. Add a Pydantic output schema for it in  agents/schemas.py.
  3. Add one AgentDefinition to AGENT_PIPELINE below, listing whose output
     it needs in `receives_output_from`.
The LangGraph builder (orchestration/builder.py) turns every entry into a
graph node automatically, and the audit log and UI pick it up too.
"""

from dataclasses import dataclass, field

from pydantic import BaseModel

from agents.schemas import RequirementsOutput, SDLCOutput


@dataclass
class AgentDefinition:
    key: str                         # node name AND prompt file name: prompts/<key>.yaml
    display_name: str                # shown in the UI and the audit log
    output_schema: type[BaseModel]   # the JSON shape we expect back
    # Keys of earlier agents whose output is given to this agent as input.
    receives_output_from: list[str] = field(default_factory=list)


# The order of this list is the order the agents run in.
AGENT_PIPELINE: list[AgentDefinition] = [
    AgentDefinition(
        key="requirements_agent",
        display_name="Requirements Agent",
        output_schema=RequirementsOutput,
    ),
    AgentDefinition(
        key="sdlc_agent",
        display_name="SDLC Agent",
        output_schema=SDLCOutput,
        receives_output_from=["requirements_agent"],
    ),
    # Future phases add more agents here, e.g.:
    # AgentDefinition(key="compliance_agent", display_name="Compliance Agent",
    #                 output_schema=ComplianceOutput,
    #                 receives_output_from=["requirements_agent"]),
]


def get_agent(key: str) -> AgentDefinition:
    """Look up an agent definition by its key."""
    return next(d for d in AGENT_PIPELINE if d.key == key)
