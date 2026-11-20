"""Manage requester and approver accounts.

Examples:
  python scripts/manage_users.py add alice requester --name "Alice Requester"
  python scripts/manage_users.py add bob approver --name "Bob Approver"
  python scripts/manage_users.py passwd alice
  python scripts/manage_users.py rename madhukar madhukar.reddy@royalcyber.com --name "Madhukar Reddy"
  python scripts/manage_users.py list
  python scripts/manage_users.py remove alice

Passwords are prompted for (or read from stdin with --password-stdin) and are
never written to the file in plain text.
"""
import argparse
import getpass
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procurement.approval import ApprovalService  # noqa: E402
from procurement.auth import ROLES, AuthError, UserStore  # noqa: E402
from procurement.store import SqliteCaseStore  # noqa: E402


def read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise AuthError("Passwords do not match.")
    return first


def backup(paths: list[Path]) -> Path:
    """Copy data files to data/backups/<timestamp>/ before changing them."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = ROOT / "data" / "backups" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for p in paths:
        if not p.exists():
            continue
        if p.suffix == ".db":  # consistent copy even while the app is running
            with sqlite3.connect(p) as src, sqlite3.connect(dest / p.name) as dst:
                src.backup(dst)
        else:
            shutil.copy2(p, dest / p.name)
    return dest


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
    rn = sub.add_parser("rename", help="change a username and move its requests")
    rn.add_argument("old")
    rn.add_argument("new")
    rn.add_argument("--name", default="", help="new display name")
    parser.add_argument("--cases-db", default=os.getenv("CASES_DB", ROOT / "data" / "cases.db"))
    parser.add_argument("--audit-file", default=os.getenv("AUDIT_PATH", ROOT / "data" / "audit.jsonl"))
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
        elif args.cmd == "rename":
            where = backup([Path(args.users_file), Path(args.cases_db)])
            print(f"Backup written to {where}")
            acct = store.rename_user(args.old, args.new, args.name)
            svc = ApprovalService(args.audit_file, store=SqliteCaseStore(args.cases_db))
            moved = svc.reassign_requester(args.old, acct.username, actor="admin:manage_users")
            print(f"Renamed {args.old} -> {acct.username} ({acct.role}); {moved} request(s) moved")
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
