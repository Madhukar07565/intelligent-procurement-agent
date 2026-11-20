"""Purchase order generation (option A)."""
import json
import threading
from datetime import date, datetime, timedelta, timezone

import pytest

from procurement.agent import validate_fields
from procurement.approval import (APPROVED, PENDING, PO_ISSUED, REJECTED, ApprovalError,
                                  ApprovalService, User)
from procurement.comparison import compare
from procurement.models import Recommendation
from procurement.po import FilePurchaseOrderIssuer

TODAY = date(2026, 11, 20)


def pdf_text(path_or_bytes):
    import io
    from pypdf import PdfReader
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else path_or_bytes
    reader = PdfReader(src)
    return "\n".join(page.extract_text() for page in reader.pages)
BOB = User("bob", "approver")


@pytest.fixture
def rec(repo):
    quotes, ex = repo.find("laptop", 50, TODAY)
    req = validate_fields("laptop", 50, date(2026, 12, 15), TODAY, requester="alice").request
    return Recommendation(req, compare(quotes, req.required_date), "expl", ex)


@pytest.fixture
def clock():
    return {"t": datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)}


@pytest.fixture
def po_dir(tmp_path):
    return tmp_path / "pos"


@pytest.fixture
def svc(tmp_path, po_dir, clock):
    return ApprovalService(tmp_path / "audit.jsonl", clock=lambda: clock["t"],
                           po_issuer=FilePurchaseOrderIssuer(po_dir))


def audit(svc):
    return [json.loads(x) for x in svc._audit_path.read_text().splitlines()]


def test_PO1_approval_issues_po_with_correct_contents(svc, rec, po_dir):
    cid = svc.submit(rec, "alice")
    svc.decide(cid, BOB, True, "ok")
    case = svc.get(cid)
    po = case.purchase_order
    assert case.status == PO_ISSUED and case.purchase_confirmed
    assert po.po_number == "PO-2026-0001"
    assert (po.supplier, po.quote_ref, po.quantity, po.unit_price, po.total_price, po.currency) == \
        ("Acme Supplies", "ACM-1001", 50, 950.0, 47500.0, "USD")
    assert (po.delivery_date, po.required_date) == ("2026-11-30", "2026-12-15")
    assert (po.requested_by, po.approved_by, po.approval_comment) == ("alice", "bob", "ok")
    saved = json.loads((po_dir / "PO-2026-0001.json").read_text())
    assert saved == po.to_dict()
    text = pdf_text(po_dir / "PO-2026-0001.pdf")
    for expected in ["PURCHASE ORDER", "PO-2026-0001", "Acme Supplies", "ACM-1001", "Laptop", "50",
                     "950.00 USD", "47,500.00 USD", "2026-12-15", "2026-11-30", "Approved by: bob",
                     "Requested by: alice", "Authorized signature"]:
        assert expected in text, expected
    assert svc.po_pdf(cid) == (po_dir / "PO-2026-0001.pdf").read_bytes()
    assert [e["event"] for e in audit(svc)] == ["submitted", "approved", "po_issued"]


def test_PO2_no_po_while_pending(svc, rec, po_dir):
    cid = svc.submit(rec, "alice")
    assert svc.get(cid).purchase_order is None and list(po_dir.iterdir()) == []
    with pytest.raises(ApprovalError, match="approved case"):
        svc.issue_po(cid, BOB)
    assert list(po_dir.iterdir()) == [] and svc.get(cid).status == PENDING


def test_PO3_no_po_after_rejection(svc, rec, po_dir):
    cid = svc.submit(rec, "alice")
    svc.decide(cid, BOB, False, "no budget")
    with pytest.raises(ApprovalError):
        svc.issue_po(cid, BOB)
    assert svc.get(cid).status == REJECTED and list(po_dir.iterdir()) == []


