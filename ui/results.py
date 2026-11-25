"""
ui/results.py - Shows the agents' results: summary metrics, requirements
tables, the SDLC recommendation, raw output, audit log and JSON download.
"""

import json

import pandas as pd
import streamlit as st

import audit_log
import config
from pipeline import AgentResult, PipelineResult

PRIORITY_BADGES = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟢 Low"}
RATING_BADGES = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟢 Low"}
FLAG_LABELS = {
    "invalid_citation": "❌ Invalid citation (removed)",
    "missing_citation": "📎 No source cited",
    "possible_hallucination": "⚠️ Possible hallucination",
    "uncited_number": "🔎 Number not in the cited excerpts",
    "unsupported_rule": "🚫 Rule not in the knowledge base (removed)",
    "weak_citation": "🪫 Cited excerpt barely relates to the statement",
    "low_confidence": "📉 Low confidence",
}


def _badge(value: str, badges: dict) -> str:
    return badges.get((value or "").strip().lower(), value)


def _confidence_icon(confidence: float) -> str:
    if confidence >= 0.8:
        return "🟢"
    if confidence >= config.CONFIDENCE_REVIEW_THRESHOLD:
        return "🟠"
    return "🔴"


def _overview_table(requirements) -> None:
    rows = [{"ID": r.id, "Categories": r.categories, "Requirement": r.statement,
             "Priority": _badge(r.priority, PRIORITY_BADGES),
             "Risk": _badge(r.risk_level, RATING_BADGES),
             "Confidence": r.confidence,
             "Review": "⚠️ needs review" if r.needs_human_review else ""}
            for r in requirements]
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, width="stretch",
        column_config={
            "ID": st.column_config.TextColumn(width="small"),
            "Categories": st.column_config.ListColumn(width="medium"),
            "Requirement": st.column_config.TextColumn(width="large"),
            "Confidence": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0,
                                                          format="%.2f", width="small"),
        },
    )


def _show_citations(sources: list[str], chunk_map: dict) -> None:
    """One popover per cited excerpt, showing the excerpt's text."""
    if not sources:
        st.caption("📎 No excerpt cited.")
        return
    columns = st.columns(min(len(sources), 6))
    for i, cid in enumerate(sources):
        chunk = chunk_map.get(cid, {})
        icon = {"kb": "📚", "transcript": "🗣️"}.get(chunk.get("origin"), "📎")
        with columns[i % len(columns)].popover(f"{icon} {cid}", width="stretch"):
            similarity = chunk.get("similarity")
            extra = f" · similarity {similarity:.2f}" if similarity is not None else ""
            if chunk.get("origin") == "transcript":
                st.caption(f"🗣️ {chunk.get('document')} · {str(chunk.get('timestamp', ''))[:16].replace('T', ' ')}"
                           f"{extra}")
            elif chunk.get("origin") == "kb":
                st.caption(f"**{chunk.get('title')}** v{chunk.get('version')} · {chunk.get('type')} · "
                           f"{chunk.get('source')} · section: {chunk.get('section')}{extra}")
            else:
                st.caption(f"{chunk.get('document', '?')} · part "
                           f"{(chunk.get('position') or 0) + 1}{extra}")
            st.text(chunk.get("text", "(excerpt not available)"))


def _rule_name(cid: str, chunk_map: dict) -> str:
    chunk = chunk_map.get(cid)
    return f"{cid}: {chunk['title']} – {chunk['section']}" if chunk else cid


def _requirement_card(r, chunk_map: dict) -> None:
    review = " · ⚠️ needs review" if r.needs_human_review else ""
    title = f"{_confidence_icon(r.confidence)} {r.id} · {r.confidence:.2f}{review} — {r.statement}"
    with st.expander(title):
        st.markdown(" ".join(f":blue-badge[{c}]" for c in r.categories)
                    + f" :gray-badge[priority {r.priority}] :gray-badge[risk {r.risk_level}]"
                    + f" :violet-badge[{r.approval_status}]")
        st.markdown(f"**{r.statement}**")
        if r.business_justification:
            st.markdown(f"**Why:** {r.business_justification}")
        if r.source_stakeholder:
            st.markdown(f"**Stakeholder:** {r.source_stakeholder}")
        if r.acceptance_criteria:
            st.markdown("**Acceptance criteria**")
            st.markdown("\n".join(f"- *Given* {c.given}, *when* {c.when}, *then* {c.then}"
                                  for c in r.acceptance_criteria))
        rules = [_rule_name(cid, chunk_map) for cid in r.applicable_rules]
        for label, values in (("Depends on", r.dependencies), ("Applicable rules (KB)", rules),
                              ("Assumptions", r.assumptions)):
            if values:
                st.markdown(f"**{label}:** " + "; ".join(values))

        st.markdown("**Sources**")
        _show_citations(r.sources, chunk_map)

        for flag in r.flags:
            st.warning(f"{FLAG_LABELS.get(flag.type, flag.type)}: {flag.detail}")
        breakdown = ", ".join(f"{k.replace('_', ' ')} {v:.2f}" for k, v in r.confidence_breakdown.items())
        st.caption(f"Confidence {r.confidence:.2f} = weighted mean of: {breakdown} "
                   f"(model's own rating {r.model_confidence:.2f}).")


