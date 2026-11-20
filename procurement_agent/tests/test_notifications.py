"""Approver alerts on new purchase requests."""
import json
from datetime import date, datetime, timezone

import pytest

from procurement.agent import validate_fields
from procurement.approval import ApprovalError, ApprovalService, User
from procurement.auth import UserStore
from procurement.comparison import compare
from procurement.models import Recommendation
from procurement.notifications import (SNS_SUBJECT_MAX, AlertStore, CompositeNotifier, InAppNotifier,
                                       SnsEmailNotifier)
from procurement.store import SqliteCaseStore

TODAY = date(2026, 11, 20)
NOW = datetime(2026, 11, 20, 9, 30, tzinfo=timezone.utc)
TOPIC = "arn:aws:sns:us-east-1:123456789012:procurement-approval-alerts"


@pytest.fixture
def users(tmp_path):
    u = UserStore(tmp_path / "users.json")
    u.add_user("madhukar", "pass-1234", "requester", "Madhukar")
    u.add_user("carol", "pass-1234", "requester", "Carol")
    u.add_user("mass", "pass-1234", "approver", "Mass")
    u.add_user("dave", "pass-1234", "approver", "Dave")
    return u


@pytest.fixture
def alerts(tmp_path):
    return AlertStore(tmp_path / "cases.db", clock=lambda: NOW)


def rec_for(repo, product="laptop", qty=50):
    quotes, ex = repo.find(product, qty, TODAY)
    req = validate_fields(product, qty, date(2026, 12, 15), TODAY).request
    return Recommendation(req, compare(quotes, req.required_date), "e", ex)


def service(tmp_path, notifier):
    return ApprovalService(tmp_path / "audit.jsonl", clock=lambda: NOW, notifier=notifier,
                           store=SqliteCaseStore(tmp_path / "cases.db"))


def audit(tmp_path):
    return [json.loads(x) for x in (tmp_path / "audit.jsonl").read_text().splitlines()]


class FakeSns:
    def __init__(self, fail=False):
        self.fail = fail
        self.published = []

    def publish(self, **kw):
        if self.fail:
            raise ConnectionError("network down")
        self.published.append(kw)
        return {"MessageId": "m1"}


# ---------------------------------------------------------------- in-app
def test_N1_every_approver_alerted_not_requesters(tmp_path, repo, users, alerts):
    svc = service(tmp_path, InAppNotifier(alerts, users))
    cid = svc.submit(rec_for(repo), "madhukar")
    for approver in ("mass", "dave"):
        [a] = alerts.unread(approver)
        assert a.case_id == cid and "madhukar requested 50 x laptop by 2026-12-15" in a.message
        assert "Acme Supplies, 47,500.00 USD" in a.message
    assert alerts.unread("madhukar") == [] and alerts.unread("carol") == []


def test_N2_approver_who_submits_is_not_alerted_about_own_case(tmp_path, repo, users, alerts):
    svc = service(tmp_path, InAppNotifier(alerts, users))
    svc.submit(rec_for(repo), "mass")
    assert alerts.unread_count("mass") == 0 and alerts.unread_count("dave") == 1


def test_N3_alerts_survive_restart(tmp_path, repo, users, alerts):
    service(tmp_path, InAppNotifier(alerts, users)).submit(rec_for(repo), "madhukar")
    assert AlertStore(tmp_path / "cases.db").unread_count("mass") == 1


def test_N4_mark_read_is_per_user_and_per_case(tmp_path, repo, users, alerts):
    svc = service(tmp_path, InAppNotifier(alerts, users))
    c1 = svc.submit(rec_for(repo), "madhukar")
    svc.submit(rec_for(repo, "monitor", 5), "carol")
    assert alerts.mark_read("mass", c1) == 1
    assert [a.case_id for a in alerts.unread("mass")] != [c1] and alerts.unread_count("mass") == 1
    assert alerts.unread_count("dave") == 2           # other approver unaffected
    alerts.mark_read("mass")
    assert alerts.unread_count("mass") == 0 and len(alerts.recent("mass")) == 2


