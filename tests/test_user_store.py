import pytest
import yaml

import config
from auth import user_store

QUESTION = user_store.SECURITY_QUESTIONS[0]


def register(username="alice", email="alice@example.com", password="secret123",
             answer="Green Valley"):
    user_store.register_user(username, "Alice A", email, password, QUESTION, answer)


def stored_users():
    return yaml.safe_load(config.USERS_FILE.read_text(encoding="utf-8"))["credentials"]["usernames"]


def test_users_file_created_with_cookie_secret():
    data = user_store.load_config()
    assert len(data["cookie"]["key"]) == 64
    assert data["credentials"]["usernames"] == {}


def test_register_stores_only_hashes():
    register()
    user = stored_users()["alice"]
    assert user["password"].startswith("$2")
    assert user["password"] != "secret123"
    assert "Green Valley" not in config.USERS_FILE.read_text(encoding="utf-8")
    assert user["security_answer_hash"].startswith("$2")


def test_username_and_email_are_normalised_and_unique():
    register(username="Alice", email="Alice@Example.com")
    assert "alice" in stored_users()
    with pytest.raises(ValueError, match="username is already taken"):
        register(username="ALICE", email="other@example.com")
    with pytest.raises(ValueError, match="email already exists"):
        register(username="bob", email="ALICE@example.com")


@pytest.mark.parametrize("kwargs, message", [
    ({"username": "ab"}, "Username"),
    ({"username": "bad name!"}, "Username"),
    ({"email": "not-an-email"}, "valid email"),
    ({"password": "short1"}, "at least 8"),
    ({"password": "onlyletters"}, "letter and one number"),
    ({"password": "12345678"}, "letter and one number"),
    ({"answer": " "}, "answer"),
])
def test_validation_errors(kwargs, message):
    with pytest.raises(ValueError, match=message):
        register(**kwargs)


def test_invalid_security_question():
    with pytest.raises(ValueError, match="security question"):
        user_store.register_user("carol", "C", "c@example.com", "secret123", "Favourite colour?", "x y")


def test_reset_with_correct_answer_ignores_case_and_spaces():
    register()
    old_hash = stored_users()["alice"]["password"]
    user_store.reset_password("Alice", "  green   VALLEY ", "newpass99")
    new_hash = stored_users()["alice"]["password"]
    assert new_hash != old_hash
    from streamlit_authenticator import Hasher
    assert Hasher.check_pw("newpass99", new_hash)


def test_reset_with_wrong_answer_or_unknown_user_gives_same_error():
    register()
    with pytest.raises(ValueError, match="Username or security answer is incorrect"):
        user_store.reset_password("alice", "wrong", "newpass99")
    with pytest.raises(ValueError, match="Username or security answer is incorrect"):
        user_store.reset_password("nobody", "wrong", "newpass99")


def test_reset_rejects_weak_new_password():
    register()
    with pytest.raises(ValueError, match="at least 8"):
        user_store.reset_password("alice", "Green Valley", "abc1")


def test_get_security_question():
    register()
    assert user_store.get_security_question(" ALICE ") == QUESTION
    assert user_store.get_security_question("nobody") is None


# ------------------------------------------------------------------ roles --
def test_existing_accounts_default_to_analyst():
    register()
    assert user_store.get_roles("alice") == ["analyst"]
    assert user_store.get_roles("nobody") == []
    assert user_store.get_roles(None) == []


def test_set_roles_validates():
    register()
    user_store.set_roles("ALICE", ["admin", "analyst", "admin"])
    assert user_store.get_roles("alice") == ["admin", "analyst"]
    assert user_store.has_role("alice", "admin")
    with pytest.raises(ValueError, match="Unknown role"):
        user_store.set_roles("alice", ["superuser"])
    with pytest.raises(ValueError, match="at least one"):
        user_store.set_roles("alice", [])
    with pytest.raises(ValueError, match="No account"):
        user_store.set_roles("nobody", ["admin"])


def test_manage_cli(capsys):
    from auth import manage
    register()
    assert manage.main(["set-roles", "alice", "admin"]) == 0
    assert manage.main(["list"]) == 0
    assert "alice" in capsys.readouterr().out
    assert manage.main(["set-roles", "alice", "wizard"]) == 1
    assert manage.main([]) == 1
