"""
ui/sidebar.py - The sidebar: account, Ollama/model status and model switch.
"""

import streamlit as st

import config
import llm_service


def render_sidebar(running: bool) -> tuple[str, bool]:
    """Draw the sidebar. Returns (chosen model name, is Ollama ready?)."""
    with st.sidebar:
        st.header("⚙️ Model")
        try:
            installed = llm_service.list_installed_models()
        except Exception:
            st.error("Ollama is not running. Start the Ollama app (or run `ollama serve`), "
                     "then refresh this page.")
            return config.MODEL_NAME, False

        if not installed:
            st.error(f"No models installed. Run:  `ollama pull {config.MODEL_NAME}`")
            return config.MODEL_NAME, False

        # Put the default model first if it is installed.
        default = next((m for m in installed if m in (config.MODEL_NAME, f"{config.MODEL_NAME}:latest")),
                       installed[0])
        model_name = st.selectbox("Ollama model", installed, index=installed.index(default),
                                  disabled=running,
                                  help="Any model pulled with `ollama pull`. "
                                       "Bigger models are smarter but slower and need more RAM.")
        st.success("Ollama is running", icon="✅")

        with st.expander("How it works"):
            st.markdown(
                "1. **Prepare context** - a small document is used whole; a large one is "
                "split into chunks and only the most relevant parts are retrieved (RAG).\n"
                "2. **Requirements Agent** - writes functional & non-functional requirements.\n"
                "3. **SDLC Agent** - reads those requirements and recommends an SDLC model.\n\n"
                "Everything runs locally. Each run is recorded in `logs/audit_log.jsonl`."
            )
        st.divider()
    return model_name, True
