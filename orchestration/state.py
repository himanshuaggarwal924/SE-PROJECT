"""
orchestration/state.py - The shared STATE that flows through the LangGraph.

Think of the state as a form that is passed from node to node. Each node
reads the fields it needs and returns ONLY the fields it wants to change;
LangGraph merges those changes into the state.
"""

from typing import Annotated, TypedDict


class AgentOutput(TypedDict):
    """What one agent node writes into the state."""
    raw: str                  # exactly what the model wrote (all calls, joined)
    parsed: dict | None       # final validated output (None if nothing usable)
    error: str | None         # why parsing failed, if it did
    status: str               # ok | partial | failed | skipped
    rendered: str             # the text later agents receive
    elapsed_seconds: float    # how long the agent took
    calls: int                # how many model calls it made


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
    options: dict                  # run options, e.g. {"num_functional": 5, "num_non_functional": 4}
    source_segments: list          # interview answers, one citable excerpt each (or [])
    pii_masked: dict               # sensitive values masked before any model call, per type
    versions: dict                 # model / prompt / KB / rules versions of this run

    # --- written by the prepare_context node ---
    reference_context: str         # document excerpts [C1]... given to the Requirements Agent
    kb_context: str                # knowledge-base excerpts [KB-1]... (Requirements Agent)
    kb_context_full: str           # more KB excerpts (Compliance Agent)
    revision_count: int            # how many quality-driven revision rounds have run
    context_info: dict             # how that context was prepared (for the UI/log)
    # Citation ID -> excerpt: {"C1": {"text", "document", "position", "similarity"}}
    chunk_map: dict

    # --- written by the agent nodes: {agent key: AgentOutput} ---
    agent_outputs: Annotated[dict[str, AgentOutput], merge_dicts]

    # Future phases can add fields here, e.g. clarification questions,
    # validation results, or an approval decision from a human reviewer.
