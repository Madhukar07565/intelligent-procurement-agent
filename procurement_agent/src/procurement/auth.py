"""User accounts and login for requesters and approvers.

Users live in a JSON file (data/users.json, not committed). Passwords are stored
only as salted scrypt hashes. Manage accounts with scripts/manage_users.py.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .approval import APPROVER, REQUESTER, User

ROLES = (REQUESTER, APPROVER)
USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
MIN_PASSWORD_LENGTH = 8
MIN_WEAK_PASSWORD_LENGTH = 4  # only with allow_weak=True (demo accounts)
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 300
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


class AuthError(Exception):
    """Login or account problem. The message is safe to show to the user."""


@dataclass(frozen=True)
class Account:
    username: str
    role: str
    display_name: str

    def as_user(self) -> User:
        return User(self.username, self.role)


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return salt.hex(), digest.hex()


def _verify(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, candidate = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(candidate, hash_hex)


# A fixed dummy hash so unknown usernames take as long as wrong passwords.
_DUMMY_SALT, _DUMMY_HASH = hash_password("dummy-password-not-used", b"\0" * 16)


class UserStore:
    def __init__(self, path: str | Path, clock: Callable[[], float] = time.monotonic):
        self.path = Path(path)
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    # ---- file access ----------------------------------------------------
    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, users: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(users, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)  # atomic on POSIX

    # ---- account management ----------------------------------------------
    @staticmethod
    def _check_password(password: str, allow_weak: bool) -> None:
        minimum = MIN_WEAK_PASSWORD_LENGTH if allow_weak else MIN_PASSWORD_LENGTH
        if len(password) < minimum:
            raise AuthError(f"Password must be at least {minimum} characters.")

    def add_user(self, username: str, password: str, role: str, display_name: str = "",
                 allow_weak: bool = False) -> Account:
        username = username.strip().lower()
        if not USERNAME_RE.match(username):
            raise AuthError("Username must be 3-32 characters: lowercase letters, digits, '.', '_' or '-'.")
        if role not in ROLES:
            raise AuthError(f"Role must be one of: {', '.join(ROLES)}.")
        self._check_password(password, allow_weak)
        with self._lock:
            users = self._load()
            if username in users:
                raise AuthError(f"User {username} already exists.")
            salt, digest = hash_password(password)
            users[username] = {"role": role, "display_name": display_name.strip() or username,
                               "salt": salt, "hash": digest}
            self._save(users)
        return Account(username, role, display_name.strip() or username)

    def set_password(self, username: str, password: str, allow_weak: bool = False) -> None:
        self._check_password(password, allow_weak)
        with self._lock:
            users = self._load()
            if username not in users:
                raise AuthError(f"No such user: {username}")
            users[username]["salt"], users[username]["hash"] = hash_password(password)
            self._save(users)
            self._failures.pop(username, None)

    def remove_user(self, username: str) -> None:
        with self._lock:
            users = self._load()
            if users.pop(username, None) is None:
                raise AuthError(f"No such user: {username}")
            self._save(users)

    def list_accounts(self) -> list[Account]:
        return [Account(u, d["role"], d.get("display_name", u)) for u, d in sorted(self._load().items())]

    # ---- login ------------------------------------------------------------
    def _recent_failures(self, username: str) -> list[float]:
        cutoff = self._clock() - LOCKOUT_SECONDS
        recent = [t for t in self._failures.get(username, []) if t > cutoff]
        self._failures[username] = recent
        return recent

    def authenticate(self, username: str, password: str) -> Account:
        """Return the account, or raise AuthError with a generic message."""
        username = (username or "").strip().lower()
        with self._lock:
            if len(self._recent_failures(username)) >= MAX_FAILED_ATTEMPTS:
                raise AuthError("Too many failed attempts. Try again in a few minutes.")
            record = self._load().get(username)
        if record is None:
            _verify(password or "", _DUMMY_SALT, _DUMMY_HASH)  # equalize timing
            ok = False
        else:
            ok = _verify(password or "", record["salt"], record["hash"])
        with self._lock:
            if not ok:
                self._failures.setdefault(username, []).append(self._clock())
                raise AuthError("Invalid username or password.")
            self._failures.pop(username, None)
        return Account(username, record["role"], record.get("display_name", username))
