"""
pipeline.py - Runs the agent graph (LangGraph) and packages the results.

    typed description, document or interview transcripts
            |
            v
    [prepare_context] -> Requirements -> Quality -> Compliance
        -> (human review) -> SDLC -> (human review) -> Workflow -> results

Both the Streamlit UI (app.py) and the command line script (run_demo.py)
call run_pipeline(), so the logic lives in exactly one place. The graph
itself is defined in orchestration/builder.py.

Review modes (options["review_mode"]):
  "none"        run straight through; items stay "pending" (default)
  "auto"        run straight through; everything auto-approved (run_demo --auto-approve)
  "interactive" pause at each review step: run_pipeline() returns a result
                with status "awaiting_review"; resume_pipeline() continues it.
                The paused state lives in data/checkpoints.sqlite, so a run can
                be resumed even after the app restarts.
"""

import sqlite3
import threading
import time
from dataclasses import dataclass, field

from langgraph.types import Command
from pydantic import BaseModel

import audit_log
import config
from agents.registry import AGENT_PIPELINE
from orchestration.builder import build_graph
from security.masking import Masker
from security.versions import run_versions
from storage import db


@dataclass
class AgentResult:
    """What one agent produced."""
    key: str
    display_name: str
    raw_output: str                  # exactly what the model wrote
    parsed: BaseModel | None         # validated structured data (None if parsing failed)
    parse_error: str | None = None   # why parsing failed, if it did
    status: str = "ok"               # ok | partial | failed | skipped | not_run


@dataclass
class PipelineResult:
    """Everything produced by one run of the pipeline (so far, if paused)."""
    run_id: str
    model_name: str
    agent_results: list[AgentResult] = field(default_factory=list)
    elapsed_seconds: int = 0         # how long the whole run took
    context_info: dict = field(default_factory=dict)
    chunk_map: dict = field(default_factory=dict)   # citation ID -> excerpt
    scenario: str = ""
    status: str = "done"             # done | awaiting_review
    review_stage: str = ""           # requirements_review | sdlc_review (when awaiting)
    review_payload: dict = field(default_factory=dict)
    review_mode: str = "none"
    pii_masked: dict = field(default_factory=dict)   # sensitive values masked, per type
    versions: dict = field(default_factory=dict)     # model / prompt / KB versions of the run

    def get(self, key: str) -> AgentResult | None:
        """Look up one agent's result by its key, e.g. result.get("sdlc_agent")."""
        return next((r for r in self.agent_results if r.key == key), None)


# ------------------------------------------------------------ checkpointer --
_checkpointer = None
_checkpointer_lock = threading.Lock()


def persistent_checkpointer():
    """The SQLite checkpointer (data/checkpoints.sqlite), shared by all runs."""
    global _checkpointer
    from langgraph.checkpoint.sqlite import SqliteSaver
    with _checkpointer_lock:
        path = str(config.CHECKPOINT_DB)
        if _checkpointer is None or getattr(_checkpointer, "_path", None) != path:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            from security.crypto import EncryptedSerde
            _checkpointer = SqliteSaver(sqlite3.connect(path, check_same_thread=False), serde=EncryptedSerde())
            _checkpointer._path = path
        return _checkpointer


def reset_checkpointer() -> None:
    """Forget the shared checkpointer (tests, and the retention purge)."""
    global _checkpointer
    with _checkpointer_lock:
        if _checkpointer is not None:
            _checkpointer.conn.close()
        _checkpointer = None


def _graph(review_mode: str):
    if review_mode == "interactive":
        return build_graph(review_mode, checkpointer=persistent_checkpointer())
    return build_graph(review_mode)


