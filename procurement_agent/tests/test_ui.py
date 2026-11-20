import tempfile
from pathlib import Path

from streamlit.testing.v1 import AppTest


def app_script():
    from datetime import date
    import streamlit as st
    from fakes import ScriptedLLM
    from procurement.agent import ProcurementAgent
    from procurement.approval import ApprovalService
    from procurement.quotes import QuoteRepository
    from procurement.ui import render

    DATA = "DATA_PATH"
    if "agent" not in st.session_state:
        st.session_state["agent"] = ProcurementAgent(
            ScriptedLLM({"product": "laptop", "quantity": 50, "required_date": "2026-12-15"}),
            QuoteRepository(DATA))
        from procurement.po import FilePurchaseOrderIssuer
        st.session_state["svc"] = ApprovalService(Path_AUDIT, po_issuer=FilePurchaseOrderIssuer(Path_PO))
    render(st.session_state["agent"], st.session_state["svc"], today=date(2026, 11, 20))


def make_app(tmp):
    from pathlib import Path
    data = Path(__file__).resolve().parent.parent / "data" / "quotes.json"
    import inspect, textwrap
    src = textwrap.dedent(inspect.getsource(app_script))
    src = src.replace('"DATA_PATH"', repr(str(data))).replace("Path_AUDIT", repr(str(Path(tmp) / "audit.jsonl"))).replace("Path_PO", repr(str(Path(tmp) / "pos")))
    src = src.replace("def app_script():", "def _main():") + "\n_main()\n"
    return AppTest.from_string(src, default_timeout=30)


def btn(at, label):
    matches = [b for b in at.button if b.label == label]
    return matches[0] if matches else None


def submit_request(at):
    at.text_area(key="request_text").set_value("I need 50 laptops by Dec 15").run()
    btn(at, "Extract details").click().run()
    btn(at, "Confirm and get quotes").click().run()
    btn(at, "Submit for approval").click().run()
    return at


def test_full_flow_requires_human_approval(tmp_path):
    at = make_app(tmp_path).run()
    assert not at.exception
    submit_request(at)
    assert not at.exception
    assert any("Submitted for approval" in i.value for i in at.info)

    # U2: nothing is confirmed before approval
    all_text = " ".join(m.value for m in at.markdown) + " ".join(s.value for s in at.success)
    assert "Purchase confirmed" not in all_text
    assert "Awaiting approval" in all_text

    # U1: requester role sees no Approve / Reject
    assert btn(at, "Approve") is None and btn(at, "Reject") is None

    # approver bob approves
    at.text_input(key="user_name").set_value("bob").run()
    at.radio(key="user_role").set_value("approver").run()
    approve = btn(at, "Approve")
    assert approve is not None
    approve.click().run()
    assert not at.exception
    assert any("Purchase confirmed with" in s.value for s in at.success)


def test_requester_as_approver_cannot_approve_own_case(tmp_path):
    at = make_app(tmp_path).run()
    submit_request(at)
    at.radio(key="user_role").set_value("approver").run()   # still named alice
    btn(at, "Approve").click().run()
    assert any("own request" in e.value for e in at.error)
    assert not any("Purchase confirmed with" in s.value for s in at.success)


def test_reject_requires_comment(tmp_path):
    at = make_app(tmp_path).run()
    submit_request(at)
    at.text_input(key="user_name").set_value("bob").run()
    at.radio(key="user_role").set_value("approver").run()
    btn(at, "Reject").click().run()
    assert any("comment is required" in e.value for e in at.error)


def test_incomplete_request_asks_for_details(tmp_path):
    at = make_app(tmp_path).run()
    # swap in an extraction with missing fields
    from fakes import ScriptedLLM
    at.session_state["agent"]._llm = ScriptedLLM({"product": "monitor", "missing": ["quantity", "required_date"]})
    at.text_area(key="request_text").set_value("some monitors asap").run()
    btn(at, "Extract details").click().run()
    warnings = " ".join(w.value for w in at.warning)
    assert "Missing: quantity" in warnings and "Missing: required date" in warnings
    assert btn(at, "Submit for approval") is None


def test_po_issued_and_downloadable_after_approval(tmp_path):
    at = make_app(tmp_path).run()
    submit_request(at)
    assert not (tmp_path / "pos").exists() or not any((tmp_path / "pos").iterdir())
    at.text_input(key="user_name").set_value("bob").run()
    at.radio(key="user_role").set_value("approver").run()
    btn(at, "Approve").click().run()
    assert not at.exception
    assert any("PO-2026-0001" in s.value for s in at.success)
    assert (tmp_path / "pos" / "PO-2026-0001.pdf").read_bytes().startswith(b"%PDF-")
    assert len(at.get("download_button")) == 1
