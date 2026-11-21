"""Streamlit UI tests: login, role-specific screens, approval flow and persistence."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from procurement.auth import UserStore

DATA = Path(__file__).resolve().parent.parent / "data" / "quotes.json"
PASSWORDS = {"alice": "alice-pass-123", "carol": "carol-pass-123", "bob": "bob-pass-123"}


def app_script():
    from datetime import date
    import streamlit as st
    from fakes import ScriptedLLM
    from procurement.agent import ProcurementAgent
    from procurement.approval import ApprovalService
    from procurement.auth import UserStore
    from procurement.po import FilePurchaseOrderIssuer
    from procurement.quotes import QuoteRepository
    from procurement.store import SqliteCaseStore
    from procurement.ui import render

    TMP = "TMP_DIR"
    if "agent" not in st.session_state:
        st.session_state["agent"] = ProcurementAgent(
            ScriptedLLM({"product": "laptop", "quantity": 50, "required_date": "2026-12-15"}),
            QuoteRepository("DATA_PATH"))
        st.session_state["svc"] = ApprovalService(
            TMP + "/audit.jsonl", po_issuer=FilePurchaseOrderIssuer(TMP + "/pos"),
            store=SqliteCaseStore(TMP + "/cases.db"))
        st.session_state["users"] = UserStore(TMP + "/users.json")
        from procurement.notifications import AlertStore, InAppNotifier
        st.session_state["alerts"] = AlertStore(TMP + "/cases.db")
        st.session_state["svc"]._notifier = InAppNotifier(st.session_state["alerts"], st.session_state["users"])
    render(st.session_state["agent"], st.session_state["svc"], st.session_state["users"],
           today=date(2026, 11, 20), alerts=st.session_state["alerts"], poll_seconds=None)


@pytest.fixture
def make_app(tmp_path):
    users = UserStore(tmp_path / "users.json")
    users.add_user("alice", PASSWORDS["alice"], "requester", "Alice Requester")
    users.add_user("carol", PASSWORDS["carol"], "requester", "Carol Requester")
    users.add_user("bob", PASSWORDS["bob"], "approver", "Bob Approver")

    def _make():
        import inspect
        import textwrap
        src = textwrap.dedent(inspect.getsource(app_script))
        src = src.replace('"DATA_PATH"', repr(str(DATA))).replace('"TMP_DIR"', repr(str(tmp_path)))
        src = src.replace("def app_script():", "def _main():") + "\n_main()\n"
        return AppTest.from_string(src, default_timeout=30).run()
    return _make


def btn(at, label):
    matches = [b for b in at.button if b.label == label]
    return matches[0] if matches else None


def tab_labels(at):
    return [t.label for t in at.tabs]


def login(at, username, password=None):
    at.text_input(key="ui_login_user").set_value(username)
    at.text_input(key="ui_login_pass").set_value(password or PASSWORDS[username])
    at.button[0].click().run()  # form submit button "Sign in"
    return at


def logout(at):
    btn(at, "Sign out").click().run()
    return at


def submit_request(at, text="I need 50 laptops by Dec 15"):
    at.text_area(key="ui_request_text").set_value(text).run()
    btn(at, "Extract details").click().run()
    btn(at, "Confirm and search suppliers").click().run()
    btn(at, "Submit for approval").click().run()
    return at


def test_UI1_login_required(make_app):
    at = make_app()
    assert not at.exception
    assert any("Sign in" in s.value for s in at.subheader)
    assert at.tabs == [] or len(at.tabs) == 0
    assert btn(at, "Extract details") is None and btn(at, "Approve") is None


def test_UI2_wrong_password_is_rejected(make_app):
    at = login(make_app(), "alice", "wrong-password")
    assert any("Invalid username or password" in e.value for e in at.error)
    assert len(at.tabs) == 0


def test_UI3_requester_screen(make_app):
    at = login(make_app(), "alice")
    assert not at.exception
    assert tab_labels(at) == ["New request", "My requests (0)"]
    assert any("Requester workspace" in m.value for m in at.markdown)
    assert btn(at, "Approve") is None and btn(at, "Reject") is None


def test_UI4_approver_screen(make_app):
    at = login(make_app(), "bob")
    assert tab_labels(at) == ["Approval queue (0)", "Decision history"]
    assert any("Approver workspace" in m.value for m in at.markdown)
    assert btn(at, "Extract details") is None          # approvers do not raise requests
    assert [m.label for m in at.metric] == ["Waiting for approval", "Value waiting", "Approved", "POs issued"]


def test_UI5_full_flow_requires_human_approval(make_app, tmp_path):
    at = submit_request(login(make_app(), "alice"))
    assert any("Submitted for approval" in i.value for i in at.info)
    text = " ".join(m.value for m in at.markdown) + " ".join(s.value for s in at.success)
    assert "Purchase confirmed" not in text
    assert tab_labels(at)[1] == "My requests (1)"
    assert not (tmp_path / "pos").exists() or not any((tmp_path / "pos").iterdir())

    logout(at)
    assert at.session_state["agent"] is not None              # app objects survive sign-out
    assert "ui_account" not in at.session_state
    login(at, "bob")
    assert tab_labels(at)[0] == "Approval queue (1)"
    btn(at, "Approve").click().run()
    assert not at.exception
    assert any("PO-2026-0001" in s.value for s in at.success)
    assert (tmp_path / "pos" / "PO-2026-0001.pdf").read_bytes().startswith(b"%PDF-")
    assert tab_labels(at)[0] == "Approval queue (0)"


def test_UI6_requester_sees_outcome_and_po(make_app):
    at = submit_request(login(make_app(), "alice"))
    logout(at)
    login(at, "bob")
    btn(at, "Approve").click().run()
    logout(at)
    login(at, "alice")
    assert any("PO issued" in e.label for e in at.expander)
    assert any("Purchase order **PO-2026-0001**" in s.value for s in at.success)
    assert len(at.get("download_button")) == 1
    assert btn(at, "Approve") is None


def test_UI7_requesters_see_only_their_own_requests(make_app):
    at = submit_request(login(make_app(), "alice"))
    logout(at)
    login(at, "carol")
    assert tab_labels(at)[1] == "My requests (0)"
    assert not any("laptop" in e.label for e in at.expander)


def test_UI8_reject_requires_comment(make_app):
    at = submit_request(login(make_app(), "alice"))
    logout(at)
    login(at, "bob")
    btn(at, "Reject").click().run()
    assert any("comment is required" in e.value for e in at.error)
    at.text_input(key=[k for k in at.session_state if str(k).startswith("ui_cmt_")][0]).set_value("Over budget")
    btn(at, "Reject").click().run()
    assert tab_labels(at)[0] == "Approval queue (0)"
    logout(at)
    login(at, "alice")
    assert any("Rejected" in e.label for e in at.expander)


def test_UI9_data_persists_into_a_new_app_session(make_app):
    at = submit_request(login(make_app(), "alice"))
    fresh = login(make_app(), "bob")                 # new session, new service, same database
    assert tab_labels(fresh)[0] == "Approval queue (1)"
    btn(fresh, "Approve").click().run()
    again = login(make_app(), "alice")
    assert any("PO issued" in e.label for e in again.expander)


def test_UI10_approver_cannot_decide_own_case(make_app):
    at = make_app()
    from procurement.agent import validate_fields
    from datetime import date
    agent, svc = at.session_state["agent"], at.session_state["svc"]
    req = validate_fields("laptop", 5, date(2026, 12, 15), date(2026, 11, 20)).request
    svc.submit(agent.recommend(req, date(2026, 11, 20)), "bob")
    login(at, "bob")
    assert any("another approver must decide" in w.value for w in at.warning)
    assert btn(at, "Approve") is None


def test_UI11_incomplete_request_asks_for_details(make_app):
    at = login(make_app(), "alice")
    from fakes import ScriptedLLM
    at.session_state["agent"]._llm = ScriptedLLM({"product": "monitor", "missing": ["quantity", "required_date"]})
    at.text_area(key="ui_request_text").set_value("some monitors asap").run()
    btn(at, "Extract details").click().run()
    warnings = " ".join(w.value for w in at.warning)
    assert "Missing: quantity" in warnings and "Missing: required date" in warnings
    assert btn(at, "Submit for approval") is None


def test_UI12_untrusted_text_is_escaped_in_html_cards(make_app):
    """Supplier names and AI text come from outside the app and must not inject HTML."""
    at = login(make_app(), "alice")
    from datetime import date
    from procurement.agent import validate_fields
    agent = at.session_state["agent"]
    req = validate_fields("laptop", 50, date(2026, 12, 15), date(2026, 11, 20)).request
    rec = agent.recommend(req, date(2026, 11, 20))
    from dataclasses import replace
    evil = "<img src=x onerror=alert(1)>"
    best = rec.comparison.recommended
    bad_quote = replace(best.quote, supplier=evil)
    bad_best = replace(best, quote=bad_quote)
    comparison = replace(rec.comparison, ranked=[bad_best] + rec.comparison.ranked[1:], recommended=bad_best)
    at.session_state["ui_rec"] = replace(rec, comparison=comparison, explanation="<script>alert(2)</script>")
    at.run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "<img src=x" not in page and "<script>alert" not in page
    assert "&lt;img src=x onerror=alert(1)&gt;" in page and "&lt;script&gt;" in page


def alert_text(at):
    return " ".join(m.value for m in at.markdown if m.value.startswith("<div class=\"pa-alerts\""))


def test_UI13_approver_is_alerted_after_requester_submits(make_app):
    at = submit_request(login(make_app(), "alice"))
    assert any("Approvers have been alerted" in i.value for i in at.info)
    case_id = at.session_state["ui_submitted_case"]
    logout(at)
    login(at, "bob")
    assert any("new purchase request" in t.value for t in at.toast)
    panel = alert_text(at)
    assert "1 new request waiting for your approval" in panel and case_id in panel
    assert "alice requested 50 x laptop" in panel
    assert any("🔔 1 new request" in m.value for m in at.sidebar.markdown)


def test_UI14_mark_all_read_clears_alerts(make_app):
    at = submit_request(login(make_app(), "alice"))
    logout(at)
    login(at, "bob")
    btn(at, "Mark all as read").click().run()
    assert alert_text(at) == "" and not any("🔔" in m.value for m in at.sidebar.markdown)
    assert tab_labels(at)[0] == "Approval queue (1)"       # the case itself is still waiting
    logout(at)
    login(at, "bob")
    assert len(at.toast) == 0


def test_UI15_deciding_a_case_clears_its_alert(make_app):
    at = submit_request(login(make_app(), "alice"))
    logout(at)
    login(at, "bob")
    btn(at, "Approve").click().run()
    assert alert_text(at) == ""
    assert at.session_state["alerts"].unread_count("bob") == 0


def test_UI16_requester_sees_no_approver_alerts(make_app):
    at = submit_request(login(make_app(), "alice"))
    logout(at)
    login(at, "carol")
    assert alert_text(at) == "" and len(at.toast) == 0


BUILD_ARGS = {
    "required_date": "2027-01-30", "title": "Rocket engine test stand",
    "items": [
        {"product": "pressure sensor", "quantity": 100, "requirements": [
            {"spec": "range_max", "value": "0-150 psi"}, {"spec": "output", "value": "4-20 mA"},
            {"spec": "connection", "value": "1/4 NPT"}]},
        {"product": "flow meter", "quantity": 6, "requirements": [
            {"spec": "meter_type", "value": "magnetic"}, {"spec": "pipe_size", "value": "2 in"}]},
        {"product": "proximity sensor", "quantity": 200, "requirements": [
            {"spec": "housing", "value": "M18"}, {"spec": "output", "value": "PNP"}]},
    ],
}


def test_UI17_multi_product_request_creates_one_approval_request_per_supplier(make_app, tmp_path):
    at = login(make_app(), "alice")
    from fakes import ScriptedLLM
    at.session_state["agent"]._llm = ScriptedLLM(BUILD_ARGS)
    at.text_area(key="ui_request_text").set_value("parts for the test stand").run()
    btn(at, "Extract details").click().run()
    assert not at.exception
    assert any("Confirm details · 3 products" in m.value for m in at.markdown)
    assert len([c for c in at.checkbox if c.label == "Include"]) == 3
    btn(at, "Confirm and search suppliers").click().run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "2 approval requests → 2 purchase orders · one per supplier" in page and "Rocket engine test stand" in page
    assert [t.label for t in at.tabs if "→" in t.label] == ["1 · pressure sensor → WIKA", "2 · flow meter → DwyerOmega",
                                                            "3 · proximity sensor → DwyerOmega"]
    btn(at, "Submit 2 approval requests (one per supplier)").click().run()
    assert any("Submitted 2 approval requests, one per supplier" in i.value for i in at.info)
    ids = at.session_state["ui_submitted_case"]
    assert len(ids) == 2

    logout(at)
    login(at, "bob")
    assert [t.label for t in at.tabs][0] == "Approval queue (2)"
    assert [s.label for s in at.selectbox] == ["Supplier", "Supplier for all 2 products"]
    assert any("Request 1 of 2 in this order" in c.value for c in at.caption)
    assert any("1 numbered PDF purchase order to the selected supplier for all 2 products" in c.value for c in at.caption)
    btn(at, "Approve").click().run()          # the WIKA request
    assert not at.exception and [t.label for t in at.tabs][0] == "Approval queue (1)"
    btn(at, "Approve").click().run()          # the DwyerOmega request
    assert not at.exception and [t.label for t in at.tabs][0] == "Approval queue (0)"
    issued = [s.value for s in at.success if "Purchase order **PO-" in s.value]
    assert len(issued) == 2 and any("to DwyerOmega, 2 item(s)" in x for x in issued)
    assert len(at.get("download_button")) == 2
    assert sorted(p.name for p in (tmp_path / "pos").glob("*.pdf")) == ["PO-2026-0001.pdf", "PO-2026-0002.pdf"]


def test_UI18_excluding_an_item_searches_only_the_rest(make_app):
    at = login(make_app(), "alice")
    from fakes import ScriptedLLM
    at.session_state["agent"]._llm = ScriptedLLM(BUILD_ARGS)
    at.text_area(key="ui_request_text").set_value("parts").run()
    btn(at, "Extract details").click().run()
    [c for c in at.checkbox if c.label == "Include"][0].uncheck()
    btn(at, "Confirm and search suppliers").click().run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "1 approval request → 1 purchase order" in page
    assert [t.label for t in at.tabs if "→" in t.label] == ["1 · flow meter → DwyerOmega", "2 · proximity sensor → DwyerOmega"]
    btn(at, "Submit for approval").click().run()
    assert isinstance(at.session_state["ui_submitted_case"], str)
