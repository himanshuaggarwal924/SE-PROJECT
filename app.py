"""
app.py - Streamlit web app (entry point).

Start it with:   streamlit run app.py
Then open the address it prints (usually http://localhost:8501).

This file only does login and page navigation. The pieces live in:
    auth/  - login, sign-up, password reset, roles
    ui/    - the pages (analysis, knowledge base) and their parts
    pipeline.py + orchestration/ - the LangGraph agent pipeline
"""

import streamlit as st

from auth import rbac
from auth.auth_ui import require_login, show_account_box
from ui.navigation import set_pages
from ui.page_account import render_account_page
from ui.page_admin import render_admin_page
from ui.page_analysis import render_analysis_page
from ui.page_evaluation import render_evaluation_page
from ui.page_interview import render_interview_page
from ui.page_knowledge_base import render_knowledge_base_page
from ui.page_projects import render_project_selector, render_projects_page

st.set_page_config(page_title="FinReq Agents", page_icon="🏦", layout="wide")
st.title("🏦 Finance Requirements Agents")

# 1. Nobody gets past this line without logging in.
authenticator = require_login()
show_account_box(authenticator)
render_project_selector()        # the current project (sidebar)

# 2. Pages - which ones a user sees depends on their roles.
pages = {
    "analysis": st.Page(render_analysis_page, title="Requirements analysis", icon="🏦",
                        url_path="analysis", default=True),
    "interview": st.Page(render_interview_page, title="Stakeholder interview", icon="🎙️",
                         url_path="interview"),
    "projects": st.Page(render_projects_page, title="Projects & history", icon="📁", url_path="projects"),
    "evaluation": st.Page(render_evaluation_page, title="Evaluation", icon="📊", url_path="evaluation"),
    "account": st.Page(render_account_page, title="My account", icon="👤", url_path="account"),
}
if rbac.can(st.session_state.get("username"), "manage_kb"):
    pages["knowledge_base"] = st.Page(render_knowledge_base_page, title="Knowledge base",
                                      icon="📚", url_path="knowledge-base")
    pages["admin"] = st.Page(render_admin_page, title="Administration", icon="🛡️", url_path="admin")
set_pages(pages)   # per user session (see ui/navigation.py)
st.navigation(list(pages.values())).run()
