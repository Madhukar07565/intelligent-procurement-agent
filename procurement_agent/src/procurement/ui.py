"""Streamlit screens. `render` takes its collaborators so tests can inject fakes.

All session keys owned by the UI start with "ui_" so sign-out can clear them.
Custom HTML is used for cards and banners. Every dynamic value placed in HTML
goes through `esc()` first; the AI explanation and supplier data are untrusted.
"""
from __future__ import annotations

import html
from datetime import date, datetime, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

from .agent import ProcurementAgent, validate_fields
from .approval import APPROVED, APPROVER, PENDING, PO_ISSUED, REJECTED, REQUESTER, ApprovalError, ApprovalService, Case
from .auth import Account, AuthError, UserStore
from .notifications import AlertStore
from .models import Recommendation, ScoredQuote

EXAMPLES = [
    ("💻  50 laptops by Dec 15", "I need 50 laptops delivered by December 15"),
    ("🖥️  10 monitors by Dec 20", "We need 10 monitors by December 20"),
    ("🪑  15 office chairs by Jan 10", "Order 15 office chairs by January 10"),
]
STEPS = ["Describe the need", "Confirm details", "Compare suppliers", "Submit for approval"]

STATUS_LABEL = {
    PENDING: "Awaiting approval. No purchase made.",
    APPROVED: "Approved. Purchase order not yet issued.",
    PO_ISSUED: "Approved. Purchase order issued.",
    REJECTED: "Rejected. No purchase made.",
}
STATUS_BADGE = {
    PENDING: "🟠 :orange[Pending approval]",
    APPROVED: "🔵 :blue[Approved]",
    PO_ISSUED: "🟢 :green[PO issued]",
    REJECTED: "🔴 :red[Rejected]",
}
# role -> (title, subtitle, gradient start, gradient end, icon)
THEME = {
    REQUESTER: ("Requester workspace", "Describe what you need. The agent finds and compares supplier quotes.",
                "#4f46e5", "#0ea5e9", "🛒"),
    APPROVER: ("Approver workspace", "Review recommendations, approve or reject, and issue purchase orders.",
               "#b45309", "#f43f5e", "✅"),
}
CHART_COLORS = {"Recommended": "#16a34a", "On time": "#6366f1", "Late": "#ef4444"}

