"""
orchestration/nodes.py - The functions that run at each step of the graph.

A LangGraph node is just a function:  state in  ->  partial state update out.
"""

import copy
import json
import time

import audit_log
import llm_service
from agents.prompt_builder import build_messages
from agents.registry import ALWAYS_READABLE, AgentDefinition, get_agent
from agents.schemas import strict_json_schema
from context_loader import build_reference_context
from orchestration.state import PipelineState
from output_parser import parse_agent_output
from security.injection import wrap_data


def prepare_context_node(state: PipelineState) -> dict:
    """Prepare the source material the Requirements Agent will read: the
    whole document if it is small, or the most relevant chunks (RAG) if not.
    Every excerpt is labelled [C1], [C2]... and kept in the chunk map so
    citations can be checked later."""
    start = time.monotonic()
    context = build_reference_context(state.get("source_text", ""),
                                      state.get("source_name", ""), state["scenario"],
                                      segments=state.get("source_segments"))
    info = {"method": context.method, "context_chars": len(context.text),
            "seconds": round(time.monotonic() - start, 1), **context.details}
    audit_log.log_event(state["run_id"], "context_prepared", **info)
    return {"reference_context": context.text, "kb_context": context.kb_text,
            "kb_context_full": context.kb_text_full,
            "context_info": info, "chunk_map": context.chunk_map}


def _render(definition: AgentDefinition, parsed) -> str:
    """The text later agents receive from this agent."""
    if definition.render_for_next is not None:
        return definition.render_for_next(parsed)
    return json.dumps(parsed.model_dump(), ensure_ascii=False)


NOT_AVAILABLE = "(not available to this agent)"


def agent_view(definition: AgentDefinition, state: dict) -> dict:
    """A deep copy of only the state an agent may read (Phase 9 permissions)."""
    allowed = set(ALWAYS_READABLE) | set(definition.reads)
    view = {key: copy.deepcopy(value) for key, value in state.items() if key in allowed}
    outputs = state.get("agent_outputs", {})
    view["agent_outputs"] = {key: copy.deepcopy(outputs[key]) for key in definition.receives_output_from
                             if key in outputs}
    return view


def check_writes(definition: AgentDefinition, update: dict) -> dict:
    """An agent may only write its own entry in agent_outputs."""
    if set(update) != {"agent_outputs"} or set(update["agent_outputs"]) != {definition.key}:
        raise PermissionError(f"{definition.display_name} tried to write outside its own output.")
    return update


def _data(view: dict, key: str, label: str) -> str:
    if key not in view:
        return NOT_AVAILABLE
    return wrap_data(view.get(key) or "", label)


def make_agent_node(definition: AgentDefinition):
    """Create the node function for one agent.

    Every agent node works the same way:
      1. skip (without calling the model) if an agent it depends on failed
      2. for each planned call: build the prompt from the YAML file, the
         state and the earlier agents' outputs, call the model through
         llm_service, parse the JSON (a failed parse never stops the run)
      3. combine the calls into the final output (deterministic checks)
      4. write audit records and return the output into the state
    """
    def agent_node(full_state: PipelineState) -> dict:
        start = time.monotonic()
        run_id = full_state["run_id"]
        # Least privilege: the agent and its hooks only see a COPY of the
        # fields it declared (plus the outputs of the agents it depends on).
        state = agent_view(definition, full_state)
        outputs_so_far = state.get("agent_outputs", {})

        disabled = (state.get("options") or {}).get("disabled_agents", [])
        failed_inputs = [key for key in definition.receives_output_from
                         if key not in definition.optional_inputs
                         and not outputs_so_far.get(key, {}).get("parsed")]
        reason = None
        if definition.optional and definition.key in disabled:
            reason = "Turned off for this run."
        elif failed_inputs:
            reason = f"Skipped: no usable output from {', '.join(failed_inputs)}."
        elif definition.skip_reason is not None:
            reason = definition.skip_reason(state)
        if reason:
            audit_log.log_event(run_id, "agent_completed", agent=definition.display_name,
                                status="skipped", parse_error=reason, elapsed_seconds=0)
            return {"agent_outputs": {definition.key: {
                "raw": "", "parsed": None, "error": reason, "status": "skipped",
                "rendered": "", "elapsed_seconds": 0, "calls": 0}}}

        # Document / KB text is untrusted: wrapped in data delimiters.
        base_variables = {
            "scenario": state["scenario"],
            "reference_context": _data(state, "reference_context", "source document excerpts"),
            "kb_context": _data(state, "kb_context", "knowledge-base excerpts"),
            "kb_context_full": _data(state, "kb_context_full", "knowledge-base excerpts"),
        }
        previous_outputs = {
            get_agent(key).display_name:
                outputs_so_far.get(key, {}).get("rendered") or "(not available for this run)"
            for key in definition.receives_output_from
        }
        specs = definition.plan_calls(state) if definition.plan_calls else [{}]

        calls, raws, errors = [], [], []
        prompt_tokens = output_tokens = 0
        for number, spec in enumerate(specs, start=1):
            variables = dict(base_variables)
            if definition.call_variables is not None:
                extra = definition.call_variables(spec, state, calls)
                if extra is None:            # the call's input is missing: skip it
                    calls.append((spec, None))
                    continue
                variables.update(extra)
            schema_class = definition.schema_for(spec) if definition.schema_for else definition.call_schema
            schema = strict_json_schema(schema_class)
            if definition.adjust_schema is not None:
                schema = definition.adjust_schema(schema, spec)
            previous = previous_outputs if spec.get("include_previous", True) else {}
            system_prompt, user_prompt = build_messages(definition, variables, previous,
                                                        prompt_key=spec.get("prompt"))

            response = llm_service.chat(system_prompt, user_prompt, state["model_name"],
                                        json_schema=schema)
            parsed, error = parse_agent_output(response.text, schema_class)
            calls.append((spec, parsed))
            raws.append(response.text)
            if error:
                errors.append(f"Call {number}: {error}" if len(specs) > 1 else error)
            prompt_tokens += response.prompt_tokens
            output_tokens += response.output_tokens

            audit_log.log_event(
                run_id, "agent_call", agent=definition.display_name,
                call=number, of=len(specs), spec=spec, seconds=response.seconds,
                prompt_tokens=response.prompt_tokens, output_tokens=response.output_tokens,
                input={"received_output_from": definition.receives_output_from,
                       "system_prompt": system_prompt, "user_prompt": user_prompt},
                output=response.text, parse_error=error,
            )

        if definition.combine is not None:
            final = definition.combine(calls, state)
        else:
            final = calls[0][1]

        if final is None:
            status = "failed"
        elif errors:
            status = "partial"
        else:
            status = "ok"
        elapsed = round(time.monotonic() - start, 1)
        summary = getattr(final, "validation_summary", None) if final is not None else None

        audit_log.log_event(
            run_id, "agent_completed", agent=definition.display_name, status=status,
            calls=len(specs), elapsed_seconds=elapsed,
            prompt_tokens=prompt_tokens, output_tokens=output_tokens,
            parse_error="\n".join(errors) or None, validation_summary=summary,
        )

        separator = "\n\n----- next call -----\n\n"
        return check_writes(definition, {"agent_outputs": {definition.key: {
            "raw": separator.join(raws),
            "parsed": final.model_dump() if final is not None else None,
            "error": "\n".join(errors) or None,
            "status": status,
            "rendered": _render(definition, final) if final is not None else "",
            "elapsed_seconds": elapsed,
            "calls": len(specs),
        }}})

    agent_node.__name__ = f"{definition.key}_node"
    return agent_node
