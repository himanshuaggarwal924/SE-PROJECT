"""
ui/results.py - Shows the agents' results: summary metrics, requirements
tables, the SDLC recommendation, raw output, audit log and JSON download.
"""

import json

import pandas as pd
import streamlit as st

import audit_log
from pipeline import AgentResult, PipelineResult

PRIORITY_BADGES = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟢 Low"}
RATING_BADGES = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟢 Low"}


def _badge(value: str, badges: dict) -> str:
    return badges.get((value or "").strip().lower(), value)


def _requirements_table(requirements) -> None:
    rows = [{"ID": r.id, "Category": r.category, "Requirement": r.description,
             "Priority": _badge(r.priority, PRIORITY_BADGES), "Why": r.reasoning}
            for r in requirements]
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, width="stretch",
        column_config={
            "ID": st.column_config.TextColumn(width="small"),
            "Category": st.column_config.TextColumn(width="small"),
            "Requirement": st.column_config.TextColumn(width="large"),
            "Priority": st.column_config.TextColumn(width="small"),
            "Why": st.column_config.TextColumn(width="medium"),
        },
    )


def show_requirements(agent_result: AgentResult) -> None:
    data = agent_result.parsed
    if data.scenario_summary:
        st.markdown(f"> {data.scenario_summary}")
    st.markdown(f"#### Functional requirements ({len(data.functional_requirements)})")
    _requirements_table(data.functional_requirements)
    st.markdown(f"#### Non-functional requirements ({len(data.non_functional_requirements)})")
    _requirements_table(data.non_functional_requirements)
    if data.assumptions:
        st.markdown("#### Assumptions")
        st.markdown("\n".join(f"- {a}" for a in data.assumptions))


def show_sdlc(agent_result: AgentResult) -> None:
    data = agent_result.parsed
    with st.container(border=True):
        st.markdown(f"### 🧭 {data.recommended_model}")
        st.caption(f"Recommended SDLC model · confidence: **{data.confidence or 'not stated'}**")
        st.markdown(data.justification)

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Requirement characteristics")
        rows = [{"Factor": c.factor, "Rating": _badge(c.rating, RATING_BADGES),
                 "Evidence": c.evidence} for c in data.characteristics]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Evidence": st.column_config.TextColumn(width="large")})
    with right:
        st.markdown("#### Alternatives not chosen")
        for alt in data.alternatives_considered:
            st.markdown(f"- **{alt.model}** - {alt.reason_not_chosen}")
        if data.key_practices:
            st.markdown("#### Recommended practices")
            st.markdown("\n".join(f"- {p}" for p in data.key_practices))


# Which display function to use for which agent. A new agent without an
# entry here is still shown - just as plain JSON.
RENDERERS = {"requirements_agent": show_requirements, "sdlc_agent": show_sdlc}


def _show_agent(agent_result: AgentResult) -> None:
    if agent_result.parsed is None:
        st.warning("The model's answer wasn't valid structured JSON, so the raw text is "
                   "shown below. Try running again.")
        st.code(agent_result.parse_error or "", language=None)
        st.text(agent_result.raw_output)
        return
    renderer = RENDERERS.get(agent_result.key)
    if renderer:
        renderer(agent_result)
    else:
        st.json(agent_result.parsed.model_dump())
    with st.expander("Raw model output"):
        st.code(agent_result.raw_output, language="json")


def _summary_metrics(result: PipelineResult) -> None:
    requirements = result.get("requirements_agent")
    sdlc = result.get("sdlc_agent")
    minutes, seconds = divmod(result.elapsed_seconds, 60)
    cols = st.columns(4)
    if requirements and requirements.parsed:
        cols[0].metric("Functional reqs", len(requirements.parsed.functional_requirements))
        cols[1].metric("Non-functional reqs", len(requirements.parsed.non_functional_requirements))
    if sdlc and sdlc.parsed:
        cols[2].metric("SDLC model", sdlc.parsed.recommended_model)
    cols[3].metric("Run time", f"{minutes}m {seconds}s")


def render_results(result: PipelineResult) -> None:
    st.subheader("Results")
    _summary_metrics(result)

    agent_tabs = [f"{'📋' if i == 0 else '🧭'} {r.display_name}"
                  for i, r in enumerate(result.agent_results)]
    tabs = st.tabs(agent_tabs + ["🔍 Source & audit"])
    for tab, agent_result in zip(tabs, result.agent_results):
        with tab:
            _show_agent(agent_result)

    with tabs[-1]:
        info = result.context_info or {}
        st.markdown("#### How the source material was prepared")
        st.json(info, expanded=True)
        with st.expander(f"Audit log for run {result.run_id}"):
            st.json(audit_log.read_events(result.run_id), expanded=False)

    export = {
        "run_id": result.run_id,
        "model": result.model_name,
        "context": result.context_info,
        "agents": {r.key: r.parsed.model_dump() if r.parsed else {"raw_output": r.raw_output}
                   for r in result.agent_results},
    }
    st.download_button("⬇️ Download results (JSON)", data=json.dumps(export, indent=2),
                       file_name=f"results_{result.run_id}.json", mime="application/json")

