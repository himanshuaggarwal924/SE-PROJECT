"""
ui/page_interview.py - "Stakeholder interview": an adaptive chat interview,
transcript management, imports, and "Send to analysis".
"""

import pandas as pd
import streamlit as st

from document_reader import SUPPORTED_TYPES, extract_text
from interview import engine, store
from interview.importer import import_transcript
from interview.templates import role_templates, topics
from ui.navigation import get_page
from ui.run_panel import get_run_lock
from ui.sidebar import render_sidebar

STATUS_ICONS = {"pending": "⬜", "covered": "✅", "partial": "🟨", "skipped": "⏭️"}


def _username() -> str | None:
    return st.session_state.get("username")


def _save(session: dict) -> None:
    store.save(session, st.session_state.get("project", "default"))
    st.session_state["interview"] = session


def _resume_offer() -> None:
    """After a page refresh the live session is gone from memory, but every
    turn was saved - offer to continue the user's unfinished interviews."""
    unfinished = [s for s in store.list_sessions(_username()) if s["status"] == "active"]
    for session in unfinished[:3]:
        who = session.get("stakeholder_name") or session["role_label"]
        left, right = st.columns([4, 1])
        left.info(f"Unfinished interview with **{who}** ({session['role_label']}), started "
                  f"{session['created_at'][:16].replace('T', ' ')} – "
                  f"{sum(t['speaker'] == 'stakeholder' for t in session['turns'])} answers so far.")
        if right.button("▶️ Resume", key=f"resume_{session['id']}", width="stretch"):
            st.session_state["interview"] = session
            st.rerun()


def _start_form() -> None:
    templates = role_templates()
    with st.form("start_interview"):
        st.markdown("**Start a new interview**")
        role = st.selectbox("Stakeholder role", list(templates),
                            format_func=lambda r: templates[r]["display_name"])
        name = st.text_input("Stakeholder name (optional)")
        scenario = st.text_area("What is the interview about?", height=80,
                                placeholder="e.g. Online personal loan approval for a retail bank")
        if st.form_submit_button("🎙️ Start interview", type="primary"):
            with st.spinner("Preparing knowledge-base pointers (only after the KB changes)…",
                            show_time=True):
                _save(engine.start_session(role, scenario, name, _username()))
            st.rerun()


def _chat(session: dict, model_name: str) -> None:
    for turn in session["turns"]:
        avatar = "🧑‍💼" if turn["speaker"] == "interviewer" else "🗣️"
        with st.chat_message("assistant" if turn["speaker"] == "interviewer" else "user", avatar=avatar):
            st.markdown(turn["text"])
            topic = topics().get(turn.get("topic") or "", {}).get("label", "")
            note = f"{turn['role']} · {turn['timestamp'][11:16]}" + (f" · {topic}" if topic else "")
            if turn.get("edited"):
                note += " · edited"
            assessment = turn.get("assessment")
            if assessment:
                note += f" · {assessment.get('verdict', '?')} (decided by {assessment.get('source', '?')})"
                if assessment.get("reason"):
                    note += f" — {assessment['reason']}"
            st.caption(note)

    if session["status"] != "active":
        st.success("Interview finished. It is saved and can be sent to analysis below.")
        return
    # Clear answers are decided instantly by rules; only borderline ones need
    # the model, so the answer box works even if Ollama is down.
    answer = st.chat_input("Type the stakeholder's answer…")
    if answer:
        with st.chat_message("user", avatar="🗣️"):
            st.markdown(answer)                      # show it straight away
        lock = get_run_lock()
        if not lock.acquire(blocking=False):
            st.warning("The agents are busy with another run. Please try again in a moment.")
            return
        try:
            with st.spinner("🤔 Thinking… clear answers are instant; a model check can take up to "
                            "a minute on this laptop.", show_time=True):
                engine.submit_answer(session, answer, model_name)
        finally:
            lock.release()
        _save(session)
        st.rerun()


