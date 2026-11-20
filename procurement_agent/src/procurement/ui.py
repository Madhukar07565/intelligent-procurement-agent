"""Streamlit screens. `render` takes its collaborators so tests can inject fakes.

All session keys owned by the UI start with "ui_" so sign-out can clear them.
"""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from .agent import ProcurementAgent, validate_fields
from .approval import APPROVED, APPROVER, PENDING, PO_ISSUED, REJECTED, REQUESTER, ApprovalError, ApprovalService, Case
from .auth import Account, AuthError, UserStore
from .models import Recommendation

EXAMPLE = "I need 50 laptops delivered by December 15"

STATUS_LABEL = {
    PENDING: "Awaiting approval. No purchase made.",
    APPROVED: "Approved. Purchase order not yet issued.",
    PO_ISSUED: "Approved. Purchase order issued.",
    REJECTED: "Rejected. No purchase made.",
}
STATUS_BADGE = {
    PENDING: ":orange[Pending approval]",
    APPROVED: ":blue[Approved]",
    PO_ISSUED: ":green[PO issued]",
    REJECTED: ":red[Rejected]",
}
THEME = {
    REQUESTER: ("Requester workspace", "Create purchase requests and track their status.", "#1f6feb", "#e8f0fe"),
    APPROVER: ("Approver workspace", "Review recommendations, approve or reject, and issue purchase orders.",
               "#b35900", "#fff4e5"),
}


# ---------------------------------------------------------------- shared pieces
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


def _case_title(case: Case) -> str:
    req = case.recommendation.request
    return (f"{case.case_id} · {req.quantity} x {req.product} by {req.required_date.isoformat()} · "
            f"{STATUS_BADGE[case.status]}")


def _case_value(case: Case) -> float:
    q = case.chosen_quote or case.recommendation.comparison.recommended.quote
    return q.total_price


def _show_outcome(svc: ApprovalService, case: Case) -> None:
    """Decision, confirmation and PO download. Read-only, used by both roles."""
    st.markdown(f"**Status:** {STATUS_LABEL[case.status]}")
    if not case.decision:
        return
    d = case.decision
    st.caption(f"Decision by {d.approver} at {d.timestamp[:19].replace('T', ' ')} UTC. "
               f"Comment: {d.comment or '-'}")
    if case.purchase_confirmed:
        q = case.chosen_quote
        st.success(f"Purchase confirmed with {q.supplier}: {q.total_price:,.2f} {q.currency}, "
                   f"delivery {q.delivery_date.isoformat()}.")
    po = case.purchase_order
    if po is not None:
        st.success(f"Purchase order **{po.po_number}** issued at {po.issued_at[:19].replace('T', ' ')} UTC.")
        try:
            st.download_button("Download PO (PDF)", svc.po_pdf(case.case_id), file_name=f"{po.po_number}.pdf",
                               mime="application/pdf", key=f"ui_dl_{case.case_id}")
        except (ApprovalError, OSError) as exc:
            st.error(f"PO PDF is not available: {exc}")
    elif case.status == APPROVED and case.po_error:
        st.error(f"Purchase order could not be generated: {case.po_error}")


def _banner(account: Account) -> None:
    title, subtitle, fg, bg = THEME[account.role]
    st.markdown(
        f"<div style='background:{bg};border-left:6px solid {fg};padding:0.8rem 1rem;border-radius:6px;"
        f"margin-bottom:1rem'><span style='color:{fg};font-weight:700;font-size:1.25rem'>{title}</span>"
        f"<br><span style='color:#333'>{subtitle}</span></div>",
        unsafe_allow_html=True,  # static strings only, no user input
    )


# ---------------------------------------------------------------- login
def _login_screen(users: UserStore) -> None:
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.title("Intelligent Procurement Agent")
        st.subheader("Sign in")
        with st.form("ui_login_form"):
            username = st.text_input("Username", key="ui_login_user")
            password = st.text_input("Password", type="password", key="ui_login_pass")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            try:
                st.session_state["ui_account"] = users.authenticate(username, password)
                st.session_state.pop("ui_login_pass", None)
                st.rerun()
            except AuthError as exc:
                st.error(str(exc))
        st.caption("Requesters and approvers have separate accounts. Ask an administrator for access.")


