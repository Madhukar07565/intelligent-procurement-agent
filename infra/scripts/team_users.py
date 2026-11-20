"""Create the team test logins and the CloudFront origin secret.

Writes, under infra/.deploy/ (git-ignored, owner-only):
  users.json             password hashes, uploaded to Secrets Manager by the deploy steps
  team-credentials.txt   plain usernames and passwords, to share privately one person at a time
  origin-secret          random value CloudFront sends to the load balancer

Each teammate gets a requester login (their email) and an approver login (email with +approver).
Run again with --reset to issue new passwords.
"""
import argparse
import os
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE.parent / "procurement_agent" / "src"))
from procurement.auth import UserStore  # noqa: E402

TEAM = [  # (email, display name)
    ("arsalan.gill@royalcyber.com", "Arsalan Gill"),
    ("rhee.k@royalcyber.com", "Rhee K"),
    ("mas@royalcyber.com", "Mas"),
]
OWNERS = [  # existing demo accounts, given strong passwords because the link is public
    ("madhukar.reddy@royalcyber.com", "requester", "Madhukar Reddy"),
    ("mreddy@dwyeromega.com", "approver", "M Reddy"),
]


def approver_login(email: str) -> str:
    local, domain = email.split("@", 1)
    return f"{local}+approver@{domain}"


def password() -> str:
    # 4 groups of 4 from an unambiguous alphabet, about 82 bits; easy to read out.
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="replace existing logins and passwords")
    args = ap.parse_args()
    out = HERE / ".deploy"
    out.mkdir(mode=0o700, exist_ok=True)
    users_file, creds_file, origin_file = out / "users.json", out / "team-credentials.txt", out / "origin-secret"

    if not origin_file.exists():
        fd = os.open(origin_file, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))
    if users_file.exists() and not args.reset:
        print(f"{users_file} exists; keeping current logins (use --reset for new passwords)")
        return 0
    users_file.unlink(missing_ok=True)

    store = UserStore(users_file)
    rows = []
    for email, name in TEAM:
        for login, role, label in ((email, "requester", name), (approver_login(email), "approver", f"{name} (approver)")):
            pw = password()
            store.add_user(login, pw, role, label)
            rows.append((name, role, login, pw))
    for login, role, name in OWNERS:
        pw = password()
        store.add_user(login, pw, role, name)
        rows.append((name, role, login, pw))

    fd = os.open(creds_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("Procurement Agent team test logins. Share each person's lines privately; do not post in group chat.\n\n")
        for name, role, login, pw in rows:
            f.write(f"{name:16} {role:10} {login:44} {pw}\n")
    print(f"Created {len(rows)} logins -> {users_file} (hashes) and {creds_file} (passwords)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
