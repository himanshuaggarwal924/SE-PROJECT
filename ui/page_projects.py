"""
ui/page_projects.py - Projects, requirement history and diffs (Phase 7).
"""

import pandas as pd
import streamlit as st

from storage import baselines, projects

CHANGE_ICONS = {"added": "🟢 added", "removed": "🔴 removed", "changed": "🟠 changed", "unchanged": "⚪ unchanged"}


def current_project() -> str:
    return st.session_state.get("project", "default")


def render_project_selector() -> str:
    """Sidebar project picker (shared by every page)."""
    names = [p["name"] for p in projects.list_projects()]
    if current_project() not in names:
        st.session_state["project"] = "default"
    st.sidebar.selectbox("📁 Project", names, key="project")
    return current_project()


def _source_options(project: str) -> dict[str, tuple[str, object]]:
    options = {}
    for b in baselines.baselines_for(project):
        options[f"Baseline v{b['version']} ({b['created_at'][:10]})"] = ("baseline", b)
    for run in projects.project_runs(project):
        options[f"Run {run['run_id']} ({run['status']})"] = ("run", run["run_id"])
    return options


def _requirements_of(source: tuple[str, object]) -> list[dict]:
    kind, value = source
    return value["content"]["requirements"] if kind == "baseline" else projects.run_requirements(value)


def render_projects_page() -> None:
    project = current_project()
    st.subheader(f"📁 Project: {project}")

    with st.expander("➕ New project"):
        with st.form("new_project", clear_on_submit=True):
            name = st.text_input("Name")
            description = st.text_input("Description")
            if st.form_submit_button("Create"):
                try:
                    projects.create_project(name, description, st.session_state.get("username"))
                    st.success(f"Project '{name.strip()}' created – select it in the sidebar.")
                except ValueError as error:
                    st.error(str(error))

    runs_tab, history_tab, diff_tab = st.tabs(["Runs and baselines", "Requirement history", "Compare"])
    with runs_tab:
        runs = projects.project_runs(project)
        if runs:
            st.dataframe(pd.DataFrame([{"Run": r["run_id"], "By": r["user"], "Status": r["status"],
                                        "Stage": r["stage"], "Scenario": r["scenario"][:80],
                                        "Updated": r["updated_at"][:16].replace("T", " ")} for r in runs]),
                         hide_index=True, width="stretch")
        else:
            st.caption("No runs in this project yet.")
        versions = baselines.baselines_for(project)
        if versions:
            st.markdown("**Baselines**")
            st.dataframe(pd.DataFrame([{"Version": b["version"], "Run": b["run_id"], "By": b["created_by"],
                                        "When": b["created_at"][:16].replace("T", " "),
                                        "Requirements": len(b["content"]["requirements"]), "Hash": b["content_hash"],
                                        "Note": b["note"]} for b in versions]), hide_index=True, width="stretch")

    with history_tab:
        ids = projects.requirement_ids(project)
        if not ids:
            st.caption("No requirement versions recorded yet.")
        else:
            rid = st.selectbox("Requirement", ids)
            history = projects.requirement_history(project, rid)
            st.dataframe(pd.DataFrame([{"When": h["created_at"][:16].replace("T", " "), "Run": h["run_id"],
                                        "Version": h["version"], "Source": h["source"],
                                        "Status": h["content"].get("approval_status"),
                                        "By": h["created_by"], "Statement": h["content"]["statement"]}
                                       for h in history]), hide_index=True, width="stretch")

    with diff_tab:
        options = _source_options(project)
        if len(options) < 2:
            st.caption("Compare needs at least two runs or baselines in this project.")
            return
        labels = list(options)
        left, right = st.columns(2)
        a = left.selectbox("From", labels, index=min(1, len(labels) - 1))
        b = right.selectbox("To", labels, index=0)
        rows = projects.diff_requirements(_requirements_of(options[a]), _requirements_of(options[b]))
        counts = {k: sum(r["change"] == k for r in rows) for k in CHANGE_ICONS}
        st.caption(" · ".join(f"{CHANGE_ICONS[k]}: {v}" for k, v in counts.items()))
        show_all = st.toggle("Show unchanged requirements")
        st.dataframe(pd.DataFrame([{"ID": r["id"], "Change": CHANGE_ICONS[r["change"]], "Before": r["before"],
                                    "After": r["after"], "Details": r["details"]} for r in rows
                                   if show_all or r["change"] != "unchanged"]), hide_index=True, width="stretch")
