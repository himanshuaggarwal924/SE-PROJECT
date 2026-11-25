"""
ui/input_panel.py - Where the user says WHAT to analyse:
either a typed description, or a document (uploaded or a sample).
"""

from dataclasses import dataclass, field

import streamlit as st

import config
from context_loader import list_sample_documents, load_sample_documents
from document_reader import SUPPORTED_TYPES, extract_text

TYPE_MODE = "✍️ Describe it"
UPLOAD_MODE = "📄 Use a document"
TRANSCRIPT_MODE = "🗣️ Use interviews"

# Typed text longer than this is treated as source material (and may go
# through retrieval) rather than as a short description.
LONG_TYPED_TEXT = 1500

EXAMPLE_DESCRIPTION = (
    "Loan approval module for a retail bank: customers apply online for a "
    "personal loan, the system checks eligibility and credit score, and either "
    "auto-decides or routes the application to a human underwriter."
)


@dataclass
class RunRequest:
    """Everything the pipeline needs to start a run."""
    scenario: str          # what to write requirements for
    source_text: str       # document text ("" if none)
    source_name: str       # document name, e.g. "spec.pdf"
    options: dict = field(default_factory=dict)   # e.g. {"num_functional": 5}
    segments: list = field(default_factory=list)  # interview answers (TRANSCRIPT_MODE)