CSS = """
<style>
#MainMenu, footer {visibility: hidden;}
header[data-testid="stHeader"] {background: transparent;}
.block-container {padding-top: 1.6rem; max-width: 1180px;}
[data-testid="stSidebar"] {background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);}
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] li,
[data-testid="stSidebar"] h3, [data-testid="stSidebar"] div {color: #e2e8f0;}
[data-testid="stSidebar"] .stButton button {background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.25);}
[data-testid="stSidebar"] .stButton button:hover {background: rgba(255,255,255,.16); border-color: #fff;}
[data-testid="stMetric"] {background: #fff; border: 1px solid #e5e7eb; border-radius: 14px; padding: 14px 18px;
  box-shadow: 0 1px 3px rgba(16,24,40,.06);}
[data-testid="stMetricLabel"] p {color: #64748b; font-weight: 700; text-transform: uppercase; font-size: .72rem;
  letter-spacing: .05em;}
[data-testid="stMetricValue"] {color: #0f172a; font-weight: 800;}
[data-testid="stExpander"] details {background: #fff; border: 1px solid #e5e7eb; border-radius: 14px;
  box-shadow: 0 1px 3px rgba(16,24,40,.06);}
[data-testid="stExpander"] summary p {font-weight: 600; font-size: 1rem;}
[data-testid="stForm"] {background: #fff; border: 1px solid #e5e7eb; border-radius: 14px;}
.stButton button, [data-testid="stFormSubmitButton"] button, [data-testid="stDownloadButton"] button {
  border-radius: 10px; font-weight: 600;}
[data-testid="stTabs"] [role="tab"] p {font-weight: 700; font-size: 1rem;}
[data-testid="stTextArea"] textarea {border-radius: 12px; font-size: 1rem;}
.pa-hero {border-radius: 18px; padding: 22px 26px; margin-bottom: 18px; color: #fff; display: flex;
  justify-content: space-between; align-items: center; gap: 16px; box-shadow: 0 12px 28px -14px rgba(15,23,42,.55);}
.pa-hero .t {font-size: 1.6rem; font-weight: 800; line-height: 1.2;}
.pa-hero .s {opacity: .92; margin-top: 4px;}
.pa-role {background: rgba(255,255,255,.18); border: 1px solid rgba(255,255,255,.4); padding: 7px 14px;
  border-radius: 999px; font-weight: 700; white-space: nowrap;}
.pa-section {font-weight: 800; color: #0f172a; font-size: 1.08rem; margin: 18px 0 8px;}
.pa-steps {display: flex; gap: 10px; margin: 2px 0 18px; flex-wrap: wrap;}
.pa-step {flex: 1; min-width: 150px; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px;
  padding: 10px 12px; color: #64748b; font-weight: 600; font-size: .9rem; display: flex; align-items: center; gap: 9px;}
.pa-step .n {width: 26px; height: 26px; border-radius: 50%; background: #e5e7eb; color: #475569; flex: none;
  display: inline-flex; align-items: center; justify-content: center; font-size: .8rem; font-weight: 800;}
.pa-step.done {color: #166534;} .pa-step.done .n {background: #16a34a; color: #fff;}
.pa-step.active {border-color: #4f46e5; color: #0f172a; box-shadow: 0 0 0 3px #e0e7ff;}
.pa-step.active .n {background: #4f46e5; color: #fff;}
.pa-winner {background: linear-gradient(135deg, #ecfdf5 0%, #ffffff 70%); border: 1px solid #86efac;
  border-radius: 16px; padding: 18px 22px; margin: 6px 0 12px;}
.pa-winner.late {background: linear-gradient(135deg, #fff7ed 0%, #ffffff 70%); border-color: #fdba74;}
.pa-winner .top {display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;}
.pa-winner .name {font-size: 1.55rem; font-weight: 800; color: #0f172a; margin: 8px 0 2px;}
.pa-winner .why {color: #475569; font-size: .93rem;}
.pa-kpis {display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 14px;}
.pa-kpi {background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 10px 12px;}
.pa-kpi .k {font-size: .7rem; text-transform: uppercase; letter-spacing: .05em; color: #64748b; font-weight: 800;}
.pa-kpi .v {font-size: 1.08rem; font-weight: 800; color: #0f172a; margin-top: 3px;}
.pa-pill {display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: .75rem; font-weight: 800;}
.pa-green {background: #dcfce7; color: #166534;} .pa-red {background: #fee2e2; color: #991b1b;}
.pa-amber {background: #fef3c7; color: #92400e;} .pa-blue {background: #e0e7ff; color: #3730a3;}
.pa-gray {background: #f1f5f9; color: #475569;}
.pa-ai {background: #f5f3ff; border: 1px solid #ddd6fe; border-radius: 14px; padding: 14px 18px;
  margin: 8px 0 14px; color: #1e1b4b; line-height: 1.5;}
.pa-ai .lbl {font-size: .7rem; font-weight: 800; letter-spacing: .06em; text-transform: uppercase; color: #6d28d9;
  margin-bottom: 6px;}
.pa-alt {background: #fff; border: 1px solid #e5e7eb; border-radius: 14px; padding: 12px 14px; margin-bottom: 8px;}
.pa-alt .name {font-weight: 800; color: #0f172a; margin-bottom: 6px; display: flex; justify-content: space-between;
  gap: 6px; align-items: center;}
.pa-alt .row {display: flex; justify-content: space-between; font-size: .88rem; color: #475569; margin-top: 3px;}
.pa-alt .row b {color: #0f172a;}
.pa-facts {display: flex; flex-wrap: wrap; gap: 8px; margin: 2px 0 10px;}
.pa-fact {background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 6px 10px; font-size: .86rem;
  color: #475569;}
.pa-fact b {color: #0f172a;}
.pa-timeline {display: flex; align-items: flex-start; margin: 12px 0 10px;}
.pa-tl {display: flex; flex-direction: column; align-items: center; width: 150px; text-align: center; flex: none;}
.pa-tl .dot {width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-weight: 800; font-size: .85rem; background: #e5e7eb; color: #64748b;}
.pa-tl.done .dot {background: #16a34a; color: #fff;} .pa-tl.fail .dot {background: #dc2626; color: #fff;}
.pa-tl.wait .dot {background: #f59e0b; color: #fff;}
.pa-tl .t {font-weight: 800; font-size: .82rem; color: #0f172a; margin-top: 5px;}
.pa-tl .s {font-size: .74rem; color: #64748b;}
.pa-line {flex: 1; height: 3px; background: #e5e7eb; margin-top: 14px; border-radius: 2px; min-width: 20px;}
.pa-line.done {background: #16a34a;}
.pa-login {border-radius: 20px; padding: 36px 34px; color: #fff; min-height: 430px;
  background: linear-gradient(140deg, #312e81 0%, #4f46e5 55%, #0ea5e9 100%);
  box-shadow: 0 18px 40px -18px rgba(49,46,129,.7);}
.pa-login .t {font-size: 2.05rem; font-weight: 800; line-height: 1.15;}
.pa-login .s {opacity: .92; margin: 10px 0 22px; font-size: 1.02rem;}
.pa-feat {display: flex; gap: 12px; align-items: flex-start; margin: 16px 0;}
.pa-feat .i {font-size: 1.25rem; background: rgba(255,255,255,.16); border-radius: 12px; width: 42px; height: 42px;
  display: flex; align-items: center; justify-content: center; flex: none;}
.pa-feat b {display: block;} .pa-feat span {opacity: .85; font-size: .9rem;}
.pa-avatar {width: 58px; height: 58px; border-radius: 50%; color: #fff; display: flex; align-items: center;
  justify-content: center; font-weight: 800; font-size: 1.35rem; margin: 6px 0 10px;}
.pa-side-name {font-weight: 800; font-size: 1.1rem;}
.pa-side-sub {font-size: .85rem; opacity: .75; margin-bottom: 12px;}
.pa-howto {font-size: .86rem; line-height: 1.7; opacity: .9;}
.pa-empty {background: #fff; border: 1px dashed #cbd5e1; border-radius: 14px; padding: 28px; text-align: center;
  color: #64748b;}
.pa-empty .i {font-size: 2rem;}
.pa-alerts {background: linear-gradient(135deg, #fff7ed 0%, #ffffff 80%); border: 1px solid #fdba74;
  border-left: 6px solid #f97316; border-radius: 14px; padding: 14px 18px; margin: 4px 0 14px;}
.pa-alerts .h {font-weight: 800; color: #9a3412; font-size: 1.05rem; margin-bottom: 6px;}
.pa-alert {display: flex; gap: 10px; align-items: baseline; padding: 6px 0; border-top: 1px dashed #fed7aa;
  color: #431407; font-size: .92rem;}
.pa-alert:first-of-type {border-top: none;}
.pa-alert .id {font-weight: 800; white-space: nowrap;} .pa-alert .tm {color: #9a3412; font-size: .78rem;
  white-space: nowrap; margin-left: auto;}
.pa-bell {display: inline-block; background: #f97316; color: #fff; border-radius: 999px; padding: 4px 12px;
  font-weight: 800; font-size: .85rem; margin-bottom: 10px;}
</style>
"""


