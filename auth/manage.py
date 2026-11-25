"""
auth/manage.py - Account administration from the terminal.

    python -m auth.manage list                       # users and their roles
    python -m auth.manage set-roles alice admin analyst

There is deliberately no "first user becomes admin" shortcut: an admin is
always appointed explicitly by someone with access to this machine.
"""

import sys

from auth import user_store


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("list", "set-roles"):
        print(__doc__)
        return 1
    if argv[0] == "list":
        users = user_store.load_config()["credentials"]["usernames"]
        for name in users:
            print(f"{name:20} {', '.join(user_store.get_roles(name))}")
        return 0
    if len(argv) < 3:
        print("Usage: python -m auth.manage set-roles <username> <role> [<role> ...]")
        return 1
    try:
        user_store.set_roles(argv[1], argv[2:])
    except ValueError as error:
        print(f"Error: {error}")
        return 1
    print(f"{argv[1]}: {', '.join(user_store.get_roles(argv[1]))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
