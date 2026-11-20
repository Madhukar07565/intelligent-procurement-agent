"""Human approval workflow and audit log. No LLM involved.

The only code path that moves a case to APPROVED is ApprovalService.decide().
A purchase order is generated only for an APPROVED case (status PO_ISSUED).
"""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .models import Decision, Quote, Recommendation
from .po import PurchaseOrder, PurchaseOrderIssuer
from .store import SqliteCaseStore

PENDING = "PENDING_APPROVAL"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
PO_ISSUED = "PO_ISSUED"

REQUESTER = "requester"
APPROVER = "approver"


class ApprovalError(Exception):
    """A decision was refused. The message is safe to show to the user."""


@dataclass(frozen=True)
class User:
    name: str
    role: str  # "requester" or "approver"


@dataclass
class Case:
    case_id: str
    recommendation: Recommendation
    submitted_by: str
    submitted_at: str = ""
    status: str = PENDING
    decision: Decision | None = None
    chosen_quote: Quote | None = None
    purchase_order: PurchaseOrder | None = None
    po_error: str | None = None

    @property
    def purchase_confirmed(self) -> bool:
        return self.status in (APPROVED, PO_ISSUED)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalService:
    def __init__(self, audit_path: str | Path, clock: Callable[[], datetime] = _utcnow,
                 po_issuer: PurchaseOrderIssuer | None = None, store: SqliteCaseStore | None = None):
        self._po_issuer = po_issuer
        self._store = store or SqliteCaseStore(":memory:")
        self._audit_path = Path(audit_path)
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.Lock()

    # ---- audit -------------------------------------------------------
    def _audit(self, event: str, case_id: str, actor: str, details: dict) -> None:
        line = {"timestamp": self._clock().isoformat(), "event": event,
                "case_id": case_id, "actor": actor, "details": details}
        with self._audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")

    # ---- workflow ----------------------------------------------------
    def submit(self, recommendation: Recommendation, submitted_by: str) -> str:
        if recommendation.comparison.recommended is None:
            raise ApprovalError("There is no supplier option to approve.")
        case_id = uuid.uuid4().hex[:8]
        with self._lock:
            self._store.save(Case(case_id, recommendation, submitted_by, submitted_at=self._clock().isoformat()))
        self._audit("submitted", case_id, submitted_by, {
            "request": recommendation.request.to_dict(),
            "ranking": recommendation.comparison.to_dict(),
            "excluded": recommendation.excluded,
            "explanation": recommendation.explanation,
        })
        return case_id

    def po_pdf(self, case_id: str) -> bytes:
        """PDF of the issued purchase order for a case."""
        case = self.get(case_id)
        if case.purchase_order is None or self._po_issuer is None:
            raise ApprovalError("No purchase order has been issued for this case.")
        return self._po_issuer.pdf_bytes(case.purchase_order)

    def list_cases(self, submitted_by: str | None = None, statuses: list[str] | None = None) -> list[Case]:
        """Cases in submission order, optionally filtered by submitter and status."""
        return self._store.list(submitted_by, statuses)

    def get(self, case_id: str) -> Case:
        """A fresh copy of the stored case. Changes to it are not saved."""
        case = self._store.get(case_id)
        if case is None:
            raise ApprovalError(f"Unknown case: {case_id}")
        return case

    def decide(
        self,
        case_id: str,
        user: User,
        approve: bool,
        comment: str = "",
        chosen_supplier: str | None = None,
    ) -> Decision:
        comment = (comment or "").strip()
        with self._lock:
            case = self.get(case_id)
            try:
                chosen = self._validate(case, user, approve, comment, chosen_supplier)
            except ApprovalError as exc:
                self._audit("decision_refused", case_id, user.name, {"reason": str(exc), "approve": approve})
                raise
            decision = Decision(
                case_id=case_id, approved=approve, approver=user.name, comment=comment,
                chosen_supplier=chosen.supplier if approve else None,
                timestamp=self._clock().isoformat(),
            )
            case.decision = decision
            case.status = APPROVED if approve else REJECTED
            case.chosen_quote = chosen if approve else None
            self._store.save(case)
        self._audit("approved" if approve else "rejected", case_id, user.name, {
            "comment": comment,
            "chosen_supplier": decision.chosen_supplier,
            "recommended_supplier": case.recommendation.comparison.recommended.quote.supplier,
        })
        if approve and self._po_issuer is not None:
            # A PO failure does not undo the approval; it can be retried with issue_po().
            try:
                self.issue_po(case_id, user)
            except ApprovalError:
                pass
        return decision

    def issue_po(self, case_id: str, user: User) -> PurchaseOrder:
        """Generate the PO for an approved case. Safe to retry; never issues twice."""
        if self._po_issuer is None:
            raise ApprovalError("Purchase order generation is not configured.")
        with self._lock:
            case = self.get(case_id)
            if user.role != APPROVER:
                raise ApprovalError("Only an approver can issue a purchase order.")
            if case.status == PO_ISSUED:
                raise ApprovalError(f"Purchase order {case.purchase_order.po_number} was already issued.")
            if case.status != APPROVED or case.decision is None or case.chosen_quote is None:
                raise ApprovalError("A purchase order can only be issued for an approved case.")
            q, req, d = case.chosen_quote, case.recommendation.request, case.decision
            fields = {
                "case_id": case_id, "issued_at": self._clock().isoformat(),
                "supplier": q.supplier, "quote_ref": q.quote_ref, "product": q.product,
                "quantity": req.quantity, "unit_price": q.unit_price, "total_price": q.total_price,
                "currency": q.currency, "delivery_date": q.delivery_date.isoformat(),
                "required_date": req.required_date.isoformat(), "requested_by": case.submitted_by,
                "approved_by": d.approver, "approved_at": d.timestamp, "approval_comment": d.comment,
                "recommended_supplier": case.recommendation.comparison.recommended.quote.supplier,
            }
            try:
                po = self._po_issuer.issue(fields)
            except Exception as exc:  # disk full, permissions, remote failure
                case.po_error = str(exc)
                self._store.save(case)
                self._audit("po_failed", case_id, user.name, {"error": str(exc)})
                raise ApprovalError(f"Approved, but the purchase order could not be generated: {exc}") from exc
            case.purchase_order, case.po_error = po, None
            case.status = PO_ISSUED
            self._store.save(case)
        self._audit("po_issued", case_id, user.name, {
            "po_number": po.po_number, "supplier": po.supplier,
            "total_price": po.total_price, "currency": po.currency,
        })
        return po

    def _validate(self, case: Case, user: User, approve: bool, comment: str,
                  chosen_supplier: str | None) -> Quote:
        if user.role != APPROVER:
            raise ApprovalError("Only an approver can approve or reject a purchase.")
        if user.name == case.submitted_by:
            raise ApprovalError("You cannot decide on your own request.")
        if case.status != PENDING:
            raise ApprovalError(f"This case was already decided ({case.status}).")
        if not approve and not comment:
            raise ApprovalError("A comment is required when rejecting.")

        recommended = case.recommendation.comparison.recommended.quote
        quotes = {s.quote.supplier: s.quote for s in case.recommendation.comparison.ranked}
        chosen = recommended
        if chosen_supplier and chosen_supplier != recommended.supplier:
            if chosen_supplier not in quotes:
                raise ApprovalError(f"{chosen_supplier} is not one of the quoted suppliers.")
            if approve and not comment:
                raise ApprovalError("A comment is required when choosing a supplier other than the recommended one.")
            chosen = quotes[chosen_supplier]

        if approve and chosen.valid_until < self._clock().date():
            raise ApprovalError(
                f"The quotation from {chosen.supplier} expired on {chosen.valid_until.isoformat()}. "
                "Refresh the quotes before approving."
            )
        return chosen
