"""Streamlit screens. `render` takes its collaborators so tests can inject fakes."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from .agent import AgentError, ProcurementAgent, validate_fields
from .approval import APPROVED, APPROVER, PENDING, PO_ISSUED, REJECTED, REQUESTER, ApprovalError, ApprovalService, User
from .models import Recommendation

EXAMPLE = "I need 50 laptops delivered by December 15"


def _ranking_rows(rec: Recommendation) -> list[dict]:
    rows = []
    for i, s in enumerate(rec.comparison.ranked, start=1):
        q = s.quote
        rows.append({
            "Rank": i,
            "Supplier": q.supplier,
            "Total price": f"{q.total_price:,.2f} {q.currency}",
            "Delivery date": q.delivery_date.isoformat(),
            "On time": "Yes" if s.eligible else f"No, {s.days_late} day(s) late",
            "Score": round(s.score, 1) if s.eligible else "-",
            "Quote ref": q.quote_ref,
        })
    return rows


def _show_recommendation(rec: Recommendation, available_products: list[str] | None = None) -> None:
    best = rec.comparison.recommended
    if best is None:
        st.error(f"No quotations are available for \"{rec.request.product}\".")
        for e in rec.excluded:
            st.caption(f"Excluded: {e['supplier']} ({e['quote_ref']}), {e['reason']}")
        if available_products and not rec.excluded:
            st.info("Products with supplier quotations: " + ", ".join(available_products)
                    + ". Edit the product above and confirm again.")
        return
    st.success(f"Recommended supplier: **{best.quote.supplier}**")
    st.write(rec.explanation)
    st.dataframe(_ranking_rows(rec), hide_index=True, use_container_width=True)
    for w in rec.comparison.warnings:
        st.warning(w)
    for e in rec.excluded:
        st.caption(f"Excluded: {e['supplier']} ({e['quote_ref']}), {e['reason']}")
    st.caption("Ranking: 60% price, 40% delivery, among suppliers that meet the required date.")


def _new_request_tab(agent: ProcurementAgent, svc: ApprovalService, user: User, today: date) -> None:
    ss = st.session_state
    text = st.text_area("Describe what you need", value=ss.get("text", ""), key="request_text",
                        placeholder=EXAMPLE)
    if st.button("Extract details", key="extract_btn"):
        ss.pop("rec", None)
        ss.pop("submitted_case", None)
        try:
            ss["extraction"] = agent.extract_request(text, today, requester=user.name)
        except Exception as exc:  # network, credentials, throttling
            ss.pop("extraction", None)
            st.error(f"The AI service failed: {exc}")

    ext = ss.get("extraction")
    if ext is None:
        return

    if ext.ok:
        st.subheader("Confirm details")
        d = {"product": ext.request.product, "quantity": ext.request.quantity,
             "date": ext.request.required_date}
    else:
        st.subheader("Details needed")
        for name in ext.missing:
            st.warning(f"Missing: {name.replace('_', ' ')}")
        for err in ext.errors:
            st.warning(err)
        st.caption("Fill in the fields below or rephrase your request.")
        d = {"product": "", "quantity": 1, "date": today + timedelta(days=14)}

    with st.form("confirm_form"):
        product = st.text_input("Product", value=d["product"])
        quantity = st.number_input("Quantity", min_value=0, value=int(d["quantity"]), step=1)
        required = st.date_input("Required delivery date", value=d["date"])
        confirmed = st.form_submit_button("Confirm and get quotes")

    if confirmed:
        check = validate_fields(product, quantity, required, today, raw_text=text, requester=user.name)
        if not check.ok:
            for err in check.errors + [f"Missing: {m}" for m in check.missing]:
                st.error(err)
        else:
            try:
                with st.spinner("Retrieving and comparing quotations..."):
                    ss["rec"] = agent.recommend(check.request, today)
                ss.pop("submitted_case", None)
            except (AgentError, Exception) as exc:
                ss.pop("rec", None)
                st.error(f"Could not produce a recommendation: {exc}")

    rec = ss.get("rec")
    if rec is not None:
        st.subheader("Recommendation")
        _show_recommendation(rec, agent.available_products())
        if rec.comparison.recommended is not None:
            case_id = ss.get("submitted_case")
            if case_id:
                st.info(f"Submitted for approval. Case ID: **{case_id}**. No purchase has been made.")
            elif st.button("Submit for approval", key="submit_btn"):
                try:
                    ss["submitted_case"] = svc.submit(rec, user.name)
                    st.rerun()
                except ApprovalError as exc:
                    st.error(str(exc))


STATUS_LABEL = {
    PENDING: "Awaiting approval. No purchase made.",
    APPROVED: "Approved. Purchase order not yet issued.",
    PO_ISSUED: "Approved. Purchase order issued.",
    REJECTED: "Rejected. No purchase made.",
}


def _approvals_tab(svc: ApprovalService, user: User) -> None:
    cases = svc.list_cases()
    if not cases:
        st.info("No cases yet.")
        return
    if user.role != APPROVER:
        st.info("You are signed in as a requester. Only approvers can approve or reject.")
    for case in reversed(cases):
        rec = case.recommendation
        req = rec.request
        best = rec.comparison.recommended.quote
        with st.expander(
            f"Case {case.case_id}: {req.quantity} x {req.product} by {req.required_date.isoformat()} "
            f"[{case.status}]", expanded=case.status == PENDING,
        ):
            st.write(f"Requested by **{case.submitted_by}**. Recommended: **{best.supplier}**.")
            _show_recommendation(rec)
            st.markdown(f"**Status:** {STATUS_LABEL[case.status]}")
            if case.decision:
                dcs = case.decision
                st.caption(f"Decision by {dcs.approver} at {dcs.timestamp}. Comment: {dcs.comment or '-'}")
                if case.purchase_confirmed:
                    q = case.chosen_quote
                    st.success(f"Purchase confirmed with {q.supplier}: {q.total_price:,.2f} {q.currency}, "
                               f"delivery {q.delivery_date.isoformat()}.")
                po = case.purchase_order
                if po is not None:
                    st.success(f"Purchase order **{po.po_number}** issued at {po.issued_at}.")
                    with st.container(border=True):
                        st.markdown(po.to_markdown())
                    try:
                        st.download_button("Download PO (PDF)", svc.po_pdf(case.case_id),
                                           file_name=f"{po.po_number}.pdf", mime="application/pdf",
                                           key=f"dl_{case.case_id}")
                    except (ApprovalError, OSError) as exc:
                        st.error(f"PO PDF is not available: {exc}")
                elif case.status == APPROVED:
                    if case.po_error:
                        st.error(f"Purchase order could not be generated: {case.po_error}")
                    if user.role == APPROVER and st.button("Generate purchase order", key=f"po_{case.case_id}"):
                        try:
                            svc.issue_po(case.case_id, user)
                            st.rerun()
                        except ApprovalError as exc:
                            st.error(str(exc))
            elif user.role == APPROVER:
                suppliers = [s.quote.supplier for s in rec.comparison.ranked]
                chosen = st.selectbox("Supplier", suppliers, index=0, key=f"sup_{case.case_id}")
                comment = st.text_input("Comment (required to reject or to choose another supplier)",
                                        key=f"cmt_{case.case_id}")
                c1, c2 = st.columns(2)
                for col, label, approve in ((c1, "Approve", True), (c2, "Reject", False)):
                    if col.button(label, key=f"{label.lower()}_{case.case_id}"):
                        try:
                            svc.decide(case.case_id, user, approve, comment, chosen)
                            st.rerun()
                        except ApprovalError as exc:
                            st.error(str(exc))


def render(agent: ProcurementAgent, svc: ApprovalService, today: date | None = None) -> None:
    st.set_page_config(page_title="Procurement Agent", layout="wide")
    st.title("Intelligent Procurement Agent")
    today = today or date.today()

    with st.sidebar:
        st.header("Signed in as")
        name = st.text_input("Name", value="alice", key="user_name").strip() or "anonymous"
        role = st.radio("Role", [REQUESTER, APPROVER], key="user_role")
        st.caption("Demo only: this selector stands in for real authentication.")
    user = User(name, role)

    tab_new, tab_cases = st.tabs(["New request", "Approvals"])
    with tab_new:
        _new_request_tab(agent, svc, user, today)
    with tab_cases:
        _approvals_tab(svc, user)
