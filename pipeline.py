"""
pipeline.py - Runs the agent graph (LangGraph) and packages the results.

    typed description and/or uploaded document
            |
            v
    [prepare_context: direct text or RAG] -> [Requirements Agent] -> [SDLC Agent] -> results

Both the Streamlit UI (app.py) and the command line script (run_demo.py)
call run_pipeline(), so the logic lives in exactly one place. The graph
itself is defined in orchestration/builder.py.
"""

import time
from dataclasses import dataclass, field

from pydantic import BaseModel

import audit_log
import config
from agents.registry import AGENT_PIPELINE
from orchestration.builder import build_graph


@dataclass
class AgentResult:
    """What one agent produced."""
    key: str
    display_name: str
    raw_output: str                  # exactly what the model wrote
    parsed: BaseModel | None         # validated structured data (None if parsing failed)
    parse_error: str | None = None   # why parsing failed, if it did


@dataclass
class PipelineResult:
    """Everything produced by one run of the pipeline."""
    run_id: str
    model_name: str
    agent_results: list[AgentResult] = field(default_factory=list)
    elapsed_seconds: int = 0         # how long the whole run took
    context_info: dict = field(default_factory=dict)

    def get(self, key: str) -> AgentResult | None:
        """Look up one agent's result by its key, e.g. result.get("sdlc_agent")."""
        return next((r for r in self.agent_results if r.key == key), None)


def run_pipeline(
    scenario: str,
    source_text: str = "",
    source_name: str = "",
    model_name: str = config.MODEL_NAME,
    on_step_finished=None,
    user: str | None = None,
) -> PipelineResult:
    """Run the whole graph and return every agent's result.

    scenario:         the finance functionality to analyse
    source_text:      full text of the user's document ("" for typed input only)
    source_name:      the document's file name
    on_step_finished: optional function(node_name, elapsed_seconds, update)
                      called after every graph step - the UI uses it to show
                      live progress during a long run.
    user:             who started the run (recorded in the audit log)
    """
    start_time = time.monotonic()
    run_id = audit_log.new_run_id()
    audit_log.log_event(run_id, "pipeline_started", model=model_name, user=user,
                        scenario=scenario, source_name=source_name,
                        source_chars=len(source_text))

    graph = build_graph()
    initial_state = {
        "run_id": run_id,
        "model_name": model_name,
        "scenario": scenario,
        "source_text": source_text,
        "source_name": source_name,
        "agent_outputs": {},
    }
    # The thread_id identifies this run's saved state in the checkpointer.
    run_config = {"configurable": {"thread_id": run_id}}

    try:
        # stream() runs the graph and yields after each node finishes,
        # as {node name: the changes that node made to the state}.
        for step in graph.stream(initial_state, run_config, stream_mode="updates"):
            for node_name, update in step.items():
                if on_step_finished is not None:
                    on_step_finished(node_name, round(time.monotonic() - start_time), update)
    except Exception as error:
        audit_log.log_event(run_id, "pipeline_failed", error=str(error))
        raise

    final_state = graph.get_state(run_config).values

    # Turn the state into result objects (re-creating the Pydantic models).
    result = PipelineResult(run_id=run_id, model_name=model_name,
                            context_info=final_state.get("context_info", {}))
    for definition in AGENT_PIPELINE:
        output = final_state["agent_outputs"][definition.key]
        parsed = definition.output_schema.model_validate(output["parsed"]) if output["parsed"] else None
        result.agent_results.append(AgentResult(definition.key, definition.display_name,
                                                output["raw"], parsed, output["error"]))
    result.elapsed_seconds = round(time.monotonic() - start_time)

    audit_log.log_event(
        run_id,
        "pipeline_finished",
        elapsed_seconds=result.elapsed_seconds,
        parsed_successfully={r.key: r.parsed is not None for r in result.agent_results},
    )
    return result
