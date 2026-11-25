"""
auth/user_store.py - Local user accounts, stored in auth/users.yaml.

  * Passwords and security answers are stored ONLY as bcrypt hashes.
  * Nothing is sent anywhere - there is no email. "Forgot password" works
    offline with a security question chosen at sign-up.

This module has no Streamlit code, so the account logic can be tested and
reused on its own. The login screens live in auth/auth_ui.py.
"""

import re
import secrets
import threading

import yaml
from streamlit_authenticator import Hasher

import config

SECURITY_QUESTIONS = [
    "What was the name of your first school?",
    "In which city were you born?",
    "What was the name of your first pet?",
    "What is your favourite book?",
    "What was your childhood nickname?",
]

# Roles (Phase 7 enforces them everywhere). Accounts without a "roles"
# entry - including accounts created before roles existed - are analysts.
ROLES = ["analyst", "compliance_officer", "security_officer", "project_manager",
         "architect", "admin"]
DEFAULT_ROLES = ["analyst"]

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,20}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_file_lock = threading.Lock()  # two sign-ups at once must not overwrite each other


# --------------------------------------------------------------- the file --
def load_config() -> dict:
    """Read users.yaml, creating it (with a random cookie secret) if missing."""
    if not config.USERS_FILE.exists():
        save_config({
            "cookie": {
                "name": "finreq_auth",
                "key": secrets.token_hex(32),  # signs the login cookie
                "expiry_days": 1,
            },
            "credentials": {"usernames": {}},
        })
    with open(config.USERS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(data: dict) -> None:
    """Write users.yaml safely (write a temp file, then swap it in)."""
    config.USERS_FILE.parent.mkdir(exist_ok=True)
    temp_file = config.USERS_FILE.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    temp_file.replace(config.USERS_FILE)


# ------------------------------------------------------------- validation --
def _normalise_answer(answer: str) -> str:
    """'  New  Delhi ' and 'new delhi' should count as the same answer."""
    return " ".join(answer.lower().split())


def check_password_strength(password: str) -> None:
    """Raise ValueError if the password is too weak."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("Password must contain at least one letter and one number.")


# ---------------------------------------------------------------- actions --
def register_user(username: str, name: str, email: str, password: str,
                  security_question: str, security_answer: str) -> None:
    """Create a new account. Raises ValueError with a friendly message if
    anything is invalid or the username/email is already taken."""
    username = username.strip().lower()
    email = email.strip().lower()
    if not USERNAME_PATTERN.match(username):
        raise ValueError("Username must be 3-20 characters: letters, numbers or _.")
    if not name.strip():
        raise ValueError("Please enter your name.")
    if not EMAIL_PATTERN.match(email):
        raise ValueError("Please enter a valid email address.")
    check_password_strength(password)
    if security_question not in SECURITY_QUESTIONS:
        raise ValueError("Please choose a security question.")
    if len(_normalise_answer(security_answer)) < 2:
        raise ValueError("Please enter an answer to the security question.")

    with _file_lock:
        data = load_config()
        users = data["credentials"]["usernames"]
        if username in users:
            raise ValueError("That username is already taken.")
        if any(u.get("email") == email for u in users.values()):
            raise ValueError("An account with that email already exists.")

        users[username] = {
            "name": name.strip(),
            "email": email,
            "password": Hasher.hash(password),
            "security_question": security_question,
            "security_answer_hash": Hasher.hash(_normalise_answer(security_answer)),
        }
        save_config(data)


def get_security_question(username: str) -> str | None:
    """The user's security question, or None if the user doesn't exist."""
    user = load_config()["credentials"]["usernames"].get(username.strip().lower())
    return user.get("security_question") if user else None


def reset_password(username: str, security_answer: str, new_password: str) -> None:
    """Set a new password if the security answer is correct (local reset)."""
    username = username.strip().lower()
    check_password_strength(new_password)
    with _file_lock:
        data = load_config()
        user = data["credentials"]["usernames"].get(username)
        if user is None or not Hasher.check_pw(_normalise_answer(security_answer),
                                               user["security_answer_hash"]):
            # Same message either way, so nobody can probe which usernames exist.
            raise ValueError("Username or security answer is incorrect.")
        user["password"] = Hasher.hash(new_password)
        save_config(data)


# ------------------------------------------------------------------ roles --
def get_roles(username: str | None) -> list[str]:
    """The user's roles (["analyst"] if none are set, [] if the user doesn't exist)."""
    if not username:
        return []
    user = load_config()["credentials"]["usernames"].get(username.strip().lower())
    if user is None:
        return []
    return list(user.get("roles") or DEFAULT_ROLES)


def has_role(username: str | None, role: str) -> bool:
    return role in get_roles(username)


def set_roles(username: str, roles: list[str]) -> None:
    """Replace a user's roles. Raises ValueError for unknown users or roles."""
    unknown = [r for r in roles if r not in ROLES]
    if unknown:
        raise ValueError(f"Unknown role(s): {', '.join(unknown)}. Valid: {', '.join(ROLES)}")
    if not roles:
        raise ValueError("A user needs at least one role.")
    with _file_lock:
        data = load_config()
        user = data["credentials"]["usernames"].get(username.strip().lower())
        if user is None:
            raise ValueError(f"No account named '{username}'.")
        user["roles"] = list(dict.fromkeys(roles))
        save_config(data)


# -------------------------------------------------------------- MFA (TOTP) --
def get_mfa_secret(username: str | None) -> str | None:
    if not username:
        return None
    user = load_config()["credentials"]["usernames"].get(username.strip().lower())
    from security.crypto import decrypt_text
    return decrypt_text((user or {}).get("mfa_secret")) or None


def set_mfa_secret(username: str, secret: str | None) -> None:
    """Turn TOTP on (secret) or off (None) for a user."""
    with _file_lock:
        data = load_config()
        user = data["credentials"]["usernames"].get(username.strip().lower())
        if user is None:
            raise ValueError(f"No account named '{username}'.")
        if secret:
            from security.crypto import encrypt_text
            user["mfa_secret"] = encrypt_text(secret)       # encrypted at rest
        else:
            user.pop("mfa_secret", None)
        save_config(data)


def list_users() -> list[dict]:
    """[{username, name, email, roles, mfa}] - for the admin page (no hashes)."""
    users = load_config()["credentials"]["usernames"]
    return [{"username": name, "name": u.get("name", ""), "email": u.get("email", ""),
             "roles": list(u.get("roles") or DEFAULT_ROLES), "mfa": bool(u.get("mfa_secret"))}
            for name, u in users.items()]
