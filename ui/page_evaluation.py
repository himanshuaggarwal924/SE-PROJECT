"""
ui/page_evaluation.py - The evaluation dashboard (Phase 10).

Shows results written by `python run_eval.py` (evaluation/results/): full
system vs single-prompt baseline, per metric and per document, plus the live
human-correction rate from the audit log.
"""

import altair as alt
import pandas as pd
import streamlit as st

import audit_log
from evaluation.metrics import human_correction_rate
from evaluation.runner import SCALAR_METRICS, load_results

RATE_METRICS = [m for m in SCALAR_METRICS if m != "total_seconds"]
LOWER_IS_BETTER = {"hallucination_rate"}


def _fmt(value):
    return "n/a" if value is None else value


def _satisfaction_form() -> None:
    """Short stakeholder satisfaction survey (1-5 + comment) and its summary."""
    import pipeline
    from storage import feedback
    with st.container(border=True):
        st.markdown("#### 🙂 Stakeholder satisfaction")
        summary = feedback.summary()
        cols = st.columns([1, 1, 2])
        cols[0].metric("Responses", summary["responses"])
        cols[1].metric("Average (1–5)", _fmt(summary["mean"]))
        if summary["responses"]:
            cols[2].bar_chart(pd.DataFrame({"responses": summary["distribution"]}), height=120)
        with st.form("satisfaction", clear_on_submit=True):
            runs = pipeline.runs_for(st.session_state.get("username"))
            run = st.selectbox("Which run is this about? (optional)", ["(general)"] + [r["run_id"] for r in runs])
            score = st.radio("How useful were the generated requirements and recommendations?",
                             [1, 2, 3, 4, 5], index=None, horizontal=True,
                             format_func=lambda n: {1: "1 – not useful", 3: "3", 5: "5 – very useful"}.get(n, str(n)))
            comment = st.text_area("Comment (optional)", max_chars=2000)
            if st.form_submit_button("Submit rating"):
                if score is None:
                    st.error("Please choose a score from 1 to 5.")
                else:
                    feedback.submit(st.session_state.get("username"), score, comment,
                                    None if run == "(general)" else run)
                    st.success("Thank you – your rating was saved.")


def render_evaluation_page() -> None:
    st.subheader("📊 Evaluation")
    st.caption("Run `python run_eval.py` (or `--fast`, or `--mock` for a wiring check) to create results. "
               "Full system = the agent pipeline; baseline = the same model with one plain prompt, no RAG.")

    live = human_correction_rate(audit_log.read_events())
    cols = st.columns(3)
    cols[0].metric("Human decisions (audit log)", live["human_decisions"])
    cols[1].metric("Corrections (edit / regenerate / reject)", live["human_corrections"])
    cols[2].metric("Human correction rate", _fmt(live["human_correction_rate"]))

    _satisfaction_form()

    results = load_results()
    if not results:
        st.info("No evaluation results yet.")
        return
    labels = [f"{path.stem} · {data['meta']['model']}" for path, data in results]
    chosen = st.selectbox("Results", range(len(results)), format_func=lambda i: labels[i])
    path, data = results[chosen]
    meta = data["meta"]
    if meta.get("mock"):
        st.error("This is a MOCK run (canned model answers): the numbers only show that the wiring works.")
    drafts = [name for name, status in meta.get("gold_files", {}).items() if status.startswith("DRAFT")]
    if drafts:
        st.warning(f"Gold files not yet reviewed (DRAFT): {', '.join(drafts)}. Treat the scores as provisional.")
    st.caption(f"Created {meta['created_at'][:16].replace('T', ' ')} · match threshold "
               f"{meta.get('match_threshold')} · options {meta.get('options')}")

    systems = list(data["summary"])
    table = pd.DataFrame([{"Metric": m + (" (lower is better)" if m in LOWER_IS_BETTER else ""),
                           **{s.capitalize(): _fmt(data["summary"][s].get(m)) for s in systems}}
                          for m in SCALAR_METRICS])
    st.markdown("#### Full system vs baseline (mean over documents)")
    st.dataframe(table, hide_index=True, width="stretch")

    long = pd.DataFrame([{"Metric": m, "System": s, "Value": data["summary"][s].get(m)}
                         for m in RATE_METRICS for s in systems if data["summary"][s].get(m) is not None])
    if not long.empty:
        chart = alt.Chart(long).mark_bar().encode(
            x=alt.X("Value:Q", scale=alt.Scale(domain=[0, 1])), y=alt.Y("System:N", title=None),
            color="System:N", row=alt.Row("Metric:N", header=alt.Header(labelAngle=0, labelAlign="left")),
            tooltip=["Metric", "System", "Value"]).properties(height=28, width=420)
        st.altair_chart(chart)

    for name, scores in data["documents"].items():
        with st.expander(f"📄 {name} (run {scores.get('run_id')})"):
            rows = [{"Metric": m, **{s.capitalize(): _fmt(scores[s].get(m)) for s in systems if s in scores}}
                    for m in SCALAR_METRICS]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            stages = scores["full"].get("stage_seconds", {})
            if stages:
                st.markdown("**Processing time per stage (full system)**")
                st.bar_chart(pd.DataFrame({"seconds": stages}), horizontal=True)
            matches = scores["full"].get("matches", [])
            if matches:
                st.markdown("**Matched requirements (full system)**")
                st.dataframe(pd.DataFrame(matches), hide_index=True, width="stretch")
            missing = scores["full"].get("controls_missing")
            if missing:
                st.caption("Controls not covered: " + ", ".join(missing))
    st.download_button("⬇️ Download these results (JSON)", data=path.read_bytes(), file_name=path.name,
                       mime="application/json")