def show_requirements(agent_result: AgentResult, result: PipelineResult) -> None:
    data = agent_result.parsed
    if data.scenario_summary:
        st.markdown(f"> {data.scenario_summary}")

    summary = data.validation_summary or {}
    if summary.get("produced", 0) < summary.get("requested", 0):
        st.warning(f"Only {summary['produced']} of {summary['requested']} requested requirements "
                   f"were produced ({summary.get('failed_batches', 0)} batch(es) failed to parse).")

    only_review = st.toggle("Show only requirements that need review",
                            key=f"only_review_{result.run_id}")
    for title, items in (("Functional requirements", data.functional_requirements),
                         ("Non-functional requirements", data.non_functional_requirements)):
        shown = [r for r in items if r.needs_human_review or not only_review]
        st.markdown(f"#### {title} ({len(shown)})")
        if shown:
            _overview_table(shown)
            for requirement in shown:
                _requirement_card(requirement, result.chunk_map)

    if data.assumptions:
        st.markdown("#### Assumptions")
        st.markdown("\n".join(f"- {a}" for a in data.assumptions))
    _process_flowchart(data, result)


def _process_flowchart(data, result) -> None:
    """The process as a flowchart whose boxes are requirement IDs (Phase 12)."""
    from artefacts import process_flow
    included = [r for r in data.requirements if r.approval_status != "rejected"]
    if not included:
        return
    flow = process_flow.build_flow(included, "Loan application" if "loan" in result.scenario.lower() else "Process")
    with st.expander("🗺️ Process workflow flowchart (boxes = requirement IDs)"):
        st.caption("Diamonds are decisions with an exception path to human handling; "
                   "boxes linked with dotted lines are non-functional controls.")
        st.graphviz_chart(process_flow.to_dot(flow), use_container_width=True)
        mermaid = process_flow.to_mermaid(flow)
        st.download_button("⬇️ Mermaid source (.mmd)", data=mermaid, file_name=f"process_{result.run_id}.mmd",
                           key=f"mmd_{result.run_id}")
        st.code(mermaid, language="text")


def _ranking_chart(ranking) -> None:
    import altair as alt
    df = pd.DataFrame([{"Model": r.model, "Score": r.score, "Top": r.rank == 1} for r in ranking])
    bars = alt.Chart(df).mark_bar().encode(
        y=alt.Y("Model:N", sort="-x", title=None),
        x=alt.X("Score:Q", scale=alt.Scale(domain=[0, 100]), title="Score (%)"),
        color=alt.condition("datum.Top", alt.value("#1f6feb"), alt.value("#9aa4b2")),
        tooltip=["Model", "Score"])
    labels = bars.mark_text(align="left", dx=4).encode(text=alt.Text("Score:Q", format=".0f"))
    st.altair_chart((bars + labels).properties(height=34 * len(df)), use_container_width=True)


