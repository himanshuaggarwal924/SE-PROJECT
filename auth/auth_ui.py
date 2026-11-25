"""
auth/auth_ui.py - The login, sign-up and local password-reset screens.

  * Login / logout / session cookie: handled by streamlit-authenticator.
  * Sign-up and "forgot password": our own forms, using auth/user_store.py.

The rest of the app only calls two functions from here:
    authenticator = require_login()      # stops the page until logged in
    show_account_box(authenticator)      # "signed in as ..." + Log out button
"""

import streamlit as st
import streamlit_authenticator as stauth

import audit_log
from auth import user_store

MAX_LOGIN_ATTEMPTS = 5
MAX_RESET_ATTEMPTS = 5


def _create_authenticator() -> stauth.Authenticate:
    """Build the authenticator from the current users.yaml (re-read on every
    page load, so new sign-ups and password resets take effect immediately)."""
    data = user_store.load_config()
    cookie = data["cookie"]
    return stauth.Authenticate(
        data["credentials"], cookie["name"], cookie["key"], cookie["expiry_days"],
        auto_hash=False,  # our passwords are already bcrypt-hashed
    )


def require_login() -> stauth.Authenticate:
    """Return the authenticator if the user is logged in. Otherwise show the
    Log in / Sign up / Forgot password tabs and stop the page there."""
    authenticator = _create_authenticator()
    if st.session_state.get("authentication_status"):
        _require_mfa(authenticator)          # stops here until the TOTP code is entered
        return authenticator  # already logged in during this session

    login_tab, signup_tab, reset_tab = st.tabs(["🔑 Log in", "📝 Sign up", "❓ Forgot password"])
    with login_tab:
        # This also checks the login cookie, so a returning user skips the form.
        authenticator.login(location="main", max_login_attempts=MAX_LOGIN_ATTEMPTS,
                            fields={"Form name": "Log in to your account", "Login": "Log in"})
        status = st.session_state.get("authentication_status")
        if status:
            st.rerun()  # logged in: reload the page to show the app
        elif status is False:
            st.error("Incorrect username or password.")

    with signup_tab:
        _signup_form()
    with reset_tab:
        _reset_form()

    st.stop()  # nothing below require_login() runs until the user logs in


def _require_mfa(authenticator: stauth.Authenticate) -> None:
    """Second step for users who turned on TOTP (Phase 7)."""
    from auth import mfa
    username = st.session_state.get("username")
    secret = user_store.get_mfa_secret(username)
    if not secret or st.session_state.get("mfa_ok"):
        return
    attempts = st.session_state.get("mfa_attempts", 0)
    st.subheader("🔐 Two-factor authentication")
    if attempts >= MAX_LOGIN_ATTEMPTS:
        st.error("Too many wrong codes. Log out and try again.")
    else:
        with st.form("mfa"):
            code = st.text_input("6-digit code from your authenticator app", max_chars=6)
            if st.form_submit_button("Verify", type="primary"):
                if mfa.verify(secret, code):
                    st.session_state["mfa_ok"] = True
                    audit_log.log_event("auth", "mfa_verified", user=username)
                    st.rerun()
                st.session_state["mfa_attempts"] = attempts + 1
                audit_log.log_event("auth", "mfa_failed", user=username)
                st.error("That code is not valid.")
    authenticator.logout("Log out", location="main", callback=_clear_user_data)
    st.stop()


def show_account_box(authenticator: stauth.Authenticate) -> None:
    """Sidebar box with the user's name and a Log out button."""
    st.sidebar.markdown(f"👤 **{st.session_state.get('name')}**  \n"
                        f"`{st.session_state.get('username')}`")
    authenticator.logout("Log out", location="sidebar", callback=_clear_user_data)
    if not st.session_state.get("authentication_status"):
        st.rerun()  # just logged out: back to the login screen


def _clear_user_data(_details=None) -> None:
    """Forget the previous user's results when they log out."""
    for key in ("result", "error", "run_request", "running", "interview",
                "selected_transcripts", "send_transcripts", "_pages", "resume_request",
                "review_drafts", "artefacts", "mfa_ok", "mfa_attempts",
                "mfa_pending_secret", "project"):
        st.session_state.pop(key, None)


def _signup_form() -> None:
    with st.form("signup", clear_on_submit=False):
        st.subheader("Create an account")
        name = st.text_input("Full name", key="signup_name")
        username = st.text_input("Username", key="signup_username",
                                 help="3-20 characters: letters, numbers or _")
        email = st.text_input("Email", key="signup_email", help="Used only as an identifier - no emails are sent.")
        password = st.text_input("Password", type="password", key="signup_password",
                                 help="At least 8 characters, with a letter and a number.")
        confirm = st.text_input("Repeat password", type="password", key="signup_confirm")
        st.markdown("**Security question** - used to reset your password offline.")
        question = st.selectbox("Question", user_store.SECURITY_QUESTIONS, key="signup_question")
        answer = st.text_input("Answer", type="password", key="signup_answer",
                               help="Not case-sensitive. Stored only as a hash.")
        submitted = st.form_submit_button("Sign up", type="primary")

    if submitted:
        if password != confirm:
            st.error("The two passwords do not match.")
            return
        try:
            user_store.register_user(username, name, email, password, question, answer)
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Account created! You can now log in on the **Log in** tab.")


def _reset_form() -> None:
    st.subheader("Local password reset")
    st.info("This app runs offline, so no reset email can be sent. Instead, answer the "
            "security question you chose when you signed up.", icon="🔒")

    attempts = st.session_state.get("reset_attempts", 0)
    if attempts >= MAX_RESET_ATTEMPTS:
        st.error("Too many wrong answers. Restart the app to try again.")
        return

    # Step 1: which account?
    username = st.text_input("Username", key="reset_username")
    if not username:
        return
    question = user_store.get_security_question(username)
    if question is None:
        st.warning("No account with that username.")
        return

    # Step 2: answer the question and choose a new password.
    with st.form("reset", clear_on_submit=True):
        st.markdown(f"**{question}**")
        answer = st.text_input("Your answer", type="password", key="reset_answer")
        new_password = st.text_input("New password", type="password", key="reset_new_password",
                                     help="At least 8 characters, with a letter and a number.")
        confirm = st.text_input("Repeat new password", type="password", key="reset_confirm")
        submitted = st.form_submit_button("Reset password", type="primary")

    if submitted:
        if new_password != confirm:
            st.error("The two passwords do not match.")
            return
        try:
            user_store.reset_password(username, answer, new_password)
        except ValueError as error:
            st.session_state["reset_attempts"] = attempts + 1
            st.error(str(error))
        else:
            st.session_state["reset_attempts"] = 0
            st.success("Password changed. You can now log in with your new password.")