def _coverage(session: dict) -> None:
    st.markdown("**Topic coverage**")
    st.progress(engine.coverage_ratio(session), text=f"{engine.coverage_ratio(session):.0%} covered")
    for topic, status in session["coverage"].items():
        current = " ← now" if topic == session["current_topic"] and session["status"] == "active" else ""
        st.markdown(f"{STATUS_ICONS[status]} {topics()[topic]['label']}{current}")

    if session["status"] == "active":
        left, right = st.columns(2)
        if left.button("⏭️ Skip topic", width="stretch"):
            _save(engine.skip_topic(session))
            st.rerun()
        if right.button("⏹️ End interview", width="stretch"):
            _save(engine.end_session(session))
            st.rerun()

    answers = [t for t in session["turns"] if t["speaker"] == "stakeholder"]
    if answers:
        with st.expander("✏️ Edit an answer"):
            number = st.selectbox("Answer", [t["n"] for t in answers],
                                  format_func=lambda n: f"#{n}: {next(t['text'] for t in answers if t['n'] == n)[:50]}")
            current = next(t["text"] for t in answers if t["n"] == number)
            new_text = st.text_area("Corrected answer", value=current, key=f"edit_{session['id']}_{number}")
            if st.button("Save edit") and new_text.strip() and new_text.strip() != current:
                _save(engine.edit_answer(session, number, new_text))
                st.rerun()
    if st.button("🆕 New interview"):
        st.session_state.pop("interview", None)
        st.rerun()


def _transcripts() -> None:
    st.subheader("Saved transcripts")
    sessions = store.list_sessions(_username())
    with st.expander("📥 Import a questionnaire, email or meeting notes"):
        templates = role_templates()
        role = st.selectbox("Whose answers are these (default role)?", list(templates),
                            format_func=lambda r: templates[r]["display_name"], key="import_role")
        uploaded = st.file_uploader("File", type=SUPPORTED_TYPES, key="import_file")
        pasted = st.text_area("…or paste the text", height=120, key="import_text",
                              help="Recognised: 'Q:'/'A:' lines, 'Name (Role): text' lines, "
                                   "emails with 'From:', or plain paragraphs.")
        if st.button("Import as transcript"):
            try:
                text = extract_text(uploaded.name, uploaded.getvalue()) if uploaded else pasted
                if not text.strip():
                    raise ValueError("Nothing to import.")
                session = import_transcript(text, role, uploaded.name if uploaded else "pasted text",
                                            _username())
                if not session["turns"]:
                    raise ValueError("No answers were found in the text.")
                store.save(session)
                st.success(f"Imported {len(session['turns'])} turns as {session['id']}.")
                st.rerun()
            except Exception as error:
                st.error(f"Could not import: {error}")

    if not sessions:
        st.caption("No transcripts yet.")
        return
    rows = [{"ID": s["id"], "Role": s["role_label"], "Stakeholder": s.get("stakeholder_name", ""),
             "Source": s.get("source", "interview"), "Answers": sum(t["speaker"] == "stakeholder" for t in s["turns"]),
             "Status": s["status"], "Created": s["created_at"][:16].replace("T", " ")} for s in sessions]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    chosen = st.multiselect("Transcripts to analyse", [s["id"] for s in sessions], key="send_transcripts")
    if st.button("📤 Send to analysis", type="primary", disabled=not chosen):
        st.session_state["input_mode"] = "🗣️ Use interviews"
        st.session_state["selected_transcripts"] = chosen
        st.switch_page(get_page("analysis"))


def render_interview_page() -> None:
    st.subheader("🎙️ Stakeholder interview")
    st.caption("The interviewer adapts to each answer: vague or incomplete answers get one "
               "follow-up, then it moves to the next uncovered topic.")
    model_name, _ = render_sidebar(running=False)
    session = st.session_state.get("interview")
    if session is None:
        _resume_offer()
        _start_form()
    else:
        left, right = st.columns([3, 1])
        with left:
            _chat(session, model_name)
        with right:
            _coverage(session)
    st.divider()
    _transcripts()
