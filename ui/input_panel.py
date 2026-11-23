"""
ui/input_panel.py - Where the user says WHAT to analyse:
either a typed description, or a document (uploaded or a sample).
"""

from dataclasses import dataclass

import streamlit as st

import config
from context_loader import list_sample_documents, load_sample_documents
from document_reader import SUPPORTED_TYPES, extract_text

TYPE_MODE = "✍️ Describe it"
UPLOAD_MODE = "📄 Use a document"

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


@st.cache_data(show_spinner="Reading the document...", max_entries=5)
def _extract(file_name: str, file_bytes: bytes) -> str:
    """Extract text once per file (cached, so re-runs of the page are instant)."""
    return extract_text(file_name, file_bytes)


def render_input_panel(running: bool) -> RunRequest | None:
    """Draw the input area. Returns a RunRequest if the input is complete,
    or None if something is still missing."""
    mode = st.segmented_control("Input", [TYPE_MODE, UPLOAD_MODE], default=TYPE_MODE,
                                label_visibility="collapsed", disabled=running) or TYPE_MODE

    if mode == TYPE_MODE:
        return _typed_input(running)
    return _document_input(running)


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
