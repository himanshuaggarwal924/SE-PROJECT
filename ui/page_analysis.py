"""
ui/page_analysis.py - The main page: input -> run the agents -> results.
"""

import streamlit as st

import config
import pipeline
from ui.input_panel import render_input_panel, render_run_options
from ui.results import render_results
from ui.review_panel import render_baseline_panel, render_review
from ui.run_panel import execute_resume, execute_run
from ui.sidebar import render_sidebar


def render_analysis_page() -> None:
    st.caption("Describe a finance feature or upload a document. A Requirements Agent writes "
               "the requirements, then an SDLC Agent recommends how to build it. "
               "Runs 100% locally with Ollama + LangGraph.")

    # "running" is True while the agents work. It locks every input, because in
    # Streamlit any click restarts the script - and a restarted script would
    # NOT stop the agents, it would start a second run on top of them.
    running = st.session_state.get("running", False)
    model_name, ollama_ready = render_sidebar(running)

    with st.container(border=True):
        st.subheader("1 · What should the agents analyse?")
        request = render_input_panel(running)
        options = render_run_options(running)
        if request is not None:
            request.options = options
        if st.button("🚀 Run agents", type="primary", width="stretch",
                     disabled=running or not ollama_ready or request is None):
            st.session_state["running"] = True
            st.session_state["run_request"] = request
            st.session_state.pop("error", None)
            st.rerun()  # reload with every input locked, then start (below)

    _awaiting_runs(running)
    render_saved_run_loader(running)

    # Run or resume (on the reload after clicking a button).
    if running:
        resume = st.session_state.pop("resume_request", None)
        if resume:
            execute_resume(resume["run_id"], resume["decisions"])
        else:
            execute_run(st.session_state["run_request"], model_name,
                        st.session_state.get("username"))

    if st.session_state.get("error"):
        st.error(st.session_state["error"])

    # Results (kept in session_state so they survive other clicks).
    result = st.session_state.get("result")
    if result:
        if result.status == "awaiting_review":
            render_review(result)
            # (a toggle, not an expander: the results contain expanders themselves)
            if st.toggle("Show the results so far", key=f"so_far_{result.run_id}"):
                render_results(result)
        else:
            with st.container(border=True):
                render_results(result)
            if result.review_mode in ("interactive", "auto"):
                with st.container(border=True):
                    render_baseline_panel(result)


def render_saved_run_loader(running: bool) -> None:
    """Open a run saved as a file (e.g. demo/final_run) - no model call, nothing re-run."""
    files = pipeline.saved_runs()
    if not files:
        return
    with st.expander("📂 Load a saved run (no model needed)"):
        labels = {str(f.relative_to(config.PROJECT_ROOT)): f for f in files}
        chosen = st.selectbox("Saved run", list(labels), key="saved_run_choice")
        if st.button("Load", disabled=running, key="load_saved_run"):
            try:
                st.session_state["result"] = pipeline.load_saved_result(labels[chosen])
                st.session_state.pop("error", None)
                st.rerun()
            except (OSError, ValueError) as error:
                st.error(f"Could not load {chosen}: {error}")


def _awaiting_runs(running: bool) -> None:
    """Runs of this user paused for review - can be reopened even after a restart."""
    current = st.session_state.get("result")
    waiting = [r for r in pipeline.runs_for(st.session_state.get("username"), "awaiting_review")
               if not current or r["run_id"] != current.run_id]
    if not waiting:
        return
    with st.expander(f"✋ {len(waiting)} run(s) waiting for your review"):
        for run in waiting[:10]:
            left, right = st.columns([4, 1])
            left.markdown(f"**{run['run_id']}** – {run['scenario'][:80]} "
                          f"({run['stage'].replace('_', ' ')}, {run['updated_at'][:16].replace('T', ' ')})")
            if right.button("Open", key=f"open_{run['run_id']}", disabled=running):
                loaded = pipeline.load_result(run["run_id"])
                if loaded is None:
                    st.error("That run's saved state is no longer available.")
                else:
                    st.session_state["result"] = loaded
                    st.rerun()
