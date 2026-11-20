"""Persistence: requests, decisions and POs survive an app restart."""
from datetime import date, datetime, timezone

import pytest

from procurement.agent import validate_fields
from procurement.approval import APPROVED, PENDING, PO_ISSUED, REJECTED, ApprovalError, ApprovalService, User
from procurement.comparison import compare
from procurement.models import Recommendation
from procurement.po import FilePurchaseOrderIssuer
from procurement.store import SqliteCaseStore, recommendation_from_dict, recommendation_to_dict

TODAY = date(2026, 11, 20)
BOB = User("bob", "approver")
NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)


def rec_for(repo, product="laptop", qty=50, required=date(2026, 12, 15)):
    quotes, ex = repo.find(product, qty, TODAY)
    req = validate_fields(product, qty, required, TODAY, raw_text=f"{qty} {product}").request
    return Recommendation(req, compare(quotes, required), "Because it is best.", ex)


def service(tmp_path, issuer=True):
    return ApprovalService(
        tmp_path / "audit.jsonl", clock=lambda: NOW,
        po_issuer=FilePurchaseOrderIssuer(tmp_path / "pos") if issuer else None,
        store=SqliteCaseStore(tmp_path / "cases.db"),
    )


def test_S1_pending_case_survives_restart(tmp_path, repo):
    cid = service(tmp_path).submit(rec_for(repo), "alice")
    case = service(tmp_path).get(cid)  # brand new service and DB connection
    assert case.status == PENDING and case.submitted_by == "alice"
    assert case.submitted_at == NOW.isoformat()
    assert case.recommendation.request.quantity == 50
    assert case.recommendation.comparison.recommended.quote.supplier == "Acme Supplies"
    assert case.recommendation.explanation == "Because it is best."
    assert case.recommendation.excluded[0]["supplier"] == "OldDeals Inc"


def test_S2_approval_and_po_survive_restart(tmp_path, repo):
    s1 = service(tmp_path)
    cid = s1.submit(rec_for(repo), "alice")
    s1.decide(cid, BOB, True, "ok")
    s2 = service(tmp_path)
    case = s2.get(cid)
    assert case.status == PO_ISSUED and case.purchase_confirmed
    assert case.decision.approver == "bob" and case.decision.comment == "ok"
    assert case.chosen_quote.supplier == "Acme Supplies"
    assert case.purchase_order.po_number == "PO-2026-0001"
    assert s2.po_pdf(cid).startswith(b"%PDF-")


def test_S3_rejection_survives_restart(tmp_path, repo):
    s1 = service(tmp_path)
    cid = s1.submit(rec_for(repo), "alice")
    s1.decide(cid, BOB, False, "over budget")
    case = service(tmp_path).get(cid)
    assert case.status == REJECTED and case.decision.comment == "over budget" and case.purchase_order is None


def test_S4_rules_still_apply_after_restart(tmp_path, repo):
    s1 = service(tmp_path)
    cid = s1.submit(rec_for(repo), "alice")
    s1.decide(cid, BOB, True)
    s2 = service(tmp_path)
    with pytest.raises(ApprovalError, match="already decided"):
        s2.decide(cid, User("cara", "approver"), False, "late change")
    with pytest.raises(ApprovalError, match="already issued"):
        s2.issue_po(cid, BOB)
    assert len(list((tmp_path / "pos").glob("*.pdf"))) == 1


def test_S5_self_approval_blocked_after_restart(tmp_path, repo):
    cid = service(tmp_path).submit(rec_for(repo), "alice")
    with pytest.raises(ApprovalError, match="own request"):
        service(tmp_path).decide(cid, User("alice", "approver"), True)


def test_S6_filters_by_requester_and_status(tmp_path, repo):
    s = service(tmp_path, issuer=False)
    a1 = s.submit(rec_for(repo), "alice")
    a2 = s.submit(rec_for(repo, "monitor", 5), "alice")
    c1 = s.submit(rec_for(repo, "office chair", 3), "carol")
    s.decide(a2, BOB, True)
    assert [c.case_id for c in s.list_cases(submitted_by="alice")] == [a1, a2]
    assert [c.case_id for c in s.list_cases(submitted_by="carol")] == [c1]
    assert [c.case_id for c in s.list_cases(statuses=[PENDING])] == [a1, c1]
    assert [c.case_id for c in s.list_cases(statuses=[APPROVED, PO_ISSUED])] == [a2]
    assert len(s.list_cases()) == 3


def test_S7_recommendation_round_trip_is_exact(repo):
    for required in (date(2026, 12, 15), date(2026, 11, 22)):  # on-time and all-late cases
        rec = rec_for(repo, required=required)
        back = recommendation_from_dict(recommendation_to_dict(rec))
        assert back == rec


def test_S8_no_quote_recommendation_round_trip(repo):
    req = validate_fields("laptop", 1, date(2026, 12, 1), TODAY).request
    rec = Recommendation(req, compare([], req.required_date), "none", [])
    assert recommendation_from_dict(recommendation_to_dict(rec)) == rec


def test_S9_unknown_case(tmp_path):
    with pytest.raises(ApprovalError, match="Unknown case"):
        service(tmp_path).get("nope")


def test_S10_concurrent_decisions_on_file_store_only_one_wins(tmp_path, repo):
    import threading
    s = service(tmp_path)
    cid = s.submit(rec_for(repo), "alice")
    results = []

    def go(i):
        try:
            s.decide(cid, User(f"u{i}", "approver"), True, "c")
            results.append("ok")
        except ApprovalError:
            results.append("refused")
    ts = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results.count("ok") == 1
    assert len(list((tmp_path / "pos").glob("*.pdf"))) == 1


def test_S11_renamed_requester_keeps_their_cases(tmp_path, repo):
    import json as _json
    s = service(tmp_path)
    c1 = s.submit(rec_for(repo), "madhukar")
    s.decide(c1, BOB, True, "ok")
    c2 = s.submit(rec_for(repo, "monitor", 5), "madhukar")
    other = s.submit(rec_for(repo, "office chair", 3), "carol")
    moved = s.reassign_requester("madhukar", "madhukar.reddy@royalcyber.com", actor="admin")
    assert moved == 2
    s2 = service(tmp_path)  # fresh connection
    mine = s2.list_cases(submitted_by="madhukar.reddy@royalcyber.com")
    assert [c.case_id for c in mine] == [c1, c2]
    assert s2.list_cases(submitted_by="madhukar") == []
    assert s2.get(other).submitted_by == "carol"
    # history is otherwise unchanged
    assert s2.get(c1).status == PO_ISSUED and s2.get(c1).purchase_order.requested_by == "madhukar"
    with pytest.raises(ApprovalError, match="own request"):
        s2.decide(c2, User("madhukar.reddy@royalcyber.com", "approver"), True)
    events = [_json.loads(x) for x in (tmp_path / "audit.jsonl").read_text().splitlines()]
    [renamed] = [e for e in events if e["event"] == "requester_renamed"]
    assert renamed["details"] == {"from": "madhukar", "to": "madhukar.reddy@royalcyber.com", "cases_moved": 2}
