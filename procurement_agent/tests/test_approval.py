import json
from datetime import date, datetime, timedelta, timezone

import pytest

from procurement.agent import validate_fields
from procurement.approval import (APPROVED, PENDING, REJECTED, ApprovalError, ApprovalService, User)
from procurement.comparison import compare
from procurement.models import Recommendation

ALICE = User("alice", "requester")
BOB = User("bob", "approver")
CARA = User("cara", "approver")


@pytest.fixture
def clock_state():
    return {"now": datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)}


@pytest.fixture
def svc(tmp_path, clock_state):
    return ApprovalService(tmp_path / "audit.jsonl", clock=lambda: clock_state["now"])


@pytest.fixture
def rec(repo, today):
    request = validate_fields("laptop", 50, date(2026, 12, 15), today).request
    quotes, excluded = repo.find("laptop", 50, today)
    return Recommendation(request, compare(quotes, request.required_date), "because", excluded)


@pytest.fixture
def case_id(svc, rec):
    return svc.submit(rec, "alice")


def audit_lines(svc):
    return [json.loads(l) for l in svc._audit_path.read_text().splitlines()]


def test_new_case_is_pending_and_not_confirmed(svc, case_id):
    case = svc.get(case_id)
    assert case.status == PENDING and not case.purchase_confirmed and case.decision is None


def test_p1_approve_writes_audit(svc, case_id):
    d = svc.decide(case_id, BOB, True, "ok")
    case = svc.get(case_id)
    assert case.status == APPROVED and case.purchase_confirmed
    assert d.approver == "bob" and d.chosen_supplier == "Acme Supplies"
    events = [l["event"] for l in audit_lines(svc)]
    assert events == ["submitted", "approved"]


def test_p2_requester_cannot_approve_own(svc, case_id):
    with pytest.raises(ApprovalError, match="own request"):
        svc.decide(case_id, User("alice", "approver"), True)
    assert svc.get(case_id).status == PENDING


def test_p3_non_approver_refused(svc, case_id):
    with pytest.raises(ApprovalError, match="Only an approver"):
        svc.decide(case_id, User("dave", "requester"), True)
    assert not svc.get(case_id).purchase_confirmed


def test_p4_reject_needs_comment(svc, case_id):
    with pytest.raises(ApprovalError, match="comment"):
        svc.decide(case_id, BOB, False, "   ")
    svc.decide(case_id, BOB, False, "too expensive")
    assert svc.get(case_id).status == REJECTED and not svc.get(case_id).purchase_confirmed


def test_p5_second_decision_refused(svc, case_id):
    svc.decide(case_id, BOB, True)
    with pytest.raises(ApprovalError, match="already decided"):
        svc.decide(case_id, CARA, False, "changed my mind")
    assert svc.get(case_id).status == APPROVED


def test_p6_other_supplier_needs_comment(svc, case_id):
    with pytest.raises(ApprovalError, match="other than the recommended"):
        svc.decide(case_id, BOB, True, "", chosen_supplier="TechWorld")
    d = svc.decide(case_id, BOB, True, "cheaper and we have time", chosen_supplier="TechWorld")
    assert d.chosen_supplier == "TechWorld"
    assert svc.get(case_id).chosen_quote.supplier == "TechWorld"


def test_unknown_supplier_refused(svc, case_id):
    with pytest.raises(ApprovalError, match="not one of the quoted"):
        svc.decide(case_id, BOB, True, "x", chosen_supplier="Nobody")


def test_p7_expired_quote_blocks_approval(svc, case_id, clock_state):
    clock_state["now"] += timedelta(days=2000)
    with pytest.raises(ApprovalError, match="expired"):
        svc.decide(case_id, BOB, True, "ok")
    assert svc.get(case_id).status == PENDING
    # rejecting is still allowed
    svc.decide(case_id, BOB, False, "quotes expired")
    assert svc.get(case_id).status == REJECTED


def test_refusals_are_audited(svc, case_id):
    with pytest.raises(ApprovalError):
        svc.decide(case_id, ALICE, True)
    assert audit_lines(svc)[-1]["event"] == "decision_refused"


def test_unknown_case(svc):
    with pytest.raises(ApprovalError, match="Unknown case"):
        svc.decide("nope", BOB, True)


def test_cannot_submit_without_any_option(svc, rec):
    empty = Recommendation(rec.request, compare([], rec.request.required_date), "none")
    with pytest.raises(ApprovalError):
        svc.submit(empty, "alice")
