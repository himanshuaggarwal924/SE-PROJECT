"""
ui/navigation.py - The current user's pages, so one page can send the user
to another (st.switch_page needs the page object).

Pages are kept in st.session_state (per user/browser session), never in a
module-level variable, because module globals are shared by every user of
the Streamlit server - one user's admin page must not leak into another's.
"""

import streamlit as st


def set_pages(pages: dict) -> None:
    st.session_state["_pages"] = pages


def get_page(name: str):
    return st.session_state.get("_pages", {}).get(name)
