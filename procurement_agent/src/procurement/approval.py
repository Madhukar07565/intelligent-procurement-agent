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
from typing import TYPE_CHECKING, Callable

from .models import BuildRecommendation, Decision, Quote, Recommendation, group_by_supplier
from .po import PurchaseOrder, PurchaseOrderIssuer
from .specs import summarize_specs
from .store import SqliteCaseStore

if TYPE_CHECKING:
    from .notifications import Notifier

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
    """One approval request, which becomes exactly one purchase order.

    A single-product request has one line. A multi-product request is split into one case per
    winning supplier; those cases share `build_id`, and each holds that supplier's products.
    `recommendation` is line 1 and `extra_lines` the rest. After approval, `chosen_quotes` holds
    the approved quote for every line (all from one supplier), and `purchase_orders` the PO.
    """
    case_id: str
    recommendation: Recommendation
    submitted_by: str
    submitted_at: str = ""
    status: str = PENDING
    decision: Decision | None = None
    chosen_quotes: list[Quote] = field(default_factory=list)
    purchase_orders: list[PurchaseOrder] = field(default_factory=list)
    po_error: str | None = None
    extra_lines: list[Recommendation] = field(default_factory=list)
    title: str = ""
    summary: str = ""
    build_id: str = ""        # shared by all approval requests created from one multi-product request
    build_part: int = 0       # 1-based position among those requests
    build_parts: int = 0      # how many approval requests the order was split into

    @property
    def lines(self) -> list[Recommendation]:
        return [self.recommendation, *self.extra_lines]

    @property
    def supplier(self) -> str:
        """The supplier this request goes to (approved, else recommended)."""
        q = self.chosen_quote or self.recommendation.comparison.recommended.quote
        return q.supplier

    def supplier_options(self) -> list[str]:
        """Suppliers with a qualifying quote for every product in this request, best first."""
        names = [s.quote.supplier for s in self.recommendation.comparison.ranked]
        for r in self.extra_lines:
            have = {s.quote.supplier for s in r.comparison.ranked}
            names = [n for n in names if n in have]
        return names

    @property
    def is_build(self) -> bool:
        return bool(self.extra_lines)

    @property
    def chosen_quote(self) -> Quote | None:
        return self.chosen_quotes[0] if self.chosen_quotes else None

    @property
    def purchase_order(self) -> PurchaseOrder | None:
        return self.purchase_orders[0] if self.purchase_orders else None

    def po_groups(self) -> list[tuple[str, list[int]]]:
        """Purchase orders this case produces: approved quotes after a decision, else the recommendation."""
        quotes = self.chosen_quotes or [r.comparison.recommended.quote for r in self.lines]
        return group_by_supplier(quotes)

    def total(self) -> float:
        quotes = self.chosen_quotes or [r.comparison.recommended.quote for r in self.lines]
        return round(sum(q.total_price for q in quotes), 2)

    @property
    def purchase_confirmed(self) -> bool:
        return self.status in (APPROVED, PO_ISSUED)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalService:
    def __init__(self, audit_path: str | Path, clock: Callable[[], datetime] = _utcnow,
                 po_issuer: PurchaseOrderIssuer | None = None, store: SqliteCaseStore | None = None,
                 notifier: "Notifier | None" = None):
        self._po_issuer = po_issuer
        self._notifier = notifier
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
    def submit(self, recommendation: Recommendation | BuildRecommendation, submitted_by: str) -> str:
        """Create one approval request. A multi-product request must go to a single supplier here;
        use submit_build to split one across suppliers."""
        build = (recommendation if isinstance(recommendation, BuildRecommendation)
                 else BuildRecommendation.single(recommendation))
        if len(build.po_groups()) > 1:
            raise ApprovalError("These products go to several suppliers; submit one request per supplier.")
        return self.submit_build(build, submitted_by)[0]

    def submit_build(self, build: BuildRecommendation, submitted_by: str) -> list[str]:
        """Create one approval request per winning supplier, each holding that supplier's products.

        Products no supplier can fulfil are not submitted. Returns the case IDs in supplier order.
        """
        orderable = list(build.orderable)
        if not orderable:
            raise ApprovalError("There is no supplier option to approve.")
        groups = build.po_groups()
        multi = len(build.lines) > 1
        build_id = uuid.uuid4().hex[:8] if multi else ""
        now = self._clock().isoformat()
        cases = []
        for part, (supplier, idx) in enumerate(groups, start=1):
            lines = [orderable[i] for i in idx]
            cases.append(Case(uuid.uuid4().hex[:8], lines[0], submitted_by, submitted_at=now,
                              extra_lines=lines[1:], title=build.title if multi else "",
                              summary=build.summary if multi else "", build_id=build_id,
                              build_part=part if multi else 0, build_parts=len(groups) if multi else 0))
        with self._lock:
            for case in cases:
                self._store.save(case)
        ids = [c.case_id for c in cases]
        for case in cases:
            details = {
                "request": case.recommendation.request.to_dict(),
                "ranking": case.recommendation.comparison.to_dict(),
                "excluded": case.recommendation.excluded,
                "explanation": case.recommendation.explanation,
            }
            if multi:
                details.update({
                    "build_id": build_id, "title": build.title, "summary": build.summary,
                    "part": case.build_part, "parts": case.build_parts, "supplier": case.supplier,
                    "lines": [{"request": r.request.to_dict(), "ranking": r.comparison.to_dict()}
                              for r in case.lines],
                    "other_requests": [i for i in ids if i != case.case_id],
                    "not_submitted": [r.request.product for r in build.unfilled],
                })
            self._audit("submitted", case.case_id, submitted_by, details)
        for case in cases:
            self._notify_approvers(case.case_id, submitted_by)
        return ids

    def build_cases(self, build_id: str) -> list[Case]:
        """All approval requests created from one multi-product request."""
        if not build_id:
            return []
        return [c for c in self._store.list() if c.build_id == build_id]

    def _notify_approvers(self, case_id: str, submitted_by: str) -> None:
        """Alert approvers. The case is already saved, so a failure here never loses it."""
        if self._notifier is None:
            return
        try:
            sent = self._notifier.case_submitted(self.get(case_id))
            errors = getattr(self._notifier, "last_errors", {})
            self._audit("approvers_notified", case_id, submitted_by, {"alerts_sent": sent, "errors": errors})
        except Exception as exc:
            self._audit("notify_failed", case_id, submitted_by, {"error": f"{type(exc).__name__}: {exc}"})

    def po_pdf(self, case_id: str, po_number: str | None = None) -> bytes:
        """PDF of an issued purchase order of a case (the first one if no number is given)."""
        case = self.get(case_id)
        if not case.purchase_orders or self._po_issuer is None:
            raise ApprovalError("No purchase order has been issued for this case.")
        po = case.purchase_orders[0] if po_number is None else next(
            (p for p in case.purchase_orders if p.po_number == po_number), None)
        if po is None:
            raise ApprovalError(f"Purchase order {po_number} does not belong to this case.")
        return self._po_issuer.pdf_bytes(po)

    def reassign_requester(self, old: str, new: str, actor: str) -> int:
        """Move a renamed requester's cases to the new username, with an audit record."""
        with self._lock:
            moved = self._store.reassign_submitter(old, new)
        self._audit("requester_renamed", "-", actor, {"from": old, "to": new, "cases_moved": moved})
        return moved

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
        line_suppliers: dict[int, str] | None = None,
    ) -> Decision:
        """Approve or reject a whole approval request. It always becomes one purchase order.

        chosen_supplier switches every product in the request to that supplier (it must have a
        qualifying quote for each). line_suppliers maps line indexes to suppliers; the result must
        still be a single supplier.
        """
        comment = (comment or "").strip()
        with self._lock:
            case = self.get(case_id)
            choices = dict(line_suppliers or {})
            if chosen_supplier:
                for i in range(len(case.lines)):
                    choices.setdefault(i, chosen_supplier)
            try:
                chosen = self._validate(case, user, approve, comment, choices)
            except ApprovalError as exc:
                self._audit("decision_refused", case_id, user.name, {"reason": str(exc), "approve": approve})
                raise
            decision = Decision(
                case_id=case_id, approved=approve, approver=user.name, comment=comment,
                chosen_supplier=chosen[0].supplier if approve else None,
                timestamp=self._clock().isoformat(),
                line_suppliers=tuple(q.supplier for q in chosen) if approve else (),
            )
            case.decision = decision
            case.status = APPROVED if approve else REJECTED
            case.chosen_quotes = list(chosen) if approve else []
            self._store.save(case)
        details = {
            "comment": comment,
            "chosen_supplier": decision.chosen_supplier,
            "recommended_supplier": case.recommendation.comparison.recommended.quote.supplier,
        }
        if case.is_build:
            details["line_suppliers"] = list(decision.line_suppliers)
            details["recommended_line_suppliers"] = [r.comparison.recommended.quote.supplier for r in case.lines]
        self._audit("approved" if approve else "rejected", case_id, user.name, details)
        if approve and self._po_issuer is not None:
            # A PO failure does not undo the approval; it can be retried with issue_po().
            try:
                self.issue_pos(case_id, user)
            except ApprovalError:
                pass
        return decision

    def issue_po(self, case_id: str, user: User) -> PurchaseOrder:
        """Generate the purchase orders of an approved case and return the first one."""
        return self.issue_pos(case_id, user)[0]

    def issue_pos(self, case_id: str, user: User) -> list[PurchaseOrder]:
        """Generate one PO per supplier for an approved case. Safe to retry; never issues a PO twice.

        If one supplier's PO fails, the POs already issued are kept, and a retry issues only the rest.
        """
        if self._po_issuer is None:
            raise ApprovalError("Purchase order generation is not configured.")
        issued_now: list[PurchaseOrder] = []
        with self._lock:
            case = self.get(case_id)
            if user.role != APPROVER:
                raise ApprovalError("Only an approver can issue a purchase order.")
            if case.status == PO_ISSUED:
                numbers = ", ".join(p.po_number for p in case.purchase_orders)
                raise ApprovalError(f"Purchase order {numbers} was already issued.")
            if case.status != APPROVED or case.decision is None or not case.chosen_quotes:
                raise ApprovalError("A purchase order can only be issued for an approved case.")
            done = {p.supplier for p in case.purchase_orders}
            for supplier, idx in group_by_supplier(case.chosen_quotes):
                if supplier in done:
                    continue
                fields = self._po_fields(case, idx)
                try:
                    po = self._po_issuer.issue(fields)
                except Exception as exc:  # disk full, permissions, remote failure
                    case.po_error = f"{supplier}: {exc}"
                    self._store.save(case)
                    self._audit("po_failed", case_id, user.name, {"supplier": supplier, "error": str(exc)})
                    raise ApprovalError(
                        f"Approved, but the purchase order for {supplier} could not be generated: {exc}") from exc
                case.purchase_orders.append(po)
                issued_now.append(po)
                self._store.save(case)  # keep each PO as soon as it exists
            case.po_error = None
            case.status = PO_ISSUED
            self._store.save(case)
        for po in issued_now:
            self._audit("po_issued", case_id, user.name, {
                "po_number": po.po_number, "supplier": po.supplier,
                "total_price": po.total_price, "currency": po.currency,
                **({"lines": len(po.lines)} if case.is_build else {}),
            })
        return list(case.purchase_orders)

    def _po_fields(self, case: Case, idx: list[int]) -> dict:
        """PO content for the lines `idx` of a case, all won by the same supplier."""
        d = case.decision
        items = []
        for i in idx:
            q, rec = case.chosen_quotes[i], case.lines[i]
            items.append({
                "product": q.product, "model": q.model,
                "specification": summarize_specs(q.product, q.spec_dict) if q.model else "",
                "quantity": rec.request.quantity, "unit_price": q.unit_price, "amount": q.total_price,
                "currency": q.currency, "quote_ref": q.quote_ref, "delivery_date": q.delivery_date.isoformat(),
                "required_date": rec.request.required_date.isoformat(),
                "recommended_supplier": rec.comparison.recommended.quote.supplier,
            })
        first = items[0]
        return {
            "case_id": case.case_id, "issued_at": self._clock().isoformat(),
            "supplier": case.chosen_quotes[idx[0]].supplier,
            "quote_ref": ", ".join(dict.fromkeys(x["quote_ref"] for x in items)),
            "product": first["product"], "quantity": first["quantity"], "unit_price": first["unit_price"],
            "total_price": round(sum(x["amount"] for x in items), 2), "currency": first["currency"],
            "delivery_date": max(x["delivery_date"] for x in items),
            "required_date": min(x["required_date"] for x in items),
            "requested_by": case.submitted_by, "approved_by": d.approver, "approved_at": d.timestamp,
            "approval_comment": d.comment, "recommended_supplier": first["recommended_supplier"],
            "model": first["model"], "specification": first["specification"],
            "lines": tuple(items) if case.is_build else (), "build_title": case.title,
        }

    def _validate(self, case: Case, user: User, approve: bool, comment: str,
                  choices: dict[int, str]) -> list[Quote]:
        if user.role != APPROVER:
            raise ApprovalError("Only an approver can approve or reject a purchase.")
        if user.name == case.submitted_by:
            raise ApprovalError("You cannot decide on your own request.")
        if case.status != PENDING:
            raise ApprovalError(f"This case was already decided ({case.status}).")
        if not approve and not comment:
            raise ApprovalError("A comment is required when rejecting.")

        lines = case.lines
        unknown = [i for i in choices if not 0 <= int(i) < len(lines)]
        if unknown:
            raise ApprovalError(f"Line {unknown[0] + 1} is not part of this request.")
        chosen: list[Quote] = []
        for i, rec in enumerate(lines):
            recommended = rec.comparison.recommended.quote
            quotes = {s.quote.supplier: s.quote for s in rec.comparison.ranked}
            pick = choices.get(i)
            q = recommended
            if pick and pick != recommended.supplier:
                if pick not in quotes:
                    raise ApprovalError(f"{pick} has no qualifying quote for {rec.request.product}."
                                        if case.is_build else f"{pick} is not one of the quoted suppliers.")
                if approve and not comment:
                    raise ApprovalError("A comment is required when choosing a supplier other than the recommended one.")
                q = quotes[pick]
            if approve and q.valid_until < self._clock().date():
                raise ApprovalError(
                    f"The quotation from {q.supplier} expired on {q.valid_until.isoformat()}. "
                    "Refresh the quotes before approving."
                )
            chosen.append(q)
        if approve and len({q.supplier for q in chosen}) > 1:
            raise ApprovalError("All products in one approval request go to one supplier, so they become one "
                                "purchase order. Choose a supplier that quoted every product, or reject the request.")
        return chosen
