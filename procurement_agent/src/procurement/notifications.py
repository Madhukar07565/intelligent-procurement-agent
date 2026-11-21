"""Approver alerts when a requester submits a purchase request.

Two channels:
- InAppNotifier: one stored alert per approver (except the submitter), shown
  on sign-in and while signed in. Persists in SQLite next to the cases.
- SnsEmailNotifier: publishes to an Amazon SNS topic that approvers subscribe
  to by email, so they are alerted before they sign in. Enabled only when
  APPROVAL_SNS_TOPIC_ARN is set.

Alerts never include secrets, prices are the only commercial data, and all
data in this project is synthetic.
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Protocol

if TYPE_CHECKING:
    from .approval import Case
    from .auth import UserStore

SUBMITTED = "submitted"
SNS_SUBJECT_MAX = 100


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Alert:
    alert_id: str
    recipient: str
    case_id: str
    kind: str
    message: str
    created_at: str
    read_at: str | None = None


def summarize(case: "Case") -> tuple[str, str]:
    """(subject, one-line summary) for a newly submitted case."""
    req = case.recommendation.request
    best = case.recommendation.comparison.recommended.quote
    if case.build_id:
        items = ", ".join(f"{r.request.quantity} x {r.request.product}" for r in case.lines)
        name = case.title or "multi-product order"
        n = len(case.lines)
        subject = f"Approval needed: {case.supplier}, {n} item{'s' if n != 1 else ''} for {name} ({case.case_id})"
        summary = (f"{case.submitted_by} requested {items} from {case.supplier} by {req.required_date.isoformat()}, "
                   f"total {case.total():,.2f} {best.currency}. Request {case.build_part} of {case.build_parts} "
                   f"in this order (one approval request and one purchase order per supplier).")
        return subject, summary
    subject = f"Approval needed: {req.quantity} x {req.product} ({case.case_id})"
    summary = (f"{case.submitted_by} requested {req.quantity} x {req.product} by {req.required_date.isoformat()}. "
               f"Recommended: {best.supplier}, {best.total_price:,.2f} {best.currency}.")
    return subject, summary


class Notifier(Protocol):
    name: str

    def case_submitted(self, case: "Case") -> int:
        """Alert approvers about a new case. Returns how many alerts were sent."""
        ...


# ---------------------------------------------------------------- in-app
class AlertStore:
    def __init__(self, path: str | Path = ":memory:", clock: Callable[[], datetime] = _utcnow):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._clock = clock
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id   TEXT PRIMARY KEY,
                    recipient  TEXT NOT NULL,
                    case_id    TEXT NOT NULL,
                    kind       TEXT NOT NULL,
                    message    TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    read_at    TEXT,
                    UNIQUE (recipient, case_id, kind)
                )""")
            self._conn.execute("CREATE INDEX IF NOT EXISTS ix_alerts_unread ON alerts(recipient, read_at)")

    def add(self, recipient: str, case_id: str, kind: str, message: str) -> bool:
        """Store an alert. Returns False if this recipient already has it (no duplicates)."""
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO alerts(alert_id, recipient, case_id, kind, message, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (uuid.uuid4().hex, recipient, case_id, kind, message, self._clock().isoformat()),
            )
            return cur.rowcount == 1

    def _rows(self, sql: str, args: tuple) -> list[Alert]:
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [Alert(*r) for r in rows]

    def unread(self, recipient: str) -> list[Alert]:
        return self._rows("SELECT alert_id, recipient, case_id, kind, message, created_at, read_at FROM alerts "
                          "WHERE recipient = ? AND read_at IS NULL ORDER BY created_at, rowid", (recipient,))

    def recent(self, recipient: str, limit: int = 20) -> list[Alert]:
        return self._rows("SELECT alert_id, recipient, case_id, kind, message, created_at, read_at FROM alerts "
                          "WHERE recipient = ? ORDER BY created_at DESC, rowid DESC LIMIT ?", (recipient, limit))

    def unread_count(self, recipient: str) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM alerts WHERE recipient = ? AND read_at IS NULL",
                                      (recipient,)).fetchone()[0]

    def mark_read(self, recipient: str, case_id: str | None = None) -> int:
        """Mark one case's alerts (or all) as read for this recipient only."""
        sql = "UPDATE alerts SET read_at = ? WHERE recipient = ? AND read_at IS NULL"
        args: list = [self._clock().isoformat(), recipient]
        if case_id is not None:
            sql += " AND case_id = ?"
            args.append(case_id)
        with self._lock:
            return self._conn.execute(sql, args).rowcount


class InAppNotifier:
    name = "in-app"

    def __init__(self, alerts: AlertStore, users: "UserStore"):
        self._alerts = alerts
        self._users = users

    def case_submitted(self, case: "Case") -> int:
        from .approval import APPROVER  # local import avoids a cycle

        _, summary = summarize(case)
        sent = 0
        for account in self._users.list_accounts():
            # The submitter can never approve their own case, so do not alert them.
            if account.role == APPROVER and account.username != case.submitted_by:
                sent += self._alerts.add(account.username, case.case_id, SUBMITTED, summary)
        return sent


# ---------------------------------------------------------------- email via SNS
class SnsEmailNotifier:
    """Publishes one message per case to an SNS topic; approvers subscribe by email."""

    name = "email"

    def __init__(self, topic_arn: str, app_url: str = "", client=None):
        if not topic_arn.startswith("arn:aws:sns:"):
            raise ValueError("topic_arn must be an SNS topic ARN")
        self.topic_arn = topic_arn
        self.app_url = app_url
        if client is None:
            import boto3
            client = boto3.client("sns", region_name=topic_arn.split(":")[3])
        self._client = client

    def case_submitted(self, case: "Case") -> int:
        subject, summary = summarize(case)
        subject = " ".join(subject.split())[:SNS_SUBJECT_MAX]  # SNS: one line, at most 100 chars
        req = case.recommendation.request
        lines = [
            "A purchase request is waiting for your approval.",
            "",
            f"Case:         {case.case_id}",
            f"Requested by: {case.submitted_by}",
            f"Item:         {req.quantity} x {req.product}",
            f"Needed by:    {req.required_date.isoformat()}",
            "",
            summary,
            "",
        ]
        if self.app_url:
            lines.append(f"Sign in to review and approve: {self.app_url}")
        lines.append("No purchase is made until an approver approves it in the app.")
        self._client.publish(TopicArn=self.topic_arn, Subject=subject, Message="\n".join(lines))
        return 1


class CompositeNotifier:
    """Sends on every channel. A failing channel does not stop the others."""

    name = "all"

    def __init__(self, notifiers: list[Notifier]):
        self.notifiers = list(notifiers)
        self.last_errors: dict[str, str] = {}

    def case_submitted(self, case: "Case") -> int:
        sent, self.last_errors = 0, {}
        for n in self.notifiers:
            try:
                sent += n.case_submitted(case)
            except Exception as exc:  # network, permissions, throttling
                self.last_errors[n.name] = f"{type(exc).__name__}: {exc}"
        if self.last_errors and sent == 0:
            raise NotificationError("; ".join(f"{k}: {v}" for k, v in self.last_errors.items()))
        return sent


class NotificationError(RuntimeError):
    pass