@pytest.mark.parametrize("user,approve,comment,supplier", [
    (User("alice", "approver"), True, "ok", None),
    (User("zed", "requester"), True, "ok", None),
    (BOB, True, "", "TechWorld"),
])
def test_PO4_refused_approvals_create_no_po(svc, rec, po_dir, user, approve, comment, supplier):
    cid = svc.submit(rec, "alice")
    with pytest.raises(ApprovalError):
        svc.decide(cid, user, approve, comment, supplier)
    assert list(po_dir.iterdir()) == []


def test_PO5_expired_quote_creates_no_po(svc, rec, po_dir, clock):
    cid = svc.submit(rec, "alice")
    clock["t"] += timedelta(days=1000)
    with pytest.raises(ApprovalError, match="expired"):
        svc.decide(cid, BOB, True, "ok")
    assert list(po_dir.iterdir()) == []


def test_PO6_never_two_pos_for_one_case(svc, rec, po_dir):
    cid = svc.submit(rec, "alice")
    svc.decide(cid, BOB, True, "ok")
    with pytest.raises(ApprovalError, match="already issued"):
        svc.issue_po(cid, BOB)
    errors = []

    def retry():
        try:
            svc.issue_po(cid, BOB)
        except ApprovalError:
            errors.append(1)
    ts = [threading.Thread(target=retry) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(errors) == 8
    assert sorted(p.name for p in po_dir.iterdir()) == ["PO-2026-0001.json", "PO-2026-0001.pdf"]


def test_PO7_numbers_are_sequential_and_unique(svc, repo, po_dir):
    numbers = []
    for _ in range(3):
        quotes, ex = repo.find("laptop", 5, TODAY)
        req = validate_fields("laptop", 5, date(2026, 12, 15), TODAY).request
        cid = svc.submit(Recommendation(req, compare(quotes, req.required_date), "e", ex), "alice")
        svc.decide(cid, BOB, True)
        numbers.append(svc.get(cid).purchase_order.po_number)
    assert numbers == ["PO-2026-0001", "PO-2026-0002", "PO-2026-0003"]


def test_PO8_numbering_continues_after_restart(tmp_path, rec, po_dir, clock):
    s1 = ApprovalService(tmp_path / "a.jsonl", clock=lambda: clock["t"], po_issuer=FilePurchaseOrderIssuer(po_dir))
    s1.decide(s1.submit(rec, "alice"), BOB, True)
    s2 = ApprovalService(tmp_path / "a.jsonl", clock=lambda: clock["t"], po_issuer=FilePurchaseOrderIssuer(po_dir))
    cid = s2.submit(rec, "alice")
    s2.decide(cid, BOB, True)
    assert s2.get(cid).purchase_order.po_number == "PO-2026-0002"


def test_PO9_override_supplier_appears_on_po(svc, rec):
    cid = svc.submit(rec, "alice")
    svc.decide(cid, BOB, True, "cheaper, we can wait", chosen_supplier="TechWorld")
    po = svc.get(cid).purchase_order
    assert po.supplier == "TechWorld" and po.total_price == 44950.0
    assert "instead of the recommended supplier Acme Supplies" in po.to_markdown()


class BrokenIssuer:
    def __init__(self):
        self.fail = True
        self.calls = 0

    def issue(self, fields):
        self.calls += 1
        if self.fail:
            raise OSError("disk full")
        return FilePurchaseOrderIssuer(self.folder).issue(fields)


def test_PO10_issuer_failure_keeps_approval_and_can_be_retried(tmp_path, rec, clock):
    issuer = BrokenIssuer()
    issuer.folder = tmp_path / "pos"
    svc = ApprovalService(tmp_path / "a.jsonl", clock=lambda: clock["t"], po_issuer=issuer)
    cid = svc.submit(rec, "alice")
    svc.decide(cid, BOB, True, "ok")          # does not raise
    case = svc.get(cid)
    assert case.status == APPROVED and case.purchase_order is None and "disk full" in case.po_error
    assert audit(svc)[-1]["event"] == "po_failed"
    issuer.fail = False
    po = svc.issue_po(cid, BOB)
    assert svc.get(cid).status == PO_ISSUED and po.po_number == "PO-2026-0001" and case.po_error is None


def test_PO11_only_approver_can_retry(tmp_path, rec, clock):
    issuer = BrokenIssuer()
    issuer.folder = tmp_path / "pos"
    svc = ApprovalService(tmp_path / "a.jsonl", clock=lambda: clock["t"], po_issuer=issuer)
    cid = svc.submit(rec, "alice")
    svc.decide(cid, BOB, True)
    issuer.fail = False
    with pytest.raises(ApprovalError, match="Only an approver"):
        svc.issue_po(cid, User("alice", "requester"))
    assert svc.get(cid).purchase_order is None


def test_PO12_without_issuer_behaviour_is_unchanged(tmp_path, rec):
    svc = ApprovalService(tmp_path / "a.jsonl")
    cid = svc.submit(rec, "alice")
    svc.decide(cid, BOB, True)
    assert svc.get(cid).status == APPROVED and svc.get(cid).purchase_order is None


def test_PO13_pdf_is_valid_single_page_pdf(svc, rec, po_dir):
    from pypdf import PdfReader
    cid = svc.submit(rec, "alice")
    svc.decide(cid, BOB, True, "ok")
    data = svc.po_pdf(cid)
    assert data.startswith(b"%PDF-")
    reader = PdfReader(po_dir / "PO-2026-0001.pdf")
    assert len(reader.pages) == 1
    assert reader.metadata.title == "Purchase Order PO-2026-0001"


def test_PO14_override_reason_printed_on_pdf(svc, rec, po_dir):
    cid = svc.submit(rec, "alice")
    svc.decide(cid, BOB, True, "cheaper, we can wait", chosen_supplier="TechWorld")
    text = pdf_text(svc.po_pdf(cid))
    assert "TechWorld" in text and "44,950.00 USD" in text
    assert "over the recommended Acme Supplies" in text and "cheaper, we can wait" in text


def test_PO15_buyer_details_configurable(tmp_path, rec, clock, monkeypatch):
    monkeypatch.setenv("BUYER_NAME", "Contoso Ltd")
    monkeypatch.setenv("BUYER_EMAIL", "buy@contoso.test")
    svc = ApprovalService(tmp_path / "a.jsonl", clock=lambda: clock["t"],
                          po_issuer=FilePurchaseOrderIssuer(tmp_path / "pos"))
    cid = svc.submit(rec, "alice")
    svc.decide(cid, BOB, True)
    text = pdf_text(svc.po_pdf(cid))
    assert "Contoso Ltd" in text and "buy@contoso.test" in text


def test_PO16_non_latin_text_does_not_break_pdf(tmp_path, rec, clock):
    svc = ApprovalService(tmp_path / "a.jsonl", clock=lambda: clock["t"],
                          po_issuer=FilePurchaseOrderIssuer(tmp_path / "pos"))
    cid = svc.submit(rec, "alice")
    svc.decide(cid, BOB, True, "approved \u2713 \u4f9b\u5e94\u5546 ok")
    assert svc.get(cid).purchase_order is not None and svc.po_pdf(cid).startswith(b"%PDF-")


def test_PO17_no_pdf_for_unapproved_case(svc, rec):
    cid = svc.submit(rec, "alice")
    with pytest.raises(ApprovalError):
        svc.po_pdf(cid)


def test_PO18_default_buyer_is_royalcyber(svc, rec, monkeypatch):
    for var in ("BUYER_NAME", "BUYER_ADDRESS"):
        monkeypatch.delenv(var, raising=False)
    cid = svc.submit(rec, "alice")
    svc.decide(cid, BOB, True)
    text = pdf_text(svc.po_pdf(cid))
    for line in ["RoyalCyber", "55 Shuman Blvd, Suite 275", "Naperville, Illinois 60563", "USA"]:
        assert line in text, line
