"""Multi-product requests (bill of materials): one PO per winning supplier."""
import io
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from pypdf import PdfReader

from procurement.agent import ProcurementAgent, validate_fields
from procurement.approval import APPROVED, PENDING, PO_ISSUED, ApprovalError, ApprovalService, User
from procurement.comparison import compare
from procurement.models import BuildRecommendation, Recommendation
from procurement.po import FilePurchaseOrderIssuer
from procurement.specs import parse_requirements
from procurement.store import SqliteCaseStore
from procurement.tools import ToolRegistry

TODAY = date(2026, 11, 20)
DUE = date(2027, 1, 30)
NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
BOB = User("bob", "approver")

PRESSURE = ("pressure sensor", 100, [{"spec": "range_max", "value": "0-150 psi"}, {"spec": "output", "value": "4-20 mA"},
                                     {"spec": "connection", "value": "1/4 NPT"}])
FLOW = ("flow meter", 6, [{"spec": "meter_type", "value": "magnetic"}, {"spec": "pipe_size", "value": "2 in"},
                          {"spec": "output", "value": "4-20 mA"}])
PROX = ("proximity sensor", 200, [{"spec": "housing", "value": "M18"}, {"spec": "output", "value": "PNP"},
                                  {"spec": "sensing_distance", "value": "8 mm"}, {"spec": "ip_rating", "value": "IP67"}])
IMPOSSIBLE = ("pressure sensor", 10, [{"spec": "range_max", "value": "5000 psi"}])


def line(repo, spec, due=DUE):
    product, qty, items = spec
    reqs, notes = parse_requirements(product, items)
    assert not notes
    req = validate_fields(product, qty, due, TODAY, requirements=reqs, raw_text="build request").request
    quotes, ex = repo.find(product, qty, TODAY, req.requirements)
    return Recommendation(req, compare(quotes, due), "e", ex)


def build(repo, *specs, title="Engine test stand"):
    return BuildRecommendation(title, tuple(line(repo, s) for s in specs), "summary")


@pytest.fixture
def clock():
    return {"t": NOW}


@pytest.fixture
def svc(tmp_path, clock):
    return ApprovalService(tmp_path / "audit.jsonl", clock=lambda: clock["t"],
                           po_issuer=FilePurchaseOrderIssuer(tmp_path / "pos"),
                           store=SqliteCaseStore(tmp_path / "cases.db"))


def audit(tmp_path):
    return [json.loads(x) for x in (tmp_path / "audit.jsonl").read_text().splitlines()]


def pdf_text(data):
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


# ---------------------------------------------------------------- plan
def test_B1_three_products_two_suppliers_two_pos(repo, svc, tmp_path):
    b = build(repo, PRESSURE, FLOW, PROX)
    assert [s for s, _ in b.po_groups()] == ["WIKA", "DwyerOmega"]
    assert b.po_groups()[1][1] == [1, 2]
    cid = svc.submit(b, "alice")
    svc.decide(cid, BOB, True, "ok")
    case = svc.get(cid)
    assert case.status == PO_ISSUED and case.is_build and len(case.lines) == 3
    pos = case.purchase_orders
    assert [(p.po_number, p.supplier, len(p.items())) for p in pos] == [
        ("PO-2026-0001", "WIKA", 1), ("PO-2026-0002", "DwyerOmega", 2)]
    dwyer = pos[1]
    assert dwyer.total_price == pytest.approx(sum(x["amount"] for x in dwyer.items()))
    assert sum(p.total_price for p in pos) == pytest.approx(b.total())
    assert dwyer.build_title == "Engine test stand"
    text = pdf_text(svc.po_pdf(cid, "PO-2026-0002"))
    for part in ["FMG91-PVDF-2", "PRX-M18-8P", "Flow Meter", "Proximity Sensor", "Project: Engine test stand"]:
        assert part in text, part
    assert "A-10" not in text  # the WIKA item is on the other PO
    assert "A-10" in pdf_text(svc.po_pdf(cid, "PO-2026-0001"))
    events = [e["event"] for e in audit(tmp_path)]
    assert events.count("po_issued") == 2
    submitted = audit(tmp_path)[0]["details"]
    assert [p["supplier"] for p in submitted["planned_pos"]] == ["WIKA", "DwyerOmega"]


