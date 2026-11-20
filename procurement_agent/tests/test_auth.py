import json
import stat

import pytest

from procurement.auth import LOCKOUT_SECONDS, MAX_FAILED_ATTEMPTS, AuthError, UserStore


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def users(tmp_path, clock):
    s = UserStore(tmp_path / "users.json", clock=clock)
    s.add_user("alice", "alice-pass-123", "requester", "Alice R")
    s.add_user("bob", "bob-pass-123", "approver", "Bob A")
    return s


def test_AU1_valid_login_returns_role(users):
    a = users.authenticate("alice", "alice-pass-123")
    assert (a.username, a.role, a.display_name) == ("alice", "requester", "Alice R")
    assert users.authenticate("BOB ", "bob-pass-123").role == "approver"


@pytest.mark.parametrize("u,p", [("alice", "wrong-pass"), ("alice", ""), ("nobody", "alice-pass-123"),
                                 ("", ""), ("bob", "alice-pass-123")])
def test_AU2_bad_credentials_get_same_generic_error(users, u, p):
    with pytest.raises(AuthError, match="^Invalid username or password.$"):
        users.authenticate(u, p)


def test_AU3_passwords_never_stored_in_plain_text(users):
    raw = users.path.read_text()
    assert "alice-pass-123" not in raw and "bob-pass-123" not in raw
    rec = json.loads(raw)["alice"]
    assert set(rec) == {"role", "display_name", "salt", "hash"}


def test_AU4_same_password_gets_different_hashes(tmp_path):
    s = UserStore(tmp_path / "u.json")
    s.add_user("user1", "same-password", "requester")
    s.add_user("user2", "same-password", "requester")
    d = json.loads(s.path.read_text())
    assert d["user1"]["hash"] != d["user2"]["hash"]


def test_AU5_users_file_is_owner_only(users):
    assert stat.S_IMODE(users.path.stat().st_mode) == 0o600


def test_AU6_lockout_after_repeated_failures(users, clock):
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthError, match="Invalid"):
            users.authenticate("alice", "nope")
    with pytest.raises(AuthError, match="Too many"):
        users.authenticate("alice", "alice-pass-123")   # even the right password
    assert users.authenticate("bob", "bob-pass-123")    # other users unaffected
    clock.t += LOCKOUT_SECONDS + 1
    assert users.authenticate("alice", "alice-pass-123").username == "alice"


def test_AU7_success_resets_failure_count(users):
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(AuthError):
            users.authenticate("alice", "nope")
    users.authenticate("alice", "alice-pass-123")
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(AuthError, match="Invalid"):
            users.authenticate("alice", "nope")


@pytest.mark.parametrize("username,password,role,msg", [
    ("al", "long-enough", "requester", "Username"),
    ("Alice Smith", "long-enough", "requester", "Username"),
    ("carol", "short", "requester", "at least"),
    ("carol", "long-enough", "admin", "Role"),
    ("alice", "long-enough", "requester", "already exists"),
])
def test_AU8_account_validation(users, username, password, role, msg):
    with pytest.raises(AuthError, match=msg):
        users.add_user(username, password, role)


def test_AU9_password_change_and_removal(users):
    users.set_password("alice", "new-pass-456")
    with pytest.raises(AuthError):
        users.authenticate("alice", "alice-pass-123")
    assert users.authenticate("alice", "new-pass-456")
    users.remove_user("alice")
    with pytest.raises(AuthError):
        users.authenticate("alice", "new-pass-456")
    assert [a.username for a in users.list_accounts()] == ["bob"]


def test_AU10_missing_users_file_means_nobody_can_log_in(tmp_path):
    with pytest.raises(AuthError):
        UserStore(tmp_path / "none.json").authenticate("alice", "whatever1")