def _sign_out() -> None:
    for key in [k for k in st.session_state.keys() if str(k).startswith("ui_")]:
        del st.session_state[key]


# ---------------------------------------------------------------- requester
def _new_request_tab(agent: ProcurementAgent, svc: ApprovalService, account: Account, today: date) -> None:
    ss = st.session_state
    text = st.text_area("Describe what you need", key="ui_request_text", placeholder=EXAMPLE)
    if st.button("Extract details", key="ui_extract_btn", type="primary"):
        ss.pop("ui_rec", None)
        ss.pop("ui_submitted_case", None)
        try:
            ss["ui_extraction"] = agent.extract_request(text, today, requester=account.username)
        except Exception as exc:  # network, credentials, throttling
            ss.pop("ui_extraction", None)
            st.error(f"The AI service failed: {exc}")

    ext = ss.get("ui_extraction")
    if ext is None:
        return

    if ext.ok:
        st.subheader("Confirm details")
        d = {"product": ext.request.product, "quantity": ext.request.quantity, "date": ext.request.required_date}
    else:
        st.subheader("Details needed")
        for name in ext.missing:
            st.warning(f"Missing: {name.replace('_', ' ')}")
        for err in ext.errors:
            st.warning(err)
        st.caption("Fill in the fields below or rephrase your request.")
        d = {"product": "", "quantity": 1, "date": today + timedelta(days=14)}

    with st.form("ui_confirm_form"):
        product = st.text_input("Product", value=d["product"])
        quantity = st.number_input("Quantity", min_value=0, value=int(d["quantity"]), step=1)
        required = st.date_input("Required delivery date", value=d["date"])
        confirmed = st.form_submit_button("Confirm and get quotes")

    if confirmed:
        check = validate_fields(product, quantity, required, today, raw_text=text, requester=account.username)
        if not check.ok:
            for err in check.errors + [f"Missing: {m}" for m in check.missing]:
                st.error(err)
        else:
            try:
                with st.spinner("Retrieving and comparing quotations..."):
                    ss["ui_rec"] = agent.recommend(check.request, today)
                ss.pop("ui_submitted_case", None)
            except Exception as exc:
                ss.pop("ui_rec", None)
                st.error(f"Could not produce a recommendation: {exc}")

    rec = ss.get("ui_rec")
    if rec is not None:
        st.subheader("Recommendation")
        _show_recommendation(rec, agent.available_products())
        if rec.comparison.recommended is not None:
            case_id = ss.get("ui_submitted_case")
            if case_id:
                st.info(f"Submitted for approval. Case ID: **{case_id}**. No purchase has been made. "
                        "Track it under My requests.")
            elif st.button("Submit for approval", key="ui_submit_btn", type="primary"):
                try:
                    ss["ui_submitted_case"] = svc.submit(rec, account.username)
                    st.rerun()
                except ApprovalError as exc:
                    st.error(str(exc))


def _my_requests_tab(svc: ApprovalService, account: Account) -> None:
    cases = svc.list_cases(submitted_by=account.username)
    if not cases:
        st.info("You have not submitted any requests yet.")
        return
    counts = {s: sum(c.status == s for c in cases) for s in STATUS_LABEL}
    m = st.columns(4)
    m[0].metric("Submitted", len(cases))
    m[1].metric("Pending", counts[PENDING])
    m[2].metric("Approved", counts[APPROVED] + counts[PO_ISSUED])
    m[3].metric("Rejected", counts[REJECTED])
    for case in reversed(cases):
        with st.expander(_case_title(case), expanded=False):
            st.caption(f"Submitted {case.submitted_at[:19].replace('T', ' ')} UTC. "
                       f"Original request: \"{case.recommendation.request.raw_text}\"")
            _show_recommendation(case.recommendation)
            _show_outcome(svc, case)


def _requester_home(agent, svc, account, today) -> None:
    mine = svc.list_cases(submitted_by=account.username)
    tab_new, tab_mine = st.tabs(["New request", f"My requests ({len(mine)})"])
    with tab_new:
        _new_request_tab(agent, svc, account, today)
    with tab_mine:
        _my_requests_tab(svc, account)