def test_B2_one_supplier_wins_everything_one_po(repo, svc):
    b = build(repo, FLOW, PROX)
    assert [s for s, _ in b.po_groups()] == ["DwyerOmega"]
    cid = svc.submit(b, "alice")
    svc.decide(cid, BOB, True)
    pos = svc.get(cid).purchase_orders
    assert len(pos) == 1 and len(pos[0].items()) == 2


def test_B3_approver_override_can_merge_pos(repo, svc):
    cid = svc.submit(build(repo, PRESSURE, FLOW, PROX), "alice")
    with pytest.raises(ApprovalError, match="comment is required"):
        svc.decide(cid, BOB, True, "", line_suppliers={0: "DwyerOmega"})
    svc.decide(cid, BOB, True, "One supplier is easier to manage", line_suppliers={0: "DwyerOmega"})
    case = svc.get(cid)
    assert [q.supplier for q in case.chosen_quotes] == ["DwyerOmega"] * 3
    assert list(case.decision.line_suppliers) == ["DwyerOmega"] * 3
    [po] = case.purchase_orders
    assert len(po.items()) == 3
    assert "over the recommended WIKA for pressure sensor" in pdf_text(svc.po_pdf(cid))


def test_B4_invalid_overrides_refused(repo, svc):
    cid = svc.submit(build(repo, PRESSURE, FLOW), "alice")
    with pytest.raises(ApprovalError, match="not one of the quoted suppliers for flow meter"):
        svc.decide(cid, BOB, True, "x", line_suppliers={1: "WIKA"})
    with pytest.raises(ApprovalError, match="Line 6 is not part"):
        svc.decide(cid, BOB, True, "x", line_suppliers={5: "WIKA"})
    assert svc.get(cid).status == PENDING


def test_B5_unfilled_lines_are_not_submitted(repo, svc, tmp_path):
    b = build(repo, PRESSURE, IMPOSSIBLE)
    assert len(b.orderable) == 1 and len(b.unfilled) == 1
    cid = svc.submit(b, "alice")
    case = svc.get(cid)
    assert len(case.lines) == 1 and not case.is_build
    assert audit(tmp_path)[0]["details"]["not_submitted"] == ["pressure sensor"]
    only_bad = BuildRecommendation("x", (line(repo, IMPOSSIBLE), line(repo, IMPOSSIBLE)))
    with pytest.raises(ApprovalError, match="no supplier option"):
        svc.submit(only_bad, "alice")


class FailSecond:
    """Issuer that fails on its second PO until `fail` is cleared."""

    def __init__(self, folder):
        self.inner = FilePurchaseOrderIssuer(folder)
        self.calls = 0
        self.fail = True

    def issue(self, fields):
        self.calls += 1
        if self.fail and self.calls == 2:
            raise OSError("disk full")
        return self.inner.issue(fields)

    def pdf_bytes(self, po):
        return self.inner.pdf_bytes(po)


def test_B6_partial_failure_keeps_issued_pos_and_retry_completes(repo, tmp_path):
    issuer = FailSecond(tmp_path / "pos")
    svc = ApprovalService(tmp_path / "a.jsonl", po_issuer=issuer, store=SqliteCaseStore(tmp_path / "c.db"))
    cid = svc.submit(build(repo, PRESSURE, FLOW, PROX), "alice")
    svc.decide(cid, BOB, True)
    case = svc.get(cid)
    assert case.status == APPROVED and [p.supplier for p in case.purchase_orders] == ["WIKA"]
    assert "DwyerOmega" in case.po_error
    issuer.fail = False
    svc.issue_pos(cid, BOB)
    case = svc.get(cid)
    assert case.status == PO_ISSUED and [p.supplier for p in case.purchase_orders] == ["WIKA", "DwyerOmega"]
    assert len(list((tmp_path / "pos").glob("*.pdf"))) == 2
    with pytest.raises(ApprovalError, match="already issued"):
        svc.issue_pos(cid, BOB)