# ------------------------------------------------------------------ running --
def run_pipeline(
    scenario: str,
    source_text: str = "",
    source_name: str = "",
    model_name: str = config.MODEL_NAME,
    on_step_finished=None,
    user: str | None = None,
    options: dict | None = None,
    segments: list[dict] | None = None,
) -> PipelineResult:
    """Run the graph (until the end, or until the first review pause).

    scenario:         the finance functionality to analyse
    source_text:      full text of the user's document ("" for typed input only)
    source_name:      the document's file name
    on_step_finished: optional function(node_name, elapsed_seconds, update)
                      called after every graph step - the UI uses it to show
                      live progress during a long run.
    user:             who started the run (recorded in the audit log)
    options:          run options, e.g. {"num_functional": 5, "review_mode": "interactive"}
    segments:         interview answers (interview/engine.transcript_segments),
                      used instead of source_text, one citable excerpt per answer
    """
    start_time = time.monotonic()
    run_id = audit_log.new_run_id()
    options = dict(options or {})
    review_mode = options.setdefault("review_mode", "none")
    segments = segments or []

    # Security (Phase 9): mask sensitive values BEFORE anything is logged,
    # embedded or sent to the model. The reversible mapping stays in this
    # function's memory only; just the counts per type are recorded.
    pii_masked = {}
    if config.MASK_SENSITIVE_DATA:
        masker = Masker()
        scenario = masker.mask(scenario)
        source_text = masker.mask(source_text)
        segments = [{**s, "text": masker.mask(s["text"]),
                     "stakeholder_masked": masker.mask_name(s.get("stakeholder", ""))} for s in segments]
        pii_masked = masker.summary
    if segments and not source_text:
        source_text = "\n\n".join(s["text"] for s in segments)
    versions = run_versions(model_name)
    audit_log.log_event(run_id, "pipeline_started", model=model_name, user=user,
                        scenario=scenario, source_name=source_name,
                        source_chars=len(source_text), options=options,
                        interviews=sorted({s["interview_id"] for s in segments}),
                        pii_masked=pii_masked, versions=versions)
    db.execute("INSERT INTO runs (run_id, user, created_at, updated_at, status, scenario, source_name, "
               "model, review_mode, project) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)",
               (run_id, user, db.now(), db.now(), scenario, source_name, model_name, review_mode,
                options.get("project") or "default"))

    initial_state = {
        "run_id": run_id,
        "model_name": model_name,
        "scenario": scenario,
        "source_text": source_text,
        "source_name": source_name,
        "options": options,
        "source_segments": segments,
        "pii_masked": pii_masked,
        "versions": versions,
        "agent_outputs": {},
    }
    return _stream(run_id, review_mode, initial_state, on_step_finished, start_time)


def resume_pipeline(run_id: str, decisions: dict, on_step_finished=None) -> PipelineResult:
    """Continue a paused interactive run with the reviewers' decisions."""
    audit_log.log_event(run_id, "pipeline_resumed", reviewer=decisions.get("reviewer"))
    db.execute("UPDATE runs SET status = 'running', stage = '', updated_at = ? WHERE run_id = ?",
               (db.now(), run_id))
    return _stream(run_id, "interactive", Command(resume=decisions), on_step_finished, time.monotonic())


def _stream(run_id: str, review_mode: str, graph_input, on_step_finished, start_time) -> PipelineResult:
    graph = _graph(review_mode)
    # The thread_id identifies this run's saved state in the checkpointer.
    run_config = {"configurable": {"thread_id": run_id}}
    try:
        # stream() yields after each node, as {node name: the changes it made}.
        for step in graph.stream(graph_input, run_config, stream_mode="updates"):
            for node_name, update in step.items():
                if node_name == "__interrupt__":
                    continue             # a review pause, handled below
                if on_step_finished is not None:
                    on_step_finished(node_name, round(time.monotonic() - start_time), update or {})
    except Exception as error:
        audit_log.log_event(run_id, "pipeline_failed", error=str(error))
        db.execute("UPDATE runs SET status = 'failed', updated_at = ? WHERE run_id = ?", (db.now(), run_id))
        raise

    result = _result_from_snapshot(run_id, graph.get_state(run_config), review_mode)
    result.elapsed_seconds = round(time.monotonic() - start_time)
    _record_history(result)
    if result.status == "awaiting_review":
        audit_log.log_event(run_id, "pipeline_paused", stage=result.review_stage)
        db.execute("UPDATE runs SET status = 'awaiting_review', stage = ?, updated_at = ? WHERE run_id = ?",
                   (result.review_stage, db.now(), run_id))
    else:
        audit_log.log_event(
            run_id, "pipeline_finished", elapsed_seconds=result.elapsed_seconds,
            parsed_successfully={r.key: r.parsed is not None for r in result.agent_results},
            status={r.key: r.status for r in result.agent_results})
        db.execute("UPDATE runs SET status = 'done', stage = '', updated_at = ? WHERE run_id = ?",
                   (db.now(), run_id))
    return result


def _record_history(result: PipelineResult) -> None:
    """Store every requirement version of the run (Phase 7 history / diffs)."""
    from storage import projects
    requirements = result.get("requirements_agent")
    if requirements and requirements.parsed:
        projects.record_versions(result.run_id, [r.model_dump() for r in requirements.parsed.requirements])


