"""
orchestration/state.py - The shared STATE that flows through the LangGraph.

Think of the state as a form that is passed from node to node. Each node
reads the fields it needs and returns ONLY the fields it wants to change;
LangGraph merges those changes into the state.
"""

from typing import Annotated, TypedDict


class AgentOutput(TypedDict):
    """What one agent node writes into the state."""
    raw: str                  # exactly what the model wrote
    parsed: dict | None       # validated JSON (None if it couldn't be parsed)
    error: str | None         # why parsing failed, if it did
    elapsed_seconds: float    # how long the agent took


def merge_dicts(old: dict, new: dict) -> dict:
    """Reducer for agent_outputs: add new agents' outputs instead of
    overwriting the whole dict. (This also lets several agents run in
    parallel branches in future phases without losing each other's output.)"""
    return {**(old or {}), **(new or {})}


class PipelineState(TypedDict, total=False):
    # --- set once at the start of a run ---
    run_id: str
    model_name: str
    scenario: str                  # the finance functionality to analyse (typed or derived)
    source_text: str               # full text of the user's document ("" if none)
    source_name: str               # its file name, for citations and the log

    # --- written by the prepare_context node ---
    reference_context: str         # source material given to the Requirements Agent
    context_info: dict             # how that context was prepared (for the UI/log)

    # --- written by the agent nodes: {agent key: AgentOutput} ---
    agent_outputs: Annotated[dict[str, AgentOutput], merge_dicts]

    # Future phases can add fields here, e.g. clarification questions,
    # validation results, or an approval decision from a human reviewer.
