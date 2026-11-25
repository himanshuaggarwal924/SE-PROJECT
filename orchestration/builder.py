"""
orchestration/builder.py - Wires the nodes together into a LangGraph.

Current graph (a chain, plus one optional loop):

    START -> prepare_context -> requirements_agent -> quality_agent
          -> compliance_agent -> sdlc_agent -> END

    With review (Phase 6): ... compliance_agent -> review_requirements (pause)
          -> sdlc_agent -> review_sdlc (pause) -> workflow_agent

    With QUALITY_REVISION_ENABLED:
          quality_agent --(High-severity issues, at most once)--> revise_requirements
          revise_requirements -> quality_agent

HOW TO GROW IT in later phases (all changes happen in build_graph()):
  * New agent: add it to agents/registry.py - it becomes a node in the chain.
  * Branching: replace an add_edge() with add_conditional_edges(), e.g.
        graph.add_conditional_edges("requirements_agent", route_after_requirements,
                                    {"ok": "sdlc_agent", "unclear": "clarification_agent"})
    where route_after_requirements(state) returns "ok" or "unclear".
  * Human approval: see orchestration/review.py (interrupt() inside review nodes,
    resumed with Command(resume=decisions) on the same thread_id).
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

import config
from agents import quality_agent
from agents.registry import AGENT_PIPELINE
from orchestration.nodes import make_agent_node, prepare_context_node
from orchestration.review import (REVIEW_REQUIREMENTS, REVIEW_SDLC, review_requirements_node,
                                  review_sdlc_node)
from orchestration.revision import REVISE_REQUIREMENTS, revise_requirements_node
from orchestration.state import PipelineState

PREPARE_CONTEXT = "prepare_context"


def build_graph(review_mode: str = "none", checkpointer=None):
    """Build and compile the pipeline graph.

    review_mode: "none"        no review steps (items stay pending)
                 "interactive" pause for human review after the Compliance
                               Agent and after the SDLC Agent (interrupt())
                 "auto"        same review steps, everything auto-approved
    checkpointer: where paused/finished run states are saved (default: in memory).
    """
    graph = StateGraph(PipelineState)

    # 1. Nodes: one for context preparation, then one per registered agent.
    graph.add_node(PREPARE_CONTEXT, prepare_context_node)
    for definition in AGENT_PIPELINE:
        graph.add_node(definition.key, make_agent_node(definition))

    # 2. Edges: chain the nodes in order (with the review steps if enabled).
    order = [PREPARE_CONTEXT] + [d.key for d in AGENT_PIPELINE]
    if review_mode in ("interactive", "auto"):
        graph.add_node(REVIEW_REQUIREMENTS, review_requirements_node)
        graph.add_node(REVIEW_SDLC, review_sdlc_node)
        order.insert(order.index("sdlc_agent"), REVIEW_REQUIREMENTS)
        order.insert(order.index("sdlc_agent") + 1, REVIEW_SDLC)
    graph.add_edge(START, order[0])
    for current_node, next_node in zip(order, order[1:]):
        if current_node == "quality_agent" and config.QUALITY_REVISION_ENABLED:
            # Optional loop: High-severity issues -> one revision round -> re-review.
            graph.add_node(REVISE_REQUIREMENTS, revise_requirements_node)
            graph.add_conditional_edges("quality_agent", quality_agent.route_after,
                                        {"revise": REVISE_REQUIREMENTS, "continue": next_node})
            graph.add_edge(REVISE_REQUIREMENTS, "quality_agent")
        else:
            graph.add_edge(current_node, next_node)
    graph.add_edge(order[-1], END)

    # 3. Compile. The checkpointer saves the state after every node, which
    #    is what makes pausing for human approval possible later.
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