# ---------------------------------------------------------------- helpers
def esc(value) -> str:
    return html.escape(str(value), quote=True)


def _html(markup: str) -> None:
    """Render trusted markup. Callers must pass dynamic values through esc()."""
    st.markdown(markup, unsafe_allow_html=True)


def _money(amount: float, currency: str) -> str:
    return f"{amount:,.2f} {currency}"


def _ts(iso: str) -> str:
    return iso[:16].replace("T", " ") + " UTC" if iso else "-"


def _timing(s: ScoredQuote, required: date) -> tuple[str, str]:
    """(pill css class, text) describing delivery against the deadline."""
    if not s.eligible:
        return "pa-red", f"{s.days_late} day(s) late"
    early = (required - s.quote.delivery_date).days
    return "pa-green", ("On the deadline" if early == 0 else f"On time · {early} day(s) early")


def _section(title: str) -> None:
    _html(f'<div class="pa-section">{esc(title)}</div>')


def _empty(icon: str, text: str) -> None:
    _html(f'<div class="pa-empty"><div class="i">{icon}</div>{esc(text)}</div>')


# ---------------------------------------------------------------- recommendation views
def _winner_card(rec: Recommendation) -> None:
    best = rec.comparison.recommended
    q = best.quote
    pill_cls, timing = _timing(best, rec.request.required_date)
    if best.eligible:
        badge, card_cls = '<span class="pa-pill pa-green">🏆 Recommended supplier</span>', "pa-winner"
        score = f'<span class="pa-pill pa-blue">Score {best.score:.0f} / 100</span>'
    else:
        badge = '<span class="pa-pill pa-amber">⚠️ Closest option: misses the deadline</span>'
        card_cls, score = "pa-winner late", '<span class="pa-pill pa-gray">Not scored</span>'
    why = rec.comparison.versus_runner_up() or "Only one valid quotation was available."
    kpis = [
        ("Total cost", _money(q.total_price, q.currency)),
        ("Unit price", _money(q.unit_price, q.currency)),
        ("Delivery date", q.delivery_date.isoformat()),
        ("Vs deadline", timing),
    ]
    kpi_html = "".join(f'<div class="pa-kpi"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>'
                       for k, v in kpis)
    _html(
        f'<div class="{card_cls}"><div class="top">{badge}{score}</div>'
        f'<div class="name">{esc(q.supplier)}</div>'
        f'<div class="why">{esc(why)} Quotation {esc(q.quote_ref)}, valid until {esc(q.valid_until.isoformat())}.</div>'
        f'<div class="pa-kpis">{kpi_html}</div></div>'
    )


def _ai_explanation(rec: Recommendation) -> None:
    text = esc(rec.explanation).replace("\n", "<br>")
    _html(f'<div class="pa-ai"><div class="lbl">✨ AI explanation · Amazon Bedrock</div>{text}</div>')


def _alternative_cards(rec: Recommendation) -> None:
    others = rec.comparison.ranked[1:]
    if not others:
        return
    _section("Other quotations")
    cols = st.columns(min(3, len(others)))
    for i, s in enumerate(others):
        q = s.quote
        pill_cls, timing = _timing(s, rec.request.required_date)
        score = f"{s.score:.0f}" if s.eligible else "-"
        with cols[i % len(cols)]:
            _html(
                f'<div class="pa-alt"><div class="name">#{i + 2} {esc(q.supplier)}'
                f'<span class="pa-pill {pill_cls}">{esc(timing)}</span></div>'
                f'<div class="row">Total <b>{esc(_money(q.total_price, q.currency))}</b></div>'
                f'<div class="row">Delivery <b>{esc(q.delivery_date.isoformat())}</b></div>'
                f'<div class="row">Score <b>{esc(score)}</b></div></div>'
            )


