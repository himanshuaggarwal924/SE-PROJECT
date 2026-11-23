"""
orchestration/nodes.py - The functions that run at each step of the graph.

A LangGraph node is just a function:  state in  ->  partial state update out.
"""

import time

import audit_log
import llm_service
from agents.prompt_builder import build_messages
from agents.registry import AgentDefinition, get_agent
from agents.schemas import strict_json_schema
from context_loader import build_reference_context
from orchestration.state import PipelineState
from output_parser import parse_agent_output


def prepare_context_node(state: PipelineState) -> dict:
    """Prepare the source material the Requirements Agent will read: the
    whole document if it is small, or the most relevant chunks (RAG) if not."""
    start = time.monotonic()
    context = build_reference_context(state.get("source_text", ""),
                                      state.get("source_name", ""), state["scenario"])
    info = {"method": context.method, "context_chars": len(context.text),
            "seconds": round(time.monotonic() - start, 1), **context.details}
    audit_log.log_event(state["run_id"], "context_prepared", **info)
    return {"reference_context": context.text, "context_info": info}


def make_agent_node(definition: AgentDefinition):
    """Create the node function for one agent.

    Every agent node works the same way:
      1. build its prompt from its YAML file, the state, and the outputs of
         the agents listed in `receives_output_from`
      2. call the model through llm_service
      3. parse + validate the JSON answer
      4. write an audit record and return the output into the state
    """
    def agent_node(state: PipelineState) -> dict:
        start = time.monotonic()

        variables = {
            "scenario": state["scenario"],
            "reference_context": state.get("reference_context", ""),
        }
        outputs_so_far = state.get("agent_outputs", {})
        previous_outputs = {
            get_agent(key).display_name: outputs_so_far[key]["raw"]
            for key in definition.receives_output_from
        }
        system_prompt, user_prompt = build_messages(definition, variables, previous_outputs)

        response = llm_service.chat(
            system_prompt, user_prompt, state["model_name"],
            json_schema=strict_json_schema(definition.output_schema),
        )
        parsed, error = parse_agent_output(response.text, definition.output_schema)
        elapsed = round(time.monotonic() - start, 1)

        audit_log.log_event(
            state["run_id"],
            "agent_completed",
            agent=definition.display_name,
            elapsed_seconds=elapsed,
            prompt_tokens=response.prompt_tokens,
            output_tokens=response.output_tokens,
            input={
                "received_output_from": definition.receives_output_from,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            },
            output=response.text,
            parse_error=error,
        )

        output = {
            "raw": response.text,
            "parsed": parsed.model_dump() if parsed else None,
            "error": error,
            "elapsed_seconds": elapsed,
        }
        return {"agent_outputs": {definition.key: output}}

    agent_node.__name__ = f"{definition.key}_node"
    return agent_node