def test_B7_build_case_survives_restart(repo, svc, tmp_path, clock):
    cid = svc.submit(build(repo, PRESSURE, FLOW, PROX), "alice")
    svc.decide(cid, BOB, True, "ok", line_suppliers={1: "Siemens"})
    again = ApprovalService(tmp_path / "audit.jsonl", clock=lambda: clock["t"],
                            po_issuer=FilePurchaseOrderIssuer(tmp_path / "pos"),
                            store=SqliteCaseStore(tmp_path / "cases.db")).get(cid)
    assert again.title == "Engine test stand" and again.summary == "summary"
    assert [r.request.product for r in again.lines] == ["pressure sensor", "flow meter", "proximity sensor"]
    assert [q.supplier for q in again.chosen_quotes] == ["WIKA", "Siemens", "DwyerOmega"]
    assert [p.supplier for p in again.purchase_orders] == ["WIKA", "Siemens", "DwyerOmega"]
    assert again.purchase_orders[1].lines[0]["product"] == "flow meter"


def test_B8_rules_apply_to_every_line(repo, svc, clock):
    cid = svc.submit(build(repo, PRESSURE, FLOW), "alice")
    with pytest.raises(ApprovalError, match="own request"):
        svc.decide(cid, User("alice", "approver"), True)
    clock["t"] = NOW + timedelta(days=400)  # past every quote's valid_until
    with pytest.raises(ApprovalError, match="expired"):
        svc.decide(cid, BOB, True, "ok")
    assert svc.get(cid).purchase_orders == []


def test_B9_alert_summary_mentions_items_and_pos(repo, svc):
    from procurement.notifications import summarize
    cid = svc.submit(build(repo, PRESSURE, FLOW, PROX), "alice")
    subject, summary = summarize(svc.get(cid))
    assert subject == f"Approval needed: Engine test stand, 3 items ({cid})"
    assert "100 x pressure sensor, 6 x flow meter, 200 x proximity sensor" in summary
    assert "2 purchase order(s) (WIKA, DwyerOmega)" in summary


def test_B10_single_product_cases_unchanged(repo, svc):
    cid = svc.submit(line(repo, PRESSURE), "alice")
    svc.decide(cid, BOB, True)
    case = svc.get(cid)
    assert not case.is_build and case.purchase_order.lines == () and case.purchase_order.items()[0]["quantity"] == 100


# ---------------------------------------------------------------- agent
class ExtractLLM:
    def __init__(self, args):
        self.args = args

    def converse(self, system, messages, tools=None, force_tool=None):
        if force_tool:
            return {"output": {"message": {"role": "assistant", "content": [
                {"toolUse": {"toolUseId": "x", "name": "extract_request", "input": self.args}}]}}}
        return {"output": {"message": {"role": "assistant", "content": [{"text": "<summary>Done.</summary>"}]}}}


def item(spec):
    product, qty, reqs = spec
    return {"product": product, "quantity": qty, "requirements": reqs}


def test_BA1_extraction_merges_top_level_product_with_items(repo):
    # What Nova Lite returned in a live test: first product top-level, the rest in items.
    args = {**item(PRESSURE), "required_date": "2027-01-30", "items": [item(FLOW), item(PROX)]}
    res = ProcurementAgent(ExtractLLM(args), repo).extract_request("...", TODAY)
    assert res.ok and res.is_build
    assert [r.product for r in res.lines] == ["pressure sensor", "flow meter", "proximity sensor"]
    assert all(r.required_date == DUE for r in res.lines)


def test_BA2_extraction_items_only_and_title(repo):
    args = {"required_date": "2027-01-30", "title": "Test stand", "items": [item(PRESSURE), item(FLOW)]}
    res = ProcurementAgent(ExtractLLM(args), repo).extract_request("...", TODAY)
    assert res.ok and res.title == "Test stand" and len(res.lines) == 2