def _chart_frame(rec: Recommendation) -> pd.DataFrame:
    rows = []
    for i, s in enumerate(rec.comparison.ranked):
        q = s.quote
        status = "Recommended" if i == 0 else ("On time" if s.eligible else "Late")
        rows.append({
            "Supplier": q.supplier, "Total price": q.total_price, "Status": status,
            "Ordered": (q.delivery_date - timedelta(days=q.lead_time_days)).isoformat(),
            "Delivery": q.delivery_date.isoformat(), "Lead time (days)": q.lead_time_days,
        })
    return pd.DataFrame(rows)


def _charts(rec: Recommendation) -> None:
    df = _chart_frame(rec)
    currency = rec.comparison.ranked[0].quote.currency
    color = alt.Color("Status:N", scale=alt.Scale(domain=list(CHART_COLORS), range=list(CHART_COLORS.values())),
                      legend=alt.Legend(orient="bottom", title=None))
    row = alt.Step(44)  # pixels per supplier row
    height = 150 + 44 * len(df)  # outer height incl. title, axis and legend
    price = alt.Chart(df, title="Total price").mark_bar(cornerRadiusEnd=6).encode(
        x=alt.X("Total price:Q", title=currency, axis=alt.Axis(format=",.0f")),
        y=alt.Y("Supplier:N", sort="x", title=None),
        color=color,
        tooltip=["Supplier", alt.Tooltip("Total price:Q", format=",.2f"), "Status"],
    ).properties(height=row)
    bars = alt.Chart(df).mark_bar(cornerRadius=6).encode(
        x=alt.X("Ordered:T", title=None, axis=alt.Axis(format="%b %d")),
        x2="Delivery:T",
        y=alt.Y("Supplier:N", sort=alt.EncodingSortField("Delivery", order="ascending"), title=None),
        color=color,
        tooltip=["Supplier", "Delivery", "Lead time (days)", "Status"],
    )
    deadline = pd.DataFrame({"Deadline": [rec.request.required_date.isoformat()], "label": ["Deadline"]})
    rule = alt.Chart(deadline).mark_rule(color="#0f172a", strokeDash=[5, 4], strokeWidth=2).encode(x="Deadline:T")
    rule_label = alt.Chart(deadline).mark_text(align="left", dx=5, dy=-6, fontWeight="bold", color="#0f172a").encode(
        x="Deadline:T", y=alt.value(0), text="label:N")
    delivery = alt.layer(bars, rule, rule_label, title="Delivery window vs deadline").properties(height=row)
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.altair_chart(price, width="stretch", height=height)
    with c2, st.container(border=True):
        st.altair_chart(delivery, width="stretch", height=height)


def _ranking_table(rec: Recommendation) -> None:
    rows = []
    for i, s in enumerate(rec.comparison.ranked, start=1):
        q = s.quote
        rows.append({
            "Rank": i, "Supplier": q.supplier, "Total price": q.total_price, "Unit price": q.unit_price,
            "Delivery date": q.delivery_date.isoformat(),
            "On time": "✅ Yes" if s.eligible else f"❌ {s.days_late} day(s) late",
            "Score": round(s.score, 1) if s.eligible else None, "Quote ref": q.quote_ref,
        })
    cur = rec.comparison.ranked[0].quote.currency
    st.dataframe(
        rows, hide_index=True, width="stretch",
        column_config={
            "Rank": st.column_config.NumberColumn(width="small"),
            "Total price": st.column_config.NumberColumn(format=f"%,.2f {cur}"),
            "Unit price": st.column_config.NumberColumn(format=f"%,.2f {cur}"),
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
        },
    )


def _show_recommendation(rec: Recommendation, available_products: list[str] | None = None,
                         full: bool = True) -> None:
    """full=True adds alternative cards and charts (requester view); compact otherwise."""
    if rec.comparison.recommended is None:
        st.error(f"No quotations are available for \"{rec.request.product}\".")
        for e in rec.excluded:
            st.caption(f"Excluded: {e['supplier']} ({e['quote_ref']}), {e['reason']}")
        if available_products and not rec.excluded:
            st.info("Products with supplier quotations: " + ", ".join(available_products)
                    + ". Edit the product above and confirm again.")
        return
    _winner_card(rec)
    _ai_explanation(rec)
    for w in rec.comparison.warnings:
        st.warning(w)
    if full:
        _alternative_cards(rec)
        _charts(rec)
    _section("Full comparison")
    _ranking_table(rec)
    for e in rec.excluded:
        st.caption(f"Excluded: {e['supplier']} ({e['quote_ref']}), {e['reason']}")
    st.caption("Ranking: 60% price, 40% delivery, among suppliers that meet the required date. "
               "Scores are calculated by the app, not by the AI.")