def _result_from_snapshot(run_id: str, snapshot, review_mode: str) -> PipelineResult:
    """Turn a saved graph state into result objects (re-creating the Pydantic models)."""
    values = snapshot.values
    result = PipelineResult(run_id=run_id, model_name=values.get("model_name", ""),
                            context_info=values.get("context_info", {}),
                            chunk_map=values.get("chunk_map", {}), scenario=values.get("scenario", ""),
                            review_mode=review_mode, pii_masked=values.get("pii_masked", {}),
                            versions=values.get("versions", {}))
    outputs = values.get("agent_outputs", {})
    for definition in AGENT_PIPELINE:
        output = outputs.get(definition.key)
        if output is None:
            result.agent_results.append(AgentResult(definition.key, definition.display_name, "", None,
                                                    None, "not_run"))
            continue
        parsed = definition.output_schema.model_validate(output["parsed"]) if output["parsed"] else None
        result.agent_results.append(AgentResult(definition.key, definition.display_name,
                                                output["raw"], parsed, output["error"],
                                                output.get("status", "ok")))
    interrupts = [i for task in snapshot.tasks for i in getattr(task, "interrupts", ())]
    if snapshot.next and interrupts:
        result.status = "awaiting_review"
        result.review_payload = interrupts[0].value or {}
        result.review_stage = result.review_payload.get("stage", "")
    return result


def load_result(run_id: str) -> PipelineResult | None:
    """Rebuild an interactive run's result from the checkpointer (e.g. to
    resume a review after the app restarted). None if the run is unknown."""
    graph = _graph("interactive")
    snapshot = graph.get_state({"configurable": {"thread_id": run_id}})
    if not snapshot.values:
        return None
    return _result_from_snapshot(run_id, snapshot, "interactive")


def apply_post_run_decisions(run_id: str, decisions: dict) -> PipelineResult:
    """Decide items that were still pending when an interactive run finished
    (Phase 7: reviewers with other roles decide later). Updates the saved state."""
    from orchestration.review import apply_requirement_decisions
    graph = _graph("interactive")
    run_config = {"configurable": {"thread_id": run_id}}
    snapshot = graph.get_state(run_config)
    update = apply_requirement_decisions(snapshot.values, decisions)
    if update.get("agent_outputs"):
        graph.update_state(run_config, update, as_node=AGENT_PIPELINE[-1].key)
    result = _result_from_snapshot(run_id, graph.get_state(run_config), "interactive")
    _record_history(result)
    return result


def run_state(run_id: str) -> dict:
    """The raw saved state of an interactive run (for regenerate / baselines)."""
    return _graph("interactive").get_state({"configurable": {"thread_id": run_id}}).values


def runs_for(user: str | None, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM runs WHERE user IS ?" + (" AND status = ?" if status else "")
    params = (user, status) if status else (user,)
    return db.query(sql + " ORDER BY created_at DESC", params)


# ------------------------------------------------------------- saved runs --
def result_to_dict(result: PipelineResult) -> dict:
    """A JSON-safe copy of a result (to keep a finished run as a file)."""
    from dataclasses import asdict
    data = {k: v for k, v in asdict(result).items() if k != "agent_results"}
    data["agent_results"] = [{"key": r.key, "display_name": r.display_name, "raw_output": r.raw_output,
                              "parsed": r.parsed.model_dump() if r.parsed else None,
                              "parse_error": r.parse_error, "status": r.status} for r in result.agent_results]
    data["format"] = "finreq-saved-run/1"
    return data


def result_from_dict(data: dict) -> PipelineResult:
    schemas = {d.key: d.output_schema for d in AGENT_PIPELINE}
    fields = {k: v for k, v in data.items() if k not in ("agent_results", "format")}
    result = PipelineResult(**fields)
    for r in data["agent_results"]:
        parsed = schemas[r["key"]].model_validate(r["parsed"]) if r["parsed"] and r["key"] in schemas else None
        result.agent_results.append(AgentResult(r["key"], r["display_name"], r["raw_output"], parsed,
                                                r["parse_error"], r["status"]))
    return result


def save_result(result: PipelineResult, path) -> None:
    import json
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result_to_dict(result), indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def load_saved_result(path) -> PipelineResult:
    """Load a run saved with save_result() - no model call, nothing re-run."""
    import json
    from pathlib import Path
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != "finreq-saved-run/1":
        raise ValueError(f"{path} is not a saved run.")
    return result_from_dict(data)


def saved_runs() -> list:
    """Saved-run files under config.SAVED_RUNS_DIR (e.g. demo/final_run/result.json)."""
    folder = config.SAVED_RUNS_DIR
    return sorted(folder.rglob("result.json")) if folder.exists() else []