def test_N5_no_duplicate_alert_for_same_case(tmp_path, repo, users, alerts):
    svc = service(tmp_path, InAppNotifier(alerts, users))
    cid = svc.submit(rec_for(repo), "madhukar")
    InAppNotifier(alerts, users).case_submitted(svc.get(cid))  # e.g. a retry
    assert alerts.unread_count("mass") == 1


def test_N6_refused_submission_sends_no_alert(tmp_path, repo, users, alerts):
    svc = service(tmp_path, InAppNotifier(alerts, users))
    req = validate_fields("laptop", 1, date(2026, 12, 1), TODAY).request
    with pytest.raises(ApprovalError):
        svc.submit(Recommendation(req, compare([], req.required_date), "none"), "madhukar")
    assert alerts.unread_count("mass") == 0


def test_N7_alert_is_audited(tmp_path, repo, users, alerts):
    svc = service(tmp_path, InAppNotifier(alerts, users))
    svc.submit(rec_for(repo), "madhukar")
    last = audit(tmp_path)[-1]
    assert last["event"] == "approvers_notified" and last["details"]["alerts_sent"] == 2


# ---------------------------------------------------------------- email
def test_N8_email_sent_with_case_details_and_link(tmp_path, repo):
    sns = FakeSns()
    svc = service(tmp_path, SnsEmailNotifier(TOPIC, app_url="https://example.test/app", client=sns))
    cid = svc.submit(rec_for(repo), "madhukar")
    [msg] = sns.published
    assert msg["TopicArn"] == TOPIC
    assert msg["Subject"] == f"Approval needed: 50 x laptop ({cid})"
    for part in [cid, "Requested by: madhukar", "50 x laptop", "2026-12-15", "Acme Supplies",
                 "Sign in to review and approve: https://example.test/app", "No purchase is made"]:
        assert part in msg["Message"], part


def test_N9_email_subject_is_one_line_within_sns_limit(tmp_path, repo):
    sns = FakeSns()
    svc = service(tmp_path, SnsEmailNotifier(TOPIC, client=sns))
    rec = rec_for(repo)
    from dataclasses import replace
    long_req = replace(rec.request, product="laptop\n" + "x" * 200)
    svc.submit(replace(rec, request=long_req), "madhukar")
    subject = sns.published[0]["Subject"]
    assert len(subject) <= SNS_SUBJECT_MAX and "\n" not in subject


def test_N10_bad_topic_arn_rejected():
    with pytest.raises(ValueError):
        SnsEmailNotifier("not-an-arn", client=FakeSns())


# ---------------------------------------------------------------- failure handling
def test_N11_email_failure_does_not_block_submit_or_in_app_alert(tmp_path, repo, users, alerts):
    notifier = CompositeNotifier([InAppNotifier(alerts, users), SnsEmailNotifier(TOPIC, client=FakeSns(fail=True))])
    svc = service(tmp_path, notifier)
    cid = svc.submit(rec_for(repo), "madhukar")
    assert svc.get(cid).status == "PENDING_APPROVAL"
    assert alerts.unread_count("mass") == 1
    last = audit(tmp_path)[-1]
    assert last["event"] == "approvers_notified" and "network down" in last["details"]["errors"]["email"]


def test_N12_all_channels_failing_is_audited_and_case_kept(tmp_path, repo):
    svc = service(tmp_path, CompositeNotifier([SnsEmailNotifier(TOPIC, client=FakeSns(fail=True))]))
    cid = svc.submit(rec_for(repo), "madhukar")
    assert svc.get(cid).status == "PENDING_APPROVAL"
    assert audit(tmp_path)[-1]["event"] == "notify_failed"


def test_N13_no_notifier_means_no_alert_events(tmp_path, repo):
    svc = service(tmp_path, None)
    svc.submit(rec_for(repo), "madhukar")
    assert [e["event"] for e in audit(tmp_path)] == ["submitted"]


def test_N14_requester_cannot_read_approver_alerts(tmp_path, repo, users, alerts):
    service(tmp_path, InAppNotifier(alerts, users)).submit(rec_for(repo), "madhukar")
    assert alerts.mark_read("madhukar") == 0          # cannot clear someone else's alerts
    assert alerts.unread_count("mass") == 1
