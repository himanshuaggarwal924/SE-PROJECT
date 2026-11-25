"""
ui/page_knowledge_base.py - Browse the knowledge base (admin role only).

Read-only on purpose: KB items are Markdown files in kb/, changed through
version control, and re-indexed automatically on the next run when their
content hash changes.
"""

import pandas as pd
import streamlit as st

import config
from auth import user_store
from rag.knowledge_base import is_evidence, load_items


def render_knowledge_base_page() -> None:
    # Defence in depth: the page is only listed for admins, but check again.
    from auth import rbac
    if not rbac.can(st.session_state.get("username"), "manage_kb"):
        st.error("Only administrators can view the knowledge base.")
        return

    st.subheader("📚 Knowledge base")
    st.caption(f"Items are Markdown files in `{config.KB_DIR.name}/` with YAML front-matter "
               "(see kb/README.md). Edit them through version control; changed files are "
               "re-indexed automatically on the next run.")
    st.warning("Shipped items are **SAMPLE – illustrative, not authoritative**. Replace them "
               "with text approved by your compliance team.", icon="⚠️")

    items = load_items()
    if not items:
        st.info("The knowledge base is empty.")
        return

    rows = [{"ID": i.id, "Title": i.title, "Type": i.type, "Version": i.version,
             "Status": i.status, "Applicability": i.applicability, "Source": i.source,
             "Effective": i.effective_date, "Usable as evidence": "✅" if is_evidence(i) else "—",
             "Problems": "; ".join(i.problems), "File": i.path} for i in items]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Applicability": st.column_config.ListColumn()})

    with st.expander("Evidence allowlist (config.py)"):
        st.markdown("**Types:** " + ", ".join(config.KB_EVIDENCE_TYPES))
        st.markdown("**Sources:** " + ", ".join(config.KB_ALLOWED_SOURCES))
        st.caption("Only active items with an allowlisted type AND source are retrieved as evidence.")

    with st.expander("🔎 Which KB sections match an interview topic? (keyword search)"):
        from interview.templates import kb_hints, topic_pointer, topics
        topic = st.selectbox("Topic", list(topics()), format_func=lambda t: topics()[t]["label"])
        pointer = topic_pointer(topic)
        st.caption("Interview pointer (MiniLM, pre-computed): "
                   + (f"**{pointer['title']} – {pointer['section']}** (similarity {pointer['similarity']:.2f})"
                      if pointer else f"none above the {config.INTERVIEW_KB_HINT_MIN_SIMILARITY} threshold"))
        for hint in kb_hints(topic):
            st.markdown(f"- **{hint['title']} – {hint['section']}**: {hint['text'][:200]}…")

    labels = [f"{i.id} v{i.version} ({i.status}) – {i.path}" for i in items]
    chosen = st.selectbox("Open an item", range(len(items)), format_func=lambda n: labels[n])
    item = items[chosen]
    with st.container(border=True):
        st.markdown(f"### {item.title}")
        st.caption(f"{item.type} · {item.source} · {item.jurisdiction} · v{item.version} · "
                   f"effective {item.effective_date} · {item.status} · hash {item.content_hash}")
        if item.problems:
            st.error("Front-matter problems: " + "; ".join(item.problems))
        st.markdown(item.body)
