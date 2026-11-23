"""
ui/run_panel.py - Runs the pipeline with live, step-by-step progress.
"""

import threading
from datetime import datetime

import streamlit as st

from agents.registry import AGENT_PIPELINE
from orchestration.builder import PREPARE_CONTEXT
from pipeline import run_pipeline
from ui.input_panel import RunRequest

# Human-friendly names for every step of the graph, in order.
STEP_LABELS = {PREPARE_CONTEXT: "Preparing source material",
               **{d.key: d.display_name for d in AGENT_PIPELINE}}
STEP_ORDER = list(STEP_LABELS)


@st.cache_resource
def get_run_lock() -> threading.Lock:
    """One lock shared by ALL users and browser tabs, so only one run uses
    Ollama at a time (Ollama answers one request at a time; two runs would
    each take twice as long)."""
    return threading.Lock()


def _describe_context(info: dict) -> str:
    method = info.get("method")
    if method == "none":
        return "no document - using your description"
    if method == "direct":
        return f"whole document used ({info.get('document_chars', 0):,} characters)"
    reused = " (index reused)" if info.get("reused_existing_index") else ""
    return (f"retrieved {info.get('chunks_used')} most relevant of "
            f"{info.get('chunks_in_document')} chunks{reused}")


def execute_run(request: RunRequest, model_name: str, username: str) -> None:
    """Run the agents, showing each step as it finishes. Stores the result
    (or an error) in st.session_state, then reloads the page."""
    lock = get_run_lock()
    if not lock.acquire(blocking=False):
        st.session_state["error"] = ("Another run is already in progress (maybe another user "
                                     "or browser tab). Please wait for it to finish.")
        st.session_state["running"] = False
        st.rerun()

    try:
        started = datetime.now().strftime("%H:%M")
        with st.status(f"Agents are working (started {started}). On a CPU-only laptop this "
                       "takes several minutes - please don't refresh the page.",
                       expanded=True) as status:
            st.write(f"⏳ {STEP_LABELS[STEP_ORDER[0]]}...")

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

            st.session_state["result"] = run_pipeline(
                request.scenario, request.source_text, request.source_name,
                model_name, on_step_finished=on_step_finished, user=username,
            )
            status.update(label="Done!", state="complete")
    except Exception as error:
        st.session_state["error"] = f"The run failed: {error}"
    finally:
        lock.release()
        st.session_state["running"] = False
    st.rerun()  # redraw the page with the inputs unlocked and the results shown