def show_sdlc(agent_result: AgentResult, result: PipelineResult) -> None:
    from agents.sdlc_scoring import FACTOR_LABELS
    data = agent_result.parsed
    top = data.ranking[0] if data.ranking else None
    with st.container(border=True):
        st.markdown(f"### 🧭 {data.recommended_model}" + (f" — {top.score:.0f}%" if top else ""))
        st.caption(f"Ranked first by the scoring rules (config/sdlc_rules.yaml) · confidence "
                   f"**{data.confidence}** (lead over #2) · approval: **{data.approval_status}**")
        st.markdown(data.explanation)
        if data.scoring_basis:
            st.info(data.scoring_basis, icon="📊")
        if data.explanation_source == "template":
            st.caption("The AI explanation was unavailable, so this text was generated from the scores.")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Ranking")
        _ranking_chart(data.ranking)
    with right:
        st.markdown("#### Why not the runners-up")
        for alt_model in data.runner_up_explanations:
            st.markdown(f"- **{alt_model.model}** — {alt_model.reason_not_chosen}")
        if data.key_practices:
            st.markdown("#### Recommended practices")
            st.markdown("\n".join(f"- {p}" for p in data.key_practices))

    st.markdown("#### Decision factors")
    rows = [{"Factor": FACTOR_LABELS.get(f.factor, f.factor), "Rating": _badge(f.rating, RATING_BADGES),
             "Scored": "✅" if f.scored else "— no evidence", "Evidence": f.evidence, "Reasoning": f.reasoning, "Flags": [x.type for x in f.flags]}
            for f in data.factors]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        "Evidence": st.column_config.ListColumn(), "Flags": st.column_config.ListColumn(),
        "Reasoning": st.column_config.TextColumn(width="large")})
    with st.expander("How each model was scored"):
        for r in data.ranking:
            st.markdown(f"**{r.rank}. {r.model} — {r.score:.0f}%**  \n{r.summary}")


def _phase_list(phase, field: str) -> str:
    added = {a.split(": ", 1)[1] for a in phase.added if a.startswith(f"{field}: ")}
    items = getattr(phase, field)
    if not items:
        return "—"
    return "\n".join(f"- {'🆕 ' if i in added else ''}{i}" for i in items)


def show_workflow(agent_result: AgentResult, result: PipelineResult) -> None:
    data = agent_result.parsed
    st.markdown(f"### 🛠️ {data.model} workflow")
    st.caption(data.summary + "  ·  🆕 = added for this project"
               + ("" if data.customised_by_ai else "  ·  AI tailoring unavailable: standard template shown"))
    sections = [("Activities", "activities"), ("Roles", "roles"), ("Deliverables", "deliverables"),
                ("Security", "security_activities"), ("Testing", "testing"),
                ("Compliance checkpoints", "compliance_checkpoints"),
                ("🔒 Human approval gates", "approval_gates"), ("Entry criteria", "entry_criteria"),
                ("Exit criteria", "exit_criteria"), ("Traceability", "traceability")]
    for number, phase in enumerate(data.phases, start=1):
        with st.expander(f"{number}. {phase.name}" + (f" — {len(phase.added)} project-specific"
                                                       if phase.added else ""), expanded=number == 1):
            if phase.project_notes:
                st.info(phase.project_notes)
            columns = st.columns(3)
            for i, (label, field) in enumerate(sections):
                with columns[i % 3]:
                    st.markdown(f"**{label}**")
                    st.markdown(_phase_list(phase, field))


SEVERITY_BADGES = {"high": "🔴 High", "medium": "🟠 Medium", "low": "🟢 Low"}


def show_quality(agent_result: AgentResult, result: PipelineResult) -> None:
    data = agent_result.parsed
    summary = data.summary or {}
    severity = summary.get("issues_by_severity", {})
    cols = st.columns(4)
    cols[0].metric("High-severity issues", severity.get("High", 0))
    cols[1].metric("All issues", sum(severity.values()))
    cols[2].metric("Clarification questions", summary.get("clarification_questions", 0))
    cols[3].metric("Duplicates / conflicts", f"{len(data.duplicates)} / {len(data.conflicts)}")

    for pair in data.conflicts:
        st.error(f"⚔️ Possible conflict: {' vs '.join(pair['ids'])} — {pair['detail']}")
    for pair in data.duplicates:
        st.warning(f"👯 Possible duplicates: {' and '.join(pair['ids'])} "
                   f"(similarity {pair['similarity']}, {pair.get('method', '')})")

    rows = [{"Requirement": review.requirement_id, "Severity": _badge(issue.severity, SEVERITY_BADGES),
             "Type": issue.type.replace("_", " "), "Found by": "rule" if issue.origin == "rule" else "AI",
             "Explanation": issue.explanation}
            for review in data.reviews for issue in review.issues]
    st.markdown("#### Issues")
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={"Explanation": st.column_config.TextColumn(width="large")})
    else:
        st.success("No quality issues found.")

    questions = [(q.stakeholder_role or "Unassigned", review.requirement_id, q.question)
                 for review in data.reviews for q in review.clarification_questions]
    if questions:
        st.markdown("#### Clarification questions for stakeholders")
        for role in sorted({q[0] for q in questions}):
            with st.expander(f"🗣️ {role} ({sum(q[0] == role for q in questions)})"):
                st.markdown("\n".join(f"- **{rid}:** {text}" for r, rid, text in questions if r == role))


