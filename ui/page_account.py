"""
ui/page_account.py - The user's own account: roles and optional TOTP MFA (Phase 7).
"""

import streamlit as st

from auth import mfa, user_store
from auth.rbac import ROLE_LABELS


def render_account_page() -> None:
    username = st.session_state.get("username")
    st.subheader("👤 My account")
    st.markdown("**Roles:** " + ", ".join(ROLE_LABELS.get(r, r) for r in user_store.get_roles(username)))
    st.caption("Roles are assigned by an administrator (Administration page or `python -m auth.manage`).")

    st.markdown("#### Two-factor authentication (TOTP)")
    if user_store.get_mfa_secret(username):
        st.success("Two-factor authentication is ON for your account.")
        code = st.text_input("Enter a current code to turn it off", max_chars=6, key="mfa_off_code")
        if st.button("Turn off two-factor authentication"):
            if mfa.verify(user_store.get_mfa_secret(username), code):
                user_store.set_mfa_secret(username, None)
                st.success("Turned off.")
                st.rerun()
            else:
                st.error("That code is not valid.")
        return

    st.caption("Optional and fully local: scan the QR code with an authenticator app "
               "(e.g. Google or Microsoft Authenticator). No email or SMS is used.")
    secret = st.session_state.setdefault("mfa_pending_secret", mfa.new_secret())
    uri = mfa.provisioning_uri(secret, username)
    left, right = st.columns([1, 2])
    left.image(mfa.qr_png(uri), width=200)
    right.markdown(f"Or enter this key manually: `{secret}`")
    code = right.text_input("Then enter the 6-digit code from the app", max_chars=6, key="mfa_on_code")
    if right.button("Turn on two-factor authentication", type="primary"):
        if mfa.verify(secret, code):
            user_store.set_mfa_secret(username, secret)
            st.session_state.pop("mfa_pending_secret", None)
            st.session_state["mfa_ok"] = True
            st.success("Two-factor authentication is now ON.")
            st.rerun()
        else:
            st.error("That code is not valid - check the time on your phone and try again.")