# ---------------------------------------------------------------- case views
def _case_title(case: Case) -> str:
    req = case.recommendation.request
    return (f"{case.case_id} · {req.quantity} x {req.product} by {req.required_date.isoformat()} · "
            f"{STATUS_BADGE[case.status]}")


def _case_value(case: Case) -> float:
    q = case.chosen_quote or case.recommendation.comparison.recommended.quote
    return q.total_price


def _days_waiting(case: Case) -> int:
    try:
        submitted = datetime.fromisoformat(case.submitted_at)
    except ValueError:
        return 0
    return max(0, (datetime.now(timezone.utc) - submitted).days)


def _case_facts(case: Case, show_requester: bool = True) -> None:
    req = case.recommendation.request
    q = case.recommendation.comparison.recommended.quote
    facts = []
    if show_requester:
        facts.append(("👤 Requested by", case.submitted_by))
    facts += [
        ("📦 Item", f"{req.quantity} x {req.product}"),
        ("📅 Needed by", req.required_date.isoformat()),
        ("💰 Value", _money(_case_value(case), q.currency)),
        ("🕒 Submitted", _ts(case.submitted_at)),
    ]
    chips = "".join(f'<div class="pa-fact">{esc(k)} <b>{esc(v)}</b></div>' for k, v in facts)
    _html(f'<div class="pa-facts">{chips}</div>')
    if req.raw_text:
        st.caption(f"Original request: \u201c{req.raw_text}\u201d")


def _timeline(case: Case) -> None:
    d = case.decision
    steps = [("done", "✓", "Submitted", _ts(case.submitted_at))]
    if case.status == PENDING:
        steps.append(("wait", "2", "Awaiting decision", "approver review"))
        steps.append(("", "3", "Purchase order", "not issued"))
    elif case.status == REJECTED:
        steps.append(("fail", "✕", "Rejected", f"by {d.approver}"))
        steps.append(("", "3", "Purchase order", "not issued"))
    else:
        steps.append(("done", "✓", "Approved", f"by {d.approver}"))
        if case.purchase_order is not None:
            steps.append(("done", "✓", "PO issued", case.purchase_order.po_number))
        else:
            steps.append(("fail" if case.po_error else "wait", "3", "Purchase order",
                          "generation failed" if case.po_error else "pending"))
    parts = []
    for i, (cls, mark, title, sub) in enumerate(steps):
        if i:
            parts.append(f'<div class="pa-line {"done" if cls == "done" else ""}"></div>')
        parts.append(f'<div class="pa-tl {cls}"><div class="dot">{esc(mark)}</div>'
                     f'<div class="t">{esc(title)}</div><div class="s">{esc(sub)}</div></div>')
    _html(f'<div class="pa-timeline">{"".join(parts)}</div>')


def _show_outcome(svc: ApprovalService, case: Case) -> None:
    """Timeline, decision, confirmation and PO download. Read-only, used by both roles."""
    _timeline(case)
    st.markdown(f"**Status:** {STATUS_LABEL[case.status]}")
    if not case.decision:
        return
    d = case.decision
    st.caption(f"Decision by {d.approver} at {_ts(d.timestamp)}. Comment: {d.comment or '-'}")
    if case.purchase_confirmed:
        q = case.chosen_quote
        st.success(f"Purchase confirmed with {q.supplier}: {q.total_price:,.2f} {q.currency}, "
                   f"delivery {q.delivery_date.isoformat()}.")
    po = case.purchase_order
    if po is not None:
        st.success(f"Purchase order **{po.po_number}** issued at {_ts(po.issued_at)}.")
        try:
            st.download_button("Download PO (PDF)", svc.po_pdf(case.case_id), file_name=f"{po.po_number}.pdf",
                               mime="application/pdf", key=f"ui_dl_{case.case_id}", type="primary",
                               icon=":material/picture_as_pdf:")
        except (ApprovalError, OSError) as exc:
            st.error(f"PO PDF is not available: {exc}")
    elif case.status == APPROVED and case.po_error:
        st.error(f"Purchase order could not be generated: {case.po_error}")


# ---------------------------------------------------------------- page chrome
def _hero(account: Account) -> None:
    title, subtitle, c1, c2, icon = THEME[account.role]
    _html(
        f'<div class="pa-hero" style="background: linear-gradient(120deg, {c1} 0%, {c2} 100%);">'
        f'<div><div class="t">{icon} {esc(title)}</div><div class="s">{esc(subtitle)}</div></div>'
        f'<div class="pa-role">{esc(account.display_name)} · {esc(account.role.capitalize())}</div></div>'
    )


