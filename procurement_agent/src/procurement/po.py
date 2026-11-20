"""Purchase order generation (option A: PDF purchase orders on disk).

A PO is only ever created by ApprovalService for an APPROVED case. Other
destinations (email, ERP, queue) can be added later by implementing
`PurchaseOrderIssuer` without touching the approval logic.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from .po_pdf import Buyer, render_po_pdf


@dataclass(frozen=True)
class PurchaseOrder:
    po_number: str
    case_id: str
    issued_at: str
    supplier: str
    quote_ref: str
    product: str
    quantity: int
    unit_price: float
    total_price: float
    currency: str
    delivery_date: str
    required_date: str
    requested_by: str
    approved_by: str
    approved_at: str
    approval_comment: str
    recommended_supplier: str
    model: str = ""            # supplier model / part number
    specification: str = ""    # e.g. '0-150 psi · 4-20 mA · ±0.25% · 1/4" NPT'

    def to_dict(self) -> dict:
        return asdict(self)

    def to_markdown(self) -> str:
        override = (
            f"\n> Approver chose {self.supplier} instead of the recommended supplier "
            f"{self.recommended_supplier}. Reason: {self.approval_comment}\n"
            if self.supplier != self.recommended_supplier else ""
        )
        return f"""# Purchase Order {self.po_number}

Issued: {self.issued_at}
Case: {self.case_id}

## Supplier
{self.supplier} (quotation {self.quote_ref}){f", model {self.model}" if self.model else ""}

## Order
| Product | Quantity | Unit price | Total |
|---|---|---|---|
| {self.product} | {self.quantity} | {self.unit_price:,.2f} {self.currency} | {self.total_price:,.2f} {self.currency} |

Expected delivery: {self.delivery_date} (required by {self.required_date})

## Approval
Requested by: {self.requested_by}
Approved by: {self.approved_by} at {self.approved_at}
Comment: {self.approval_comment or "-"}
{override}"""


class PurchaseOrderIssuer(Protocol):
    def issue(self, po_fields: dict) -> PurchaseOrder:
        """Assign a PO number, persist or send the PO, and return it."""
        ...

    def pdf_bytes(self, po: PurchaseOrder) -> bytes:
        """Return the issued PO document as PDF."""
        ...


class FilePurchaseOrderIssuer:
    """Writes PO-YYYY-NNNN.pdf (the document for the supplier) and PO-YYYY-NNNN.json (the record).

    Numbers are sequential per year and never reused.
    """

    def __init__(self, folder: str | Path, buyer: Buyer | None = None):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._buyer = buyer
        self._lock = threading.Lock()

    def _next_number(self, year: str) -> int:
        pattern = re.compile(rf"PO-{year}-(\d{{4,}})\.json$")
        nums = [int(m.group(1)) for p in self.folder.iterdir() if (m := pattern.match(p.name))]
        return max(nums, default=0) + 1

    def pdf_path(self, po: PurchaseOrder) -> Path:
        return self.folder / f"{po.po_number}.pdf"

    def pdf_bytes(self, po: PurchaseOrder) -> bytes:
        """The issued PDF exactly as saved."""
        return self.pdf_path(po).read_bytes()

    def issue(self, po_fields: dict) -> PurchaseOrder:
        year = po_fields["issued_at"][:4]
        with self._lock:
            n = self._next_number(year)
            while True:
                po = PurchaseOrder(po_number=f"PO-{year}-{n:04d}", **po_fields)
                pdf = render_po_pdf(po, self._buyer)  # render first so a failure claims no number
                try:
                    # "x" fails if the file exists, so a number is never reused.
                    with (self.folder / f"{po.po_number}.json").open("x", encoding="utf-8") as f:
                        json.dump(po.to_dict(), f, indent=2)
                    break
                except FileExistsError:
                    n += 1
            self.pdf_path(po).write_bytes(pdf)
        return po
