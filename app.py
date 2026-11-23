"""
app.py - Streamlit web app (entry point).

Start it with:   streamlit run app.py
Then open the address it prints (usually http://localhost:8501).

This file only arranges the page. The pieces live in:
    auth/  - login, sign-up, password reset
    ui/    - sidebar, input panel, run progress, results
    pipeline.py + orchestration/ - the LangGraph agent pipeline
"""

import streamlit as st

from auth.auth_ui import require_login, show_account_box
from ui.input_panel import render_input_panel
from ui.results import render_results
from ui.run_panel import execute_run
from ui.sidebar import render_sidebar

st.set_page_config(page_title="FinReq Agents", page_icon="🏦", layout="wide")

st.title("🏦 Finance Requirements Agents")
st.caption("Describe a finance feature or upload a document. A Requirements Agent writes "
           "the requirements, then an SDLC Agent recommends how to build it. "
           "Runs 100% locally with Ollama + LangGraph.")

# 1. Nobody gets past this line without logging in.
authenticator = require_login()

# 2. "running" is True while the agents work. It locks every input, because in
#    Streamlit any click restarts the script - and a restarted script would
#    NOT stop the agents, it would start a second run on top of them.
running = st.session_state.get("running", False)

show_account_box(authenticator)
model_name, ollama_ready = render_sidebar(running)

# 3. Input.
with st.container(border=True):
    st.subheader("1 · What should the agents analyse?")
    request = render_input_panel(running)
    if st.button("🚀 Run agents", type="primary", width="stretch",
                 disabled=running or not ollama_ready or request is None):
        st.session_state["running"] = True
        st.session_state["run_request"] = request
        st.session_state.pop("error", None)
        st.rerun()  # reload with every input locked, then start (below)

# 4. Run (on the reload after clicking the button).
if running:
    execute_run(st.session_state["run_request"], model_name,
                st.session_state.get("username"))

if st.session_state.get("error"):
    st.error(st.session_state["error"])

# 5. Results (kept in session_state so they survive other clicks).
if st.session_state.get("result"):
    with st.container(border=True):
        render_results(st.session_state["result"])