def _sidebar(account: Account, unread: int = 0) -> None:
    _, _, c1, c2, _ = THEME[account.role]
    initials = "".join(p[0] for p in account.display_name.split()[:2]).upper() or "?"
    how = ("1. Describe what you need<br>2. Confirm the details<br>3. Review the AI recommendation<br>"
           "4. Submit for approval" if account.role == REQUESTER else
           "1. Open the approval queue<br>2. Review price and delivery<br>3. Approve or reject<br>"
           "4. Download the PDF purchase order")
    with st.sidebar:
        _html(f'<div class="pa-avatar" style="background: linear-gradient(135deg, {c1}, {c2});">{esc(initials)}</div>'
              f'<div class="pa-side-name">{esc(account.display_name)}</div>'
              f'<div class="pa-side-sub">@{esc(account.username)} · {esc(account.role.capitalize())}</div>')
        if unread:
            _html(f'<div class="pa-bell">🔔 {unread} new request{"s" if unread != 1 else ""}</div>')
        if st.button("Sign out", key="ui_signout", width="stretch", icon=":material/logout:"):
            _sign_out()
            st.rerun()
        st.divider()
        _html(f'<div class="pa-howto"><b>How it works</b><br>{how}</div>')
        st.divider()
        st.caption("Powered by Amazon Bedrock (us-east-1). Demo uses synthetic supplier data.")


# ---------------------------------------------------------------- login
def _login_screen(users: UserStore) -> None:
    st.write("")
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        features = [
            ("💬", "Ask in plain English", "Amazon Bedrock reads the product, quantity and delivery date."),
            ("📊", "Compare suppliers", "Price and delivery are scored against your deadline."),
            ("🛡️", "Human approval", "Nothing is ordered until an approver signs off."),
            ("📄", "PDF purchase orders", "Approved requests produce a numbered PO for the supplier."),
        ]
        feats = "".join(f'<div class="pa-feat"><div class="i">{i}</div><div><b>{esc(t)}</b>'
                        f'<span>{esc(s)}</span></div></div>' for i, t, s in features)
        _html(f'<div class="pa-login"><div class="t">Intelligent<br>Procurement Agent</div>'
              f'<div class="s">From purchase request to approved purchase order in minutes.</div>{feats}</div>')
    with right:
        st.write("")
        st.write("")
        st.subheader("Sign in")
        st.caption("Requesters and approvers have separate accounts.")
        with st.form("ui_login_form", border=True):
            username = st.text_input("Username", key="ui_login_user", placeholder="e.g. madhukar")
            password = st.text_input("Password", type="password", key="ui_login_pass")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch",
                                              icon=":material/login:")
        if submitted:
            try:
                st.session_state["ui_account"] = users.authenticate(username, password)
                st.session_state.pop("ui_login_pass", None)
                st.rerun()
            except AuthError as exc:
                st.error(str(exc))
        st.caption("No account? Ask an administrator.")


def _sign_out() -> None:
    for key in [k for k in st.session_state.keys() if str(k).startswith("ui_")]:
        del st.session_state[key]


# ---------------------------------------------------------------- requester
def _use_example(text: str) -> None:
    st.session_state["ui_request_text"] = text


def _steps(stage: int) -> str:
    parts = []
    for i, label in enumerate(STEPS, start=1):
        cls = "done" if i < stage else ("active" if i == stage else "")
        mark = "✓" if i < stage else str(i)
        parts.append(f'<div class="pa-step {cls}"><span class="n">{mark}</span>{esc(label)}</div>')
    return f'<div class="pa-steps">{"".join(parts)}</div>'