def render_run_options(running: bool) -> dict:
    """'Advanced' settings for one run: which optional agents run, and how
    many requirements to write."""
    from agents.registry import AGENT_PIPELINE
    with st.expander("⚙️ Advanced: agents and number of requirements"):
        st.caption("Each agent adds model calls. On a CPU-only laptop, turn off the ones you "
                   "don't need to get results sooner.")
        disabled = []
        optional_agents = [d for d in AGENT_PIPELINE if d.optional]
        for column, definition in zip(st.columns(len(optional_agents)), optional_agents):
            if not column.checkbox(definition.display_name, value=True, disabled=running,
                                   key=f"agent_on_{definition.key}"):
                disabled.append(definition.key)
        left, right = st.columns(2)
        functional = left.number_input(
            "Functional", min_value=1, max_value=config.MAX_REQUIREMENTS_PER_KIND,
            value=config.NUM_FUNCTIONAL_REQUIREMENTS, disabled=running)
        non_functional = right.number_input(
            "Non-functional", min_value=1, max_value=config.MAX_REQUIREMENTS_PER_KIND,
            value=config.NUM_NON_FUNCTIONAL_REQUIREMENTS, disabled=running)
        batches = -(-functional // config.REQUIREMENTS_BATCH_SIZE) - \
            (-non_functional // config.REQUIREMENTS_BATCH_SIZE)
        st.caption(f"Written in {batches} model calls of up to {config.REQUIREMENTS_BATCH_SIZE} "
                   "requirements each. More requirements = a longer run.")
        review = st.checkbox("✋ Pause for human review (requirements, then SDLC choice)", value=True,
                             disabled=running, key="review_on",
                             help="Recommended. Without it, items stay 'pending' and no baseline can be locked.")
    return {"num_functional": int(functional), "num_non_functional": int(non_functional),
            "disabled_agents": disabled, "review_mode": "interactive" if review else "none",
            "project": st.session_state.get("project", "default")}


@st.cache_data(show_spinner="Reading the document...", max_entries=5)
def _extract(file_name: str, file_bytes: bytes) -> str:
    """Extract text once per file (cached, so re-runs of the page are instant)."""
    return extract_text(file_name, file_bytes)


def render_input_panel(running: bool) -> RunRequest | None:
    """Draw the input area. Returns a RunRequest if the input is complete,
    or None if something is still missing."""
    st.session_state.setdefault("input_mode", TYPE_MODE)
    mode = st.segmented_control("Input", [TYPE_MODE, UPLOAD_MODE, TRANSCRIPT_MODE], key="input_mode",
                                label_visibility="collapsed", disabled=running) or TYPE_MODE

    if mode == TYPE_MODE:
        return _typed_input(running)
    if mode == TRANSCRIPT_MODE:
        return _transcript_input(running)
    return _document_input(running)


def _transcript_input(running: bool) -> RunRequest | None:
    """Interview transcripts as input: every answer becomes a citable excerpt."""
    from interview import store
    from interview.engine import transcript_segments
    sessions = {s["id"]: s for s in store.list_sessions(st.session_state.get("username"))}
    if not sessions:
        st.caption("No interview transcripts yet - run or import one on the "
                   "**Stakeholder interview** page.")
        return None
    st.session_state["selected_transcripts"] = [
        i for i in st.session_state.get("selected_transcripts", []) if i in sessions]
    chosen = st.multiselect(
        "Transcripts", list(sessions), key="selected_transcripts", disabled=running,
        format_func=lambda i: f"{i} – {sessions[i]['role_label']} "
                              f"{sessions[i].get('stakeholder_name') or ''}".strip())
    if not chosen:
        st.caption("Choose at least one transcript.")
        return None
    segments = transcript_segments([sessions[i] for i in chosen])
    st.caption(f"🗣️ {len(segments)} answers from {len(chosen)} transcript(s); requirements will "
               "cite the exact answer they come from.")
    focus = st.text_input("Focus (optional)", disabled=running, key="transcript_focus",
                          placeholder="e.g. Loan application intake and credit decision").strip()
    scenario = focus or next((sessions[i]["scenario"] for i in chosen if sessions[i].get("scenario")),
                             "The finance functionality discussed in the interviews")
    return RunRequest(scenario=scenario, source_text="", source_name="interviews: " + ", ".join(chosen),
                      segments=segments)


def _typed_input(running: bool) -> RunRequest | None:
    text = st.text_area("Describe the finance functionality you need requirements for",
                        value=EXAMPLE_DESCRIPTION, height=140, max_chars=20000,
                        disabled=running).strip()
    if not text:
        st.caption("Type a description to continue.")
        return None
    if len(text) <= LONG_TYPED_TEXT:
        return RunRequest(scenario=text, source_text="", source_name="")
    # A long pasted text is treated like a document.
    st.caption(f"Long text ({len(text):,} characters) - it will be used as source material.")
    return RunRequest(scenario="The finance functionality described in the user's text",
                      source_text=text, source_name="typed description")


def _document_input(running: bool) -> RunRequest | None:
    source = st.radio("Document source", ["Upload a file", "Use a sample document"],
                      horizontal=True, disabled=running, label_visibility="collapsed")

    if source == "Upload a file":
        uploaded = st.file_uploader("Finance document (PDF, DOCX, TXT or MD)",
                                    type=SUPPORTED_TYPES, disabled=running)
        if uploaded is None:
            st.caption("Upload a document to continue.")
            return None
        try:
            text = _extract(uploaded.name, uploaded.getvalue())
        except Exception as error:
            st.error(f"Could not read {uploaded.name}: {error}")
            return None
        name = uploaded.name
    else:
        samples = list_sample_documents()
        chosen = st.multiselect("Sample documents (demo)", samples, default=samples[:1],
                                disabled=running)
        if not chosen:
            st.caption("Choose at least one sample document.")
            return None
        text = load_sample_documents(chosen)
        name = " + ".join(chosen)

    _describe_document(text)
    focus = st.text_input("Focus (optional)", disabled=running,
                          placeholder="e.g. Instant payments with fraud screening",
                          help="Which functionality in the document should the requirements "
                               "cover? Leave empty to cover the whole document.").strip()
    scenario = focus or f"The finance functionality described in the document '{name}'"
    return RunRequest(scenario=scenario, source_text=text, source_name=name)


def _describe_document(text: str) -> None:
    """Tell the user how the document will be used (whole or via retrieval)."""
    chars = len(text)
    if chars > config.MAX_DOCUMENT_CHARS:
        note = (f"very large - only the first {config.MAX_DOCUMENT_CHARS:,} characters are "
                "indexed, then the most relevant parts are retrieved")
    elif chars > config.MAX_CONTEXT_CHARS:
        note = "large - the most relevant parts will be retrieved (RAG)"
    else:
        note = "small - it will be given to the agent in full"
    st.caption(f"📏 {chars:,} characters · {note}")
    with st.expander("Preview extracted text"):
        st.text(text[:3000] + ("\n[...]" if chars > 3000 else ""))
