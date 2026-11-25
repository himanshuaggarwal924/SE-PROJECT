"""
ui/run_panel.py - Runs the pipeline with live, step-by-step progress.
"""

import threading
from datetime import datetime

import streamlit as st

from agents.registry import AGENT_PIPELINE
from orchestration.builder import PREPARE_CONTEXT
from orchestration.revision import REVISE_REQUIREMENTS
from pipeline import resume_pipeline, run_pipeline
from ui.input_panel import RunRequest

# Human-friendly names for every step of the graph, in order.
STEP_LABELS = {PREPARE_CONTEXT: "Preparing source material",
               **{d.key: d.display_name for d in AGENT_PIPELINE}}
STEP_ORDER = list(STEP_LABELS)
STEP_LABELS[REVISE_REQUIREMENTS] = "Revising requirements (quality round)"
STEP_LABELS["review_requirements"] = "Applying your review"
STEP_LABELS["review_sdlc"] = "Applying your SDLC decision"


@st.cache_resource
def get_run_lock() -> threading.Lock:
    """One lock shared by ALL users and browser tabs, so only one run uses
    Ollama at a time (Ollama answers one request at a time; two runs would
    each take twice as long)."""
    return threading.Lock()


def _describe_context(info: dict) -> str:
    method = info.get("method")
    if method == "none":
        text = "no document - using your description"
    elif method == "direct":
        text = f"whole document used ({info.get('document_chars', 0):,} characters)"
    else:
        reused = " (index reused)" if info.get("reused_existing_index") else ""
        text = (f"retrieved {info.get('chunks_used')} most relevant of "
                f"{info.get('chunks_in_document')} chunks{reused}")
    if "kb_chunks_used" in info:
        text += f"; {info['kb_chunks_used']} knowledge-base excerpts"
    if info.get("kb_error"):
        text += " (knowledge base unavailable)"
    return text


def _with_progress(work, label: str) -> None:
    """Run work(on_step_finished) under the one-run lock with live progress.
    Stores the result (or an error) in st.session_state, then reloads the page."""
    lock = get_run_lock()
    if not lock.acquire(blocking=False):
        st.session_state["error"] = ("Another run is already in progress (maybe another user "
                                     "or browser tab). Please wait for it to finish.")
        st.session_state["running"] = False
        st.rerun()

    try:
        started = datetime.now().strftime("%H:%M")
        with st.status(f"{label} (started {started}). On a CPU-only laptop this "
                       "takes several minutes - please don't refresh the page.",
                       expanded=True) as status:

            def on_step_finished(node_name, elapsed_seconds, update):
                minutes, seconds = divmod(elapsed_seconds, 60)
                detail = ""
                if "context_info" in update:
                    detail = f" - {_describe_context(update['context_info'])}"
                st.write(f"✅ {STEP_LABELS.get(node_name, node_name)} done "
                         f"({minutes} min {seconds} s){detail}")
                position = STEP_ORDER.index(node_name) if node_name in STEP_ORDER else -1
                if 0 <= position < len(STEP_ORDER) - 1:
                    st.write(f"⏳ {STEP_LABELS[STEP_ORDER[position + 1]]} is working...")

            result = work(on_step_finished)
            st.session_state["result"] = result
            if result.status == "awaiting_review":
                status.update(label="Paused for your review", state="complete")
            else:
                status.update(label="Done!", state="complete")
    except Exception as error:
        st.session_state["error"] = f"The run failed: {error}"
    finally:
        lock.release()
        st.session_state["running"] = False
    st.rerun()  # redraw the page with the inputs unlocked and the results shown


def execute_run(request: RunRequest, model_name: str, username: str) -> None:
    """Start a new run (it may pause for review)."""
    st.write(f"⏳ {STEP_LABELS[STEP_ORDER[0]]}...")
    _with_progress(lambda progress: run_pipeline(
        request.scenario, request.source_text, request.source_name, model_name,
        on_step_finished=progress, user=username, options=request.options, segments=request.segments),
        "Agents are working")


def execute_resume(run_id: str, decisions: dict) -> None:
    """Continue a paused run with the reviewer's decisions."""
    _with_progress(lambda progress: resume_pipeline(run_id, decisions, on_step_finished=progress),
                   "Continuing after your review")