def _new_request_tab(agent: ProcurementAgent, svc: ApprovalService, account: Account, today: date) -> None:
    ss = st.session_state
    steps_slot = st.empty()

    _section("What do you need?")
    st.caption("Try an example:")
    cols = st.columns(len(EXAMPLES))
    for i, (col, (label, text)) in enumerate(zip(cols, EXAMPLES)):
        col.button(label, key=f"ui_ex_{i}", on_click=_use_example, args=(text,), width="stretch")
    text = st.text_area("Describe what you need", key="ui_request_text", height=110,
                        placeholder=EXAMPLES[0][1], label_visibility="collapsed")
    if st.button("Extract details", key="ui_extract_btn", type="primary", icon=":material/auto_awesome:"):
        ss.pop("ui_rec", None)
        ss.pop("ui_submitted_case", None)
        try:
            with st.spinner("Amazon Bedrock is reading your request..."):
                ss["ui_extraction"] = agent.extract_request(text, today, requester=account.username)
        except Exception as exc:  # network, credentials, throttling
            ss.pop("ui_extraction", None)
            st.error(f"The AI service failed: {exc}")

    ext = ss.get("ui_extraction")
    if ext is not None:
        if ext.ok:
            _section("Confirm details")
            d = {"product": ext.request.product, "quantity": ext.request.quantity,
                 "date": ext.request.required_date}
        else:
            _section("Details needed")
            for name in ext.missing:
                st.warning(f"Missing: {name.replace('_', ' ')}")
            for err in ext.errors:
                st.warning(err)
            st.caption("Fill in the fields below or rephrase your request.")
            d = {"product": "", "quantity": 1, "date": today + timedelta(days=14)}

        with st.form("ui_confirm_form"):
            c1, c2, c3 = st.columns([2, 1, 1])
            product = c1.text_input("📦 Product", value=d["product"])
            quantity = c2.number_input("🔢 Quantity", min_value=0, value=int(d["quantity"]), step=1)
            required = c3.date_input("📅 Required by", value=d["date"])
            confirmed = st.form_submit_button("Confirm and get quotes", type="primary",
                                              icon=":material/search:")

        if confirmed:
            check = validate_fields(product, quantity, required, today, raw_text=text, requester=account.username)
            if not check.ok:
                for err in check.errors + [f"Missing: {m}" for m in check.missing]:
                    st.error(err)
            else:
                try:
                    with st.spinner("Retrieving and comparing supplier quotations..."):
                        ss["ui_rec"] = agent.recommend(check.request, today)
                    ss.pop("ui_submitted_case", None)
                except Exception as exc:
                    ss.pop("ui_rec", None)
                    st.error(f"Could not produce a recommendation: {exc}")

    rec = ss.get("ui_rec")
    if rec is not None:
        _section("Recommendation")
        _show_recommendation(rec, agent.available_products(), full=True)
        if rec.comparison.recommended is not None:
            case_id = ss.get("ui_submitted_case")
            if case_id:
                st.info(f"Submitted for approval. Case ID: **{case_id}**. Approvers have been alerted. "
                        "No purchase has been made. Track it under My requests.")
            elif st.button("Submit for approval", key="ui_submit_btn", type="primary", icon=":material/send:"):
                try:
                    ss["ui_submitted_case"] = svc.submit(rec, account.username)
                    st.rerun()
                except ApprovalError as exc:
                    st.error(str(exc))

    stage = 1
    if ext is not None:
        stage = 2
    if rec is not None and rec.comparison.recommended is not None:
        stage = 3
    if ss.get("ui_submitted_case"):
        stage = len(STEPS) + 1
    steps_slot.markdown(_steps(stage), unsafe_allow_html=True)


def _my_requests_tab(svc: ApprovalService, account: Account) -> None:
    cases = svc.list_cases(submitted_by=account.username)
    if not cases:
        _empty("📭", "You have not submitted any requests yet. Start under New request.")
        return
    counts = {s: sum(c.status == s for c in cases) for s in STATUS_LABEL}
    m = st.columns(4)
    m[0].metric("Submitted", len(cases))
    m[1].metric("Pending", counts[PENDING])
    m[2].metric("Approved", counts[APPROVED] + counts[PO_ISSUED])
    m[3].metric("Rejected", counts[REJECTED])
    st.write("")
    for case in reversed(cases):
        with st.expander(_case_title(case), expanded=case is cases[-1]):
            _case_facts(case, show_requester=False)
            _show_outcome(svc, case)
            _show_recommendation(case.recommendation, full=False)


def _requester_home(agent, svc, account, today) -> None:
    mine = svc.list_cases(submitted_by=account.username)
    tab_new, tab_mine = st.tabs(["New request", f"My requests ({len(mine)})"])
    with tab_new:
        _new_request_tab(agent, svc, account, today)
    with tab_mine:
        _my_requests_tab(svc, account)


# ---------------------------------------------------------------- approver
def _approval_queue_tab(svc: ApprovalService, account: Account, alerts: AlertStore | None = None) -> None:
    pending = svc.list_cases(statuses=[PENDING])
    if not pending:
        st.success("No requests are waiting for approval.")
        _empty("🎉", "The queue is clear.")
        return
    user = account.as_user()
    for case in pending:  # oldest first
        rec = case.recommendation
        with st.expander(_case_title(case), expanded=True):
            _case_facts(case)
            _show_recommendation(rec, full=False)
            if case.submitted_by == account.username:
                st.warning("You submitted this request, so another approver must decide it.")
                continue
            with st.container(border=True):
                _section("Your decision")
                suppliers = [s.quote.supplier for s in rec.comparison.ranked]
                c1, c2 = st.columns([1, 2])
                chosen = c1.selectbox("Supplier", suppliers, index=0, key=f"ui_sup_{case.case_id}")
                comment = c2.text_input("Comment (required to reject or to choose another supplier)",
                                        key=f"ui_cmt_{case.case_id}")
                b1, b2 = st.columns(2)
                if b1.button("Approve", key=f"ui_approve_{case.case_id}", type="primary", width="stretch",
                             icon=":material/check_circle:"):
                    _decide(svc, case.case_id, user, True, comment, chosen, alerts)
                if b2.button("Reject", key=f"ui_reject_{case.case_id}", width="stretch",
                             icon=":material/cancel:"):
                    _decide(svc, case.case_id, user, False, comment, chosen, alerts)
                st.caption("Approving issues a numbered PDF purchase order for the selected supplier.")


def _decide(svc, case_id, user, approve, comment, chosen, alerts: AlertStore | None = None) -> None:
    try:
        svc.decide(case_id, user, approve, comment, chosen)
        if alerts is not None:
            alerts.mark_read(user.name, case_id)
        st.rerun()
    except ApprovalError as exc:
        st.error(str(exc))