def test_BA3_line_errors_are_labelled(repo):
    agent = ProcurementAgent(ExtractLLM({}), repo)
    res = agent.validate_lines([{"product": "pressure sensor", "quantity": 5}, {"product": "flow meter"}],
                               "2027-01-30", TODAY)
    assert not res.ok and res.missing == ["Item 2 (flow meter): quantity"] and len(res.drafts) == 2
    assert res.required_date == DUE
    res = agent.validate_lines([{"product": "pressure sensor", "quantity": 5}], None, TODAY)
    assert res.missing == ["required_date"]


def test_BA4_app_completes_lines_the_model_skipped(repo):
    agent = ProcurementAgent(ExtractLLM({}), repo)  # the model answers with text at once
    reqs = [line(repo, s).request for s in (PRESSURE, FLOW, PROX)]
    events = []
    b = agent.recommend_plan(reqs, TODAY, "Stand", progress=events.append)
    assert [e["line"] for e in events if e["type"] == "auto" and e["step"] == "search"] == [0, 1, 2]
    assert [s for s, _ in b.po_groups()] == ["WIKA", "DwyerOmega"]
    assert b.summary == "Done." and b.title == "Stand"
    assert all("Meets all stated requirements" in r.explanation for r in b.lines)


def test_BA5_registry_enforces_each_confirmed_line(repo):
    reqs = [line(repo, s).request for s in (PRESSURE, FLOW)]
    reg = ToolRegistry(repo, TODAY, requests=reqs)
    out = reg.run("get_supplier_quotes", {"line": 1, "product": "laptop", "quantity": 1})  # model drifts
    assert {q["supplier"] for q in out["quotes"]} >= {"DwyerOmega"} and all("FM" in q["model"] or "Rosemount" in q["model"]
                                                                            for q in out["quotes"])
    assert "error" in reg.run("get_supplier_quotes", {"line": 7})
    assert "call get_supplier_quotes first" in reg.run("compare_quotes", {"line": 0})["error"]
    reg.run("get_supplier_quotes", {"line": 0})
    first = reg.run("compare_quotes", {"line": 0, "required_date": "2099-01-01"})
    assert "purchase_order_plan" not in first
    last = reg.run("compare_quotes", {"line": 1})
    assert [p["supplier"] for p in last["purchase_order_plan"]] == ["WIKA", "DwyerOmega"]


@pytest.mark.parametrize("merged", [
    [{"spec": "housing", "value": "M18 PNP"}],
    [{"spec": "output", "value": "M18 PNP"}],
])
def test_BA6_merged_text_specs_are_split_using_catalogue_words(repo, merged):
    # Both forms were returned by Nova Lite in live runs for "M18 PNP".
    agent = ProcurementAgent(ExtractLLM({}), repo)
    res = agent.validate_lines([{"product": "proximity sensor", "quantity": 200,
                                 "requirements": merged + [{"spec": "sensing_distance", "value": "8 mm"}]}],
                               "2027-01-30", TODAY)
    got = {r.spec: r.value for r in res.request.requirements}
    assert got["housing"] == "M18" and got["output"] == "PNP" and got["sensing_distance"] == 8
    assert any("Read 'M18 PNP'" in n for n in res.notes)
    quotes, _ = repo.find("proximity sensor", 200, TODAY, res.request.requirements)
    assert {q.supplier for q in quotes} == {"Siemens", "Honeywell", "DwyerOmega"}


def test_BA7_split_does_not_override_a_stated_spec(repo):
    agent = ProcurementAgent(ExtractLLM({}), repo)
    res = agent.validate_lines([{"product": "proximity sensor", "quantity": 5, "requirements": [
        {"spec": "housing", "value": "M18 PNP"}, {"spec": "output", "value": "NPN"}]}], "2027-01-30", TODAY)
    got = {r.spec: r.value for r in res.request.requirements}
    assert got == {"housing": "M18 PNP", "output": "NPN"}  # user stated output: leave both as they are