def show_compliance(agent_result: AgentResult, result: PipelineResult) -> None:
    data = agent_result.parsed
    st.warning(data.disclaimer, icon="⚖️")
    summary = data.summary or {}
    cols = st.columns(3)
    cols[0].metric("Need compliance-officer approval", summary.get("need_compliance_officer_approval", 0))
    cols[1].metric("Mapped to a KB rule", f"{summary.get('with_kb_rule', 0)} / {summary.get('mapped', 0)}")
    cols[2].metric("Suggested requirements", len(data.suggested_requirements))

    rows = [{"Requirement": m.requirement_id, "Impact": _badge(m.impact, RATING_BADGES),
             "Officer approval": "🔒 required" if m.requires_compliance_officer_approval else "—",
             "Rules (KB)": [_rule_name(cid, result.chunk_map) for cid in m.applicable_rules],
             "Controls": m.required_controls, "Gaps": m.compliance_gaps,
             "Checkpoints": m.approval_checkpoints, "Retention / reporting": m.retention_reporting_obligations,
             "Flags": [f.type for f in m.flags], "Status": m.approval_status}
            for m in data.mappings]
    st.markdown("#### Compliance mappings")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        col: st.column_config.ListColumn() for col in
        ("Rules (KB)", "Controls", "Gaps", "Checkpoints", "Retention / reporting", "Flags")})

    if data.suggested_requirements:
        st.markdown("#### Suggested security / privacy requirements")
        st.caption("Status *suggested*: proposed by a baseline-control checklist; a human decides "
                   "whether to add them.")
        for s in data.suggested_requirements:
            with st.expander(f"💡 {s.id} — {s.statement}"):
                st.markdown(" ".join(f":blue-badge[{c}]" for c in s.categories)
                            + f" :violet-badge[{s.status}]")
                st.markdown(s.rationale)
                _show_citations(s.sources, result.chunk_map)


# Which display function to use for which agent. A new agent without an
# entry here is still shown - just as plain JSON.
RENDERERS = {"requirements_agent": show_requirements, "quality_agent": show_quality,
             "compliance_agent": show_compliance, "sdlc_agent": show_sdlc,
             "workflow_agent": show_workflow}
TAB_ICONS = {"requirements_agent": "📋", "quality_agent": "🔍", "compliance_agent": "⚖️",
             "sdlc_agent": "🧭", "workflow_agent": "🛠️"}


def _show_agent(agent_result: AgentResult, result: PipelineResult) -> None:
    if agent_result.status == "not_run":
        st.info("Not run yet – the run is waiting for review.")
        return
    if agent_result.status == "skipped":
        st.info(agent_result.parse_error or "This step was skipped.")
        return
    if agent_result.parsed is None:
        st.warning("The model's answer wasn't valid structured JSON, so the raw text is "
                   "shown below. Try running again.")
        st.code(agent_result.parse_error or "", language=None)
        st.text(agent_result.raw_output)
        return
    if agent_result.status == "partial":
        with st.expander("⚠️ Some model calls could not be parsed"):
            st.code(agent_result.parse_error or "", language=None)
    renderer = RENDERERS.get(agent_result.key)
    if renderer:
        renderer(agent_result, result)
    else:
        st.json(agent_result.parsed.model_dump())
    with st.expander("Raw model output"):
        st.code(agent_result.raw_output, language="json")


def _summary_metrics(result: PipelineResult) -> None:
    requirements = result.get("requirements_agent")
    sdlc = result.get("sdlc_agent")
    minutes, seconds = divmod(result.elapsed_seconds, 60)
    cols = st.columns(5)
    if requirements and requirements.parsed:
        data = requirements.parsed
        cols[0].metric("Functional reqs", len(data.functional_requirements))
        cols[1].metric("Non-functional reqs", len(data.non_functional_requirements))
        cols[2].metric("Need review", sum(r.needs_human_review for r in data.requirements))
    if sdlc and sdlc.parsed:
        cols[3].metric("SDLC model", sdlc.parsed.recommended_model)
    cols[4].metric("Run time", f"{minutes}m {seconds}s")