def _history_tab(svc: ApprovalService, account: Account) -> None:
    decided = svc.list_cases(statuses=[APPROVED, PO_ISSUED, REJECTED])
    if not decided:
        _empty("🗂️", "No decisions yet.")
        return
    for case in reversed(decided):  # newest first
        with st.expander(_case_title(case), expanded=False):
            _case_facts(case)
            _show_outcome(svc, case)
            if case.status == APPROVED and case.purchase_order is None:
                if st.button("Generate purchase order", key=f"ui_po_{case.case_id}", icon=":material/description:"):
                    try:
                        svc.issue_po(case.case_id, account.as_user())
                        st.rerun()
                    except ApprovalError as exc:
                        st.error(str(exc))
            _show_recommendation(case.recommendation, full=False)


def _active_alerts(svc: ApprovalService, alerts: AlertStore, account: Account) -> list:
    """Unread alerts for cases still waiting. Alerts for cases already decided are marked read."""
    pending_ids = {c.case_id for c in svc.list_cases(statuses=[PENDING])}
    active = []
    for a in alerts.unread(account.username):
        if a.case_id in pending_ids:
            active.append(a)
        else:
            alerts.mark_read(account.username, a.case_id)
    return active


def _alert_panel(alerts: AlertStore, active: list, account: Account) -> None:
    if not active:
        return
    n = len(active)
    rows = "".join(
        f'<div class="pa-alert"><span class="id">🔔 {esc(a.case_id)}</span><span>{esc(a.message)}</span>'
        f'<span class="tm">{esc(_ts(a.created_at))}</span></div>' for a in active)
    _html(f'<div class="pa-alerts"><div class="h">{n} new request{"s" if n != 1 else ""} waiting for your '
          f'approval</div>{rows}</div>')
    if st.button("Mark all as read", key="ui_alerts_read", icon=":material/done_all:"):
        alerts.mark_read(account.username)
        st.rerun()


def _alert_watch(alerts: AlertStore, account: Account) -> None:
    """Runs on a timer while an approver is signed in; refreshes the page when a new alert arrives."""
    ss = st.session_state
    count = alerts.unread_count(account.username)
    if count > ss.get("ui_seen_alerts", 0):
        ss["ui_seen_alerts"] = count
        ss["ui_toast_pending"] = True
        st.rerun(scope="app")
    ss["ui_seen_alerts"] = count


def _approver_home(svc: ApprovalService, account: Account, alerts: AlertStore | None = None,
                   poll_seconds: int | None = None) -> None:
    ss = st.session_state
    if alerts is not None:
        active = _active_alerts(svc, alerts, account)
        first_view = "ui_seen_alerts" not in ss
        if active and (first_view or ss.pop("ui_toast_pending", False)):
            st.toast(f"{len(active)} new purchase request{'s' if len(active) != 1 else ''} waiting for your "
                     "approval", icon="🔔")
        ss["ui_seen_alerts"] = alerts.unread_count(account.username)
        _alert_panel(alerts, active, account)
        if poll_seconds:
            st.fragment(run_every=poll_seconds)(_alert_watch)(alerts, account)
    all_cases = svc.list_cases()
    pending = [c for c in all_cases if c.status == PENDING]
    approved = [c for c in all_cases if c.status in (APPROVED, PO_ISSUED)]
    oldest = max((_days_waiting(c) for c in pending), default=0)
    m = st.columns(4)
    m[0].metric("Waiting for approval", len(pending),
                delta=f"oldest waiting {oldest} day(s)" if oldest >= 1 else None, delta_color="off")
    m[1].metric("Value waiting", f"{sum(_case_value(c) for c in pending):,.0f} USD")
    m[2].metric("Approved", len(approved))
    m[3].metric("POs issued", sum(c.status == PO_ISSUED for c in all_cases))
    st.write("")
    tab_queue, tab_hist = st.tabs([f"Approval queue ({len(pending)})", "Decision history"])
    with tab_queue:
        _approval_queue_tab(svc, account, alerts)
    with tab_hist:
        _history_tab(svc, account)


# ---------------------------------------------------------------- entry point
def render(agent: ProcurementAgent, svc: ApprovalService, users: UserStore, today: date | None = None,
           alerts: AlertStore | None = None, poll_seconds: int | None = 15) -> None:
    """poll_seconds: how often a signed-in approver checks for new alerts (None disables)."""
    st.set_page_config(page_title="Procurement Agent", page_icon="🛒", layout="wide")
    _html(CSS)
    today = today or date.today()
    account: Account | None = st.session_state.get("ui_account")
    if account is None:
        _login_screen(users)
        return
    if account.role not in THEME:
        st.error("Your account has no valid role. Contact an administrator.")
        return
    unread = 0
    if alerts is not None and account.role == APPROVER:
        unread = len(_active_alerts(svc, alerts, account))
    _sidebar(account, unread)
    _hero(account)
    if account.role == REQUESTER:
        _requester_home(agent, svc, account, today)
    else:
        _approver_home(svc, account, alerts, poll_seconds)
