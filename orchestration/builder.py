"""
orchestration/builder.py - Wires the nodes together into a LangGraph.

Current graph (a straight chain):

    START -> prepare_context -> requirements_agent -> sdlc_agent -> END

HOW TO GROW IT in later phases (all changes happen in build_graph()):
  * New agent: add it to agents/registry.py - it becomes a node in the chain.
  * Branching: replace an add_edge() with add_conditional_edges(), e.g.
        graph.add_conditional_edges("requirements_agent", route_after_requirements,
                                    {"ok": "sdlc_agent", "unclear": "clarification_agent"})
    where route_after_requirements(state) returns "ok" or "unclear".
  * Human approval: compile with interrupt_before=["sdlc_agent"]. The run
    pauses there, the checkpointer saves the state, and it continues when
    the graph is invoked again with the same thread_id.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from agents.registry import AGENT_PIPELINE  
from orchestration.nodes import make_agent_node, prepare_context_node
from orchestration.state import PipelineState
   
PREPARE_CONTEXT = "prepare_context"


def build_graph():
    """Build and compile the pipeline graph."""
    graph = StateGraph(PipelineState)

    # 1. Nodes: one for context preparation, then one per registered agent.
    graph.add_node(PREPARE_CONTEXT, prepare_context_node)
    for definition in AGENT_PIPELINE:
        graph.add_node(definition.key, make_agent_node(definition))

    # 2. Edges: chain the nodes in order.
    order = [PREPARE_CONTEXT] + [d.key for d in AGENT_PIPELINE]
    graph.add_edge(START, order[0])
    for current_node, next_node in zip(order, order[1:]):
        graph.add_edge(current_node, next_node)
    graph.add_edge(order[-1], END)

    # 3. Compile. The checkpointer saves the state after every node, which
    #    is what makes pausing for human approval possible later.
    return graph.compile(checkpointer=InMemorySaver())
