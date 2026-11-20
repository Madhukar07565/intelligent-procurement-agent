"""Render a PurchaseOrder as a PDF document ready to send to the supplier."""
from __future__ import annotations

import os
from dataclasses import dataclass

from fpdf import FPDF


@dataclass(frozen=True)
class Buyer:
    name: str
    address: str
    email: str

    @staticmethod
    def from_env() -> "Buyer":
        return Buyer(
            name=os.getenv("BUYER_NAME", "RoyalCyber"),
            # "\n" (or a literal "\n" in the env var) starts a new line on the PO.
            address=os.getenv("BUYER_ADDRESS",
                              "55 Shuman Blvd, Suite 275\nNaperville, Illinois 60563\nUSA").replace("\\n", "\n"),
            email=os.getenv("BUYER_EMAIL", "procurement@example.com"),
        )


def _t(text) -> str:
    """Core PDF fonts are Latin-1 only; replace anything else rather than fail."""
    return str(text).encode("latin-1", "replace").decode("latin-1")


def _money(amount: float, currency: str) -> str:
    return f"{amount:,.2f} {currency}"


def render_po_pdf(po, buyer: Buyer | None = None) -> bytes:
    buyer = buyer or Buyer.from_env()
    pdf = FPDF(format="A4")
    pdf.set_title(_t(f"Purchase Order {po.po_number}"))
    pdf.set_author(_t(buyer.name))
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    w = pdf.epw  # effective page width

    # Header
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(w * 0.6, 10, "PURCHASE ORDER")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(w * 0.4, 10, _t(f"PO number: {po.po_number}"), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(w * 0.6, 6, "")
    pdf.cell(w * 0.4, 6, _t(f"Date: {po.issued_at[:10]}"), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(w * 0.6, 6, "")
    pdf.cell(w * 0.4, 6, _t(f"Quotation ref: {po.quote_ref}"), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Buyer and supplier blocks
    top = pdf.get_y()
    col = w / 2 - 2
    for x_off, title, lines in (
        (0, "BUYER", [buyer.name, buyer.address, buyer.email]),
        (w / 2 + 2, "SUPPLIER", [po.supplier, f"Quotation {po.quote_ref}"]),
    ):
        pdf.set_xy(pdf.l_margin + x_off, top)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(col, 6, title, new_x="LEFT", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for line in lines:
            pdf.multi_cell(col, 5, _t(line), new_x="LEFT", new_y="NEXT")
    pdf.set_y(max(pdf.get_y(), top + 30))
    pdf.ln(4)

    # Line items
    widths = [w * 0.08, w * 0.42, w * 0.12, w * 0.19, w * 0.19]
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(230, 230, 230)
    for width, head, align in zip(widths, ["#", "Description", "Qty", "Unit price", "Amount"],
                                  ["C", "L", "R", "R", "R"]):
        pdf.cell(width, 8, head, border=1, align=align, fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 10)
    model = getattr(po, "model", "")
    spec = getattr(po, "specification", "")
    desc = f"{po.product.title()}, model {model}" if model else po.product.title()
    row_h = 8 if not spec else 13
    y0 = pdf.get_y()
    pdf.cell(widths[0], row_h, "1", border=1, align="C")
    x_desc = pdf.get_x()
    pdf.cell(widths[1], row_h, "", border=1)  # frame; text drawn inside below
    for width, val in zip(widths[2:], [str(po.quantity), _money(po.unit_price, po.currency),
                                       _money(po.total_price, po.currency)]):
        pdf.cell(width, row_h, _t(val), border=1, align="R")
    pdf.set_xy(x_desc + 1, y0 + 1.5)
    pdf.cell(widths[1] - 2, 5, _t(desc))
    if spec:
        pdf.set_xy(x_desc + 1, y0 + 6.5)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(widths[1] - 2, 5, _t(spec[:80]))
        pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(pdf.l_margin, y0 + row_h)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(sum(widths[:4]), 8, "TOTAL", border=1, align="R")
    pdf.cell(widths[4], 8, _t(_money(po.total_price, po.currency)), border=1, align="R")
    pdf.ln(12)

    # Delivery and terms
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(w, 6, "DELIVERY AND TERMS", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for line in (
        f"Required delivery date: {po.required_date}",
        f"Expected delivery date (per quotation): {po.delivery_date}",
        f"Prices, payment and delivery terms as stated in quotation {po.quote_ref}.",
        f"Please quote PO number {po.po_number} on all invoices, delivery notes and correspondence.",
        f"Please confirm acceptance of this order to {buyer.email}.",
    ):
        pdf.multi_cell(w, 5, _t(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Authorization
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(w, 6, "AUTHORIZATION", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    lines = [
        f"Requested by: {po.requested_by}",
        f"Approved by: {po.approved_by} on {po.approved_at[:19].replace('T', ' ')} UTC",
        f"Internal reference: case {po.case_id}",
    ]
    if po.supplier != po.recommended_supplier:
        lines.append(f"Approver selected {po.supplier} over the recommended {po.recommended_supplier}. "
                     f"Reason: {po.approval_comment}")
    elif po.approval_comment:
        lines.append(f"Approval comment: {po.approval_comment}")
    for line in lines:
        pdf.multi_cell(w, 5, _t(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(14)
    pdf.cell(w * 0.45, 6, "_______________________________", new_x="RIGHT")
    pdf.cell(w * 0.1, 6, "")
    pdf.cell(w * 0.45, 6, "_______________________________", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(w * 0.45, 5, "Authorized signature (buyer)")
    pdf.cell(w * 0.1, 5, "")
    pdf.cell(w * 0.45, 5, "Accepted by supplier / date", new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
