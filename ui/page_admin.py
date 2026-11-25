"""
ui/page_admin.py - Administration (admin role only): audit-log integrity,
data retention, and (Phase 7) user and role management.
"""

import streamlit as st

import audit_log
import config
from auth import rbac, user_store
from security import retention


def render_admin_page() -> None:
    if not rbac.can(st.session_state.get("username"), "manage_users"):
        st.error("Only administrators can open this page.")
        return
    st.subheader("🛡️ Administration")

    with st.container(border=True):
        st.markdown("#### Audit-log integrity")
        st.caption("Every audit record stores the hash of the previous one; this check recomputes the chain.")
        if st.button("🔍 Verify audit log"):
            outcome = audit_log.verify()
            if outcome["ok"]:
                st.success(f"Chain intact: {outcome['chained']} chained records"
                           + (f", {outcome['legacy']} older records without hashes" if outcome["legacy"] else "") + ".")
            else:
                st.error(f"Problem at line {outcome['first_error_line']}: {outcome['error']}")
            st.json(outcome, expanded=False)

    with st.container(border=True):
        st.markdown("#### Data retention")
        st.caption("Removes audit records, interview transcripts and runs (with their saved states) older "
                   "than the retention period. Baselines and change requests are kept.")
        days = st.number_input("Retention period (days)", min_value=1, value=config.RETENTION_DAYS)
        left, right = st.columns(2)
        if left.button("Preview (dry run)"):
            st.json(retention.purge(int(days), dry_run=True))
        confirm = right.checkbox("I understand this permanently deletes old data")
        if right.button("🗑️ Purge now", type="primary", disabled=not confirm):
            st.success("Purged: " + str(retention.purge(int(days), user=st.session_state.get("username"))))

    render_user_management()


def render_user_management() -> None:
    import pandas as pd
    from auth.rbac import ROLE_LABELS
    from storage import migrate
    with st.container(border=True):
        st.markdown("#### Users and roles")
        users = user_store.list_users()
        st.dataframe(pd.DataFrame([{"User": u["username"], "Name": u["name"], "Email": u["email"],
                                    "Roles": [ROLE_LABELS.get(r, r) for r in u["roles"]],
                                    "2FA": "on" if u["mfa"] else "off"} for u in users]),
                     hide_index=True, width="stretch",
                     column_config={"Roles": st.column_config.ListColumn()})
        names = [u["username"] for u in users]
        if not names:
            return
        who = st.selectbox("User", names, key="admin_user")
        current = next(u for u in users if u["username"] == who)
        chosen = st.multiselect("Roles", user_store.ROLES, default=current["roles"],
                                format_func=lambda r: ROLE_LABELS.get(r, r), key=f"admin_roles_{who}")
        left, right = st.columns(2)
        if left.button("Save roles"):
            try:
                user_store.set_roles(who, chosen)
                audit_log.log_event("admin", "roles_changed", user=st.session_state.get("username"),
                                    target=who, before=current["roles"], after=chosen)
                st.success(f"Roles of {who} updated.")
                st.rerun()
            except ValueError as error:
                st.error(str(error))
        if right.button("Reset two-factor authentication", disabled=not current["mfa"],
                        help="For a user who lost their phone."):
            user_store.set_mfa_secret(who, None)
            audit_log.log_event("admin", "mfa_reset", user=st.session_state.get("username"), target=who)
            st.success(f"2FA turned off for {who}.")
            st.rerun()
    with st.container(border=True):
        st.markdown("#### Migration")
        st.caption("Import interview transcripts saved as files before the database existed "
                   "(files are renamed *.migrated, never deleted).")
        if st.button("Import legacy transcripts"):
            st.json(migrate.migrate_transcripts())