# ---------------------------------------------------------------- approver
def _approval_queue_tab(svc: ApprovalService, account: Account) -> None:
    pending = svc.list_cases(statuses=[PENDING])
    if not pending:
        st.success("No requests are waiting for approval.")
        return
    user = account.as_user()
    for case in pending:  # oldest first
        rec = case.recommendation
        own = case.submitted_by == account.username
        with st.expander(_case_title(case), expanded=True):
            st.write(f"Requested by **{case.submitted_by}** on {case.submitted_at[:10]}. "
                     f"Original request: \"{rec.request.raw_text}\"")
            _show_recommendation(rec)
            if own:
                st.warning("You submitted this request, so another approver must decide it.")
                continue
            suppliers = [s.quote.supplier for s in rec.comparison.ranked]
            chosen = st.selectbox("Supplier", suppliers, index=0, key=f"ui_sup_{case.case_id}")
            comment = st.text_input("Comment (required to reject or to choose another supplier)",
                                    key=f"ui_cmt_{case.case_id}")
            c1, c2 = st.columns(2)
            if c1.button("Approve", key=f"ui_approve_{case.case_id}", type="primary", use_container_width=True):
                _decide(svc, case.case_id, user, True, comment, chosen)
            if c2.button("Reject", key=f"ui_reject_{case.case_id}", use_container_width=True):
                _decide(svc, case.case_id, user, False, comment, chosen)


def _decide(svc, case_id, user, approve, comment, chosen) -> None:
    try:
        svc.decide(case_id, user, approve, comment, chosen)
        st.rerun()
    except ApprovalError as exc:
        st.error(str(exc))


def _history_tab(svc: ApprovalService, account: Account) -> None:
    decided = svc.list_cases(statuses=[APPROVED, PO_ISSUED, REJECTED])
    if not decided:
        st.info("No decisions yet.")
        return
    for case in reversed(decided):  # newest first
        with st.expander(_case_title(case), expanded=False):
            st.write(f"Requested by **{case.submitted_by}**.")
            _show_recommendation(case.recommendation)
            _show_outcome(svc, case)
            if case.status == APPROVED and case.purchase_order is None:
                if st.button("Generate purchase order", key=f"ui_po_{case.case_id}"):
                    try:
                        svc.issue_po(case.case_id, account.as_user())
                        st.rerun()
                    except ApprovalError as exc:
                        st.error(str(exc))


def _approver_home(svc: ApprovalService, account: Account) -> None:
    all_cases = svc.list_cases()
    pending = [c for c in all_cases if c.status == PENDING]
    approved = [c for c in all_cases if c.status in (APPROVED, PO_ISSUED)]
    m = st.columns(4)
    m[0].metric("Waiting for approval", len(pending))
    m[1].metric("Value waiting", f"{sum(_case_value(c) for c in pending):,.0f} USD")
    m[2].metric("Approved", len(approved))
    m[3].metric("POs issued", sum(c.status == PO_ISSUED for c in all_cases))
    tab_queue, tab_hist = st.tabs([f"Approval queue ({len(pending)})", "Decision history"])
    with tab_queue:
        _approval_queue_tab(svc, account)
    with tab_hist:
        _history_tab(svc, account)


# ---------------------------------------------------------------- entry point
def render(agent: ProcurementAgent, svc: ApprovalService, users: UserStore, today: date | None = None) -> None:
    st.set_page_config(page_title="Procurement Agent", layout="wide")
    today = today or date.today()
    account: Account | None = st.session_state.get("ui_account")
    if account is None:
        _login_screen(users)
        return

    with st.sidebar:
        st.markdown(f"### {account.display_name}")
        st.caption(f"@{account.username} · {account.role.capitalize()}")
        if st.button("Sign out", key="ui_signout", use_container_width=True):
            _sign_out()
            st.rerun()

    st.title("Intelligent Procurement Agent")
    _banner(account)
    if account.role == REQUESTER:
        _requester_home(agent, svc, account, today)
    elif account.role == APPROVER:
        _approver_home(svc, account)
    else:
        st.error("Your account has no valid role. Contact an administrator.")