def show_artefacts(result: PipelineResult) -> None:
    from artefacts.bundle import DESCRIPTIONS, generate, zip_all
    if result.status == "awaiting_review":
        st.info("Artefacts are generated after the review is finished.")
        return
    cache = st.session_state.setdefault("artefacts", {})
    approved = [r for r in (result.get("requirements_agent").parsed.requirements
                            if result.get("requirements_agent") and result.get("requirements_agent").parsed else [])
                if r.approval_status == "approved"]
    st.caption(f"Built from the {len(approved)} approved requirement(s)." if approved else
               "No requirement is approved, so the artefacts are marked DRAFT.")
    from storage import projects
    if result.run_id not in cache:
        stored = projects.stored_artefacts(result.run_id)
        if stored:
            cache[result.run_id] = stored
            st.caption("Showing the stored artefacts of this run – generate again to refresh them.")
    if st.button("📦 Generate artefacts", key=f"gen_{result.run_id}"):
        with st.spinner("Generating documents…"):
            cache[result.run_id] = generate(result, st.session_state.get("username"))
            projects.store_artefacts(result.run_id, cache[result.run_id], st.session_state.get("username"))
    files = cache.get(result.run_id)
    if not files:
        return
    st.download_button("⬇️ Download all (ZIP)", data=zip_all(files, result.run_id), type="primary",
                       file_name=f"artefacts_{result.run_id}.zip", mime="application/zip")
    mimes = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "csv": "text/csv", "md": "text/markdown", "mmd": "text/plain"}
    for name, content in files.items():
        left, right = st.columns([3, 1])
        left.markdown(f"**{name}** – {DESCRIPTIONS[name]}")
        right.download_button("⬇️ Download", data=content, file_name=name, key=f"dl_{result.run_id}_{name}",
                              mime=mimes[name.rsplit('.', 1)[1]], width="stretch")


def render_results(result: PipelineResult) -> None:
    st.subheader("Results")
    _summary_metrics(result)

    agent_tabs = [f"{TAB_ICONS.get(r.key, '🤖')} {r.display_name}" for r in result.agent_results]
    tabs = st.tabs(agent_tabs + ["📦 Artefacts", "🗂️ Source & audit"])
    with tabs[-2]:
        show_artefacts(result)
    for tab, agent_result in zip(tabs, result.agent_results):
        with tab:
            _show_agent(agent_result, result)

    with tabs[-1]:
        info = result.context_info or {}
        st.markdown("#### How the source material was prepared")
        if info.get("quarantined"):
            st.error(f"🛑 {len(info['quarantined'])} excerpt(s) looked like prompt injection and were left out:")
            for item in info["quarantined"]:
                st.caption(f"{item['source']} – {', '.join(item['patterns'])}: “{item['preview']}”")
        if result.pii_masked:
            st.info("🔒 Sensitive values masked before any model call: "
                    + ", ".join(f"{count} × {kind}" for kind, count in result.pii_masked.items()))
        st.json(info, expanded=True)
        if result.versions:
            with st.expander("Versions used in this run (model, prompts, knowledge base, rules)"):
                st.json(result.versions, expanded=False)
        kb_chunks = {cid: c for cid, c in result.chunk_map.items() if c.get("origin") == "kb"}
        if kb_chunks:
            st.markdown("#### Knowledge-base excerpts given to the agents")
            st.caption("SAMPLE knowledge-base content is illustrative, not authoritative.")
            st.dataframe(pd.DataFrame([
                {"Citation": cid, "Item": c["kb_id"], "Title": c["title"], "Version": c["version"],
                 "Type": c["type"], "Section": c["section"], "Similarity": c.get("similarity")}
                for cid, c in kb_chunks.items()]), hide_index=True, width="stretch")
        with st.expander(f"Audit log for run {result.run_id}"):
            st.json(audit_log.read_events(result.run_id), expanded=False)

    export = {
        "run_id": result.run_id,
        "model": result.model_name,
        "context": result.context_info,
        "citations": result.chunk_map,
        "agents": {r.key: r.parsed.model_dump() if r.parsed else {"raw_output": r.raw_output}
                   for r in result.agent_results},
    }
    st.download_button("⬇️ Download results (JSON)", data=json.dumps(export, indent=2),
                       file_name=f"results_{result.run_id}.json", mime="application/json")

