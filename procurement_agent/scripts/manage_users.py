"""Manage requester and approver accounts.

Examples:
  python scripts/manage_users.py add alice requester --name "Alice Requester"
  python scripts/manage_users.py add bob approver --name "Bob Approver"
  python scripts/manage_users.py passwd alice
  python scripts/manage_users.py list
  python scripts/manage_users.py remove alice

Passwords are prompted for (or read from stdin with --password-stdin) and are
never written to the file in plain text.
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procurement.auth import ROLES, AuthError, UserStore  # noqa: E402


def read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise AuthError("Passwords do not match.")
    return first


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--users-file", default=os.getenv("USERS_PATH", ROOT / "data" / "users.json"))
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("username")
    add.add_argument("role", choices=ROLES)
    add.add_argument("--name", default="")
    add.add_argument("--password-stdin", action="store_true")
    add.add_argument("--allow-weak-password", action="store_true",
                     help="allow 4-7 character passwords (demo accounts only)")
    pw = sub.add_parser("passwd")
    pw.add_argument("username")
    pw.add_argument("--password-stdin", action="store_true")
    pw.add_argument("--allow-weak-password", action="store_true")
    rm = sub.add_parser("remove")
    rm.add_argument("username")
    sub.add_parser("list")
    args = parser.parse_args()

    store = UserStore(args.users_file)
    try:
        if args.cmd == "add":
            acct = store.add_user(args.username, read_password(args.password_stdin), args.role, args.name,
                                  allow_weak=args.allow_weak_password)
            print(f"Added {acct.username} ({acct.role})")
        elif args.cmd == "passwd":
            store.set_password(args.username, read_password(args.password_stdin), allow_weak=args.allow_weak_password)
            print(f"Password changed for {args.username}")
        elif args.cmd == "remove":
            store.remove_user(args.username)
            print(f"Removed {args.username}")
        else:
            for a in store.list_accounts():
                print(f"{a.username:20} {a.role:10} {a.display_name}")
    except AuthError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
