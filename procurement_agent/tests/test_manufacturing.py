"""Manufacturing catalogue: spec parsing, spec matching, pricing rules, agent wiring, PO."""
from datetime import date

import pytest

from procurement.agent import ProcurementAgent, validate_fields
from procurement.comparison import compare
from procurement.specs import Requirement, check, parse_requirements, summarize_specs
from procurement.tools import ToolRegistry

TODAY = date(2026, 11, 20)
P = "pressure sensor"


def reqs(items, cat=P):
    r, notes = parse_requirements(cat, items)
    assert notes == []
    return r


STD = [{"spec": "range_max", "value": "0-150", "unit": "psi"}, {"spec": "output", "value": "4-20 mA"},
       {"spec": "connection", "value": "1/4 inch NPT"}]


# ---------------------------------------------------------------- parsing
@pytest.mark.parametrize("value,unit,expected", [
    ("0-150", "psi", 150), ("150 psi", "", 150), ("10", "bar", 145.038), ("1 MPa", "", 145.038),
    ("0 - 150", "psi", 150), ("1,000", "kPa", 145.038),
])
def test_MF1_pressure_units(value, unit, expected):
    [r] = reqs([{"spec": "range_max", "value": value, "unit": unit}])
    assert r.value == pytest.approx(expected, rel=1e-4) and r.op == ">="


def test_MF2_range_hyphen_is_not_a_minus_sign():
    [r] = reqs([{"spec": "range_max", "value": "0-150 psi"}])
    assert r.value == 150  # was -150 before the fix


def test_MF3_temperature_and_length_units():
    [t] = reqs([{"spec": "range_max", "value": "392", "unit": "F"}], "temperature sensor")
    assert t.value == pytest.approx(200)
    [p] = reqs([{"spec": "pipe_size", "value": "2", "unit": "in"}], "flow meter")
    assert p.value == pytest.approx(50.8) and p.op == "="
    [lv] = reqs([{"spec": "range_max", "value": "10 m"}], "level sensor")
    assert lv.value == 10000 and lv.describe("level sensor") == "Measuring range: at least 10 m"


def test_MF4_default_operators_and_override():
    acc, ip = reqs([{"spec": "accuracy_pct", "value": "0.25"}, {"spec": "ip_rating", "value": "ip 67"}])
    assert (acc.op, ip.op, ip.value) == ("<=", ">=", "IP67")
    [eq] = reqs([{"spec": "range_max", "value": "150 psi", "op": "="}])
    assert eq.op == "="


def test_MF5_bad_input_becomes_a_note_not_an_error():
    r, notes = parse_requirements(P, [{"spec": "colour", "value": "red"}, {"spec": "range_max", "value": "lots"},
                                      {"spec": "range_max", "value": "5", "unit": "furlongs"}])
    assert r == [] and len(notes) == 3
    r, notes = parse_requirements("laptop", [{"spec": "range_max", "value": "1"}])
    assert r == [] and "not checked" in notes[0]


# ---------------------------------------------------------------- checks
def test_MF6_checks_compare_units_text_and_ip():
    specs = {"range_max": "10 bar", "output": "4-20 mA HART", "connection": '1/4" NPT', "ip_rating": "IP65",
             "accuracy_pct": 0.065}
    r = reqs(STD + [{"spec": "ip_rating", "value": "IP67"}, {"spec": "accuracy_pct", "value": "0.1"}])
    got = {c.label: c.ok for c in check(P, specs, r)}
    assert got == {"Pressure range (max)": False, "Output signal": True, "Process connection": True,
                   "Ingress protection": False, "Accuracy (% of span)": True}


def test_MF7_missing_spec_fails_the_check():
    [c] = check(P, {}, reqs([{"spec": "ip_rating", "value": "IP67"}]))
    assert not c.ok and "not stated" in c.detail


def test_MF8_spec_summary():
    assert summarize_specs(P, {"range_max": "150 psi", "output": "4-20 mA", "accuracy_pct": 0.25,
                               "connection": '1/4" NPT', "ip_rating": "IP65"}) == \
        '0-150 psi · 4-20 mA · ±0.25% · 1/4" NPT · IP65'


# ---------------------------------------------------------------- search
def test_MF9_pressure_example_end_to_end(repo):
    quotes, excluded = repo.find(P, 100, TODAY, reqs(STD))
    best = {q.supplier: q.model for q in quotes}
    assert best == {"DwyerOmega": "PX309-150GI", "Siemens": "SITRANS P220 7MF1567-3DB00",
                    "WIKA": "A-10 (0-160 psi)", "Honeywell": "PX2AN1XX150PSCHX", "Emerson": "Rosemount 3051TG"}
    reasons = " | ".join(e["reason"] for e in excluded)
    assert "626-07-GH-P1-E1-S1: Pressure range (max) 100 psi does not meet at least 150 psi" in reasons
    assert "SITRANS P200 7MF1565-3CA00: Pressure range (max) 145 psi does not meet" in reasons
    assert "MLH150PGL01A: Output signal 0.5-4.5 V does not meet 4-20 mA" in reasons
    assert all(all(ok for _, ok, _ in q.checks) for q in quotes)
    assert compare(quotes, date(2027, 1, 15)).recommended.quote.supplier in {"WIKA", "DwyerOmega"}


def test_MF10_volume_pricing_and_stock(repo):
    one = {q.supplier: q for q in repo.find(P, 1, TODAY, reqs(STD))[0]}
    hundred = {q.supplier: q for q in repo.find(P, 100, TODAY, reqs(STD))[0]}
    assert one["DwyerOmega"].unit_price == 245.0 and hundred["DwyerOmega"].unit_price == 215.0
    assert hundred["DwyerOmega"].from_stock and hundred["DwyerOmega"].lead_time_days == 3
    big = {q.supplier: q for q in repo.find(P, 500, TODAY, reqs(STD))[0]}
    assert not big["DwyerOmega"].from_stock and big["DwyerOmega"].lead_time_days == 12


def test_MF11_minimum_order_quantity(repo):
    quotes, excluded = repo.find(P, 5, TODAY, reqs(STD))
    assert "Siemens" not in {q.supplier for q in quotes}
    assert any("minimum order is 10 units" in e["reason"] for e in excluded)


def test_MF12_budget_excludes_expensive_models(repo):
    quotes, excluded = repo.find(P, 100, TODAY, reqs(STD), max_unit_price=250)
    assert {q.supplier for q in quotes} == {"DwyerOmega", "WIKA", "Honeywell"}
    assert any("over the budget of 250.00 USD" in e["reason"] for e in excluded)


def test_MF13_progress_events_one_per_supplier(repo):
    events = []
    repo.find(P, 100, TODAY, reqs(STD), progress=events.append)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "search_start" and kinds[-1] == "search_done" and kinds.count("supplier") == 5
    sites = {e["site"] for e in events if e["type"] == "supplier"}
    assert sites == {"dwyeromega.com", "siemens.com", "wika.com", "honeywell.com", "emerson.com"}


def test_MF14_progress_errors_never_break_search(repo):
    def boom(_):
        raise RuntimeError("display failed")
    assert len(repo.find(P, 100, TODAY, reqs(STD), progress=boom)[0]) == 5


def test_MF15_office_products_unchanged(repo):
    quotes, excluded = repo.find("laptop", 50, TODAY)
    assert {q.supplier for q in quotes} == {"Acme Supplies", "TechWorld", "QuickShip Ltd"}
    assert all(q.checks == () and q.model == "" for q in quotes)


# ---------------------------------------------------------------- agent and tools
class ExtractLLM:
    def __init__(self, args):
        self.args = args

    def converse(self, system, messages, tools=None, force_tool=None):
        return {"output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "x", "name": "extract_request", "input": self.args}}]}}}


def test_MF16_extraction_maps_product_and_requirements(repo):
    agent = ProcurementAgent(ExtractLLM({"product": "pressure transducers", "quantity": 100,
                                         "required_date": "2027-01-15", "requirements": STD,
                                         "max_unit_price": 300}), repo)
    res = agent.extract_request("...", TODAY)
    assert res.ok and res.request.product == P and res.request.max_unit_price == 300
    assert [r.spec for r in res.request.requirements] == ["range_max", "output", "connection"]


def test_MF17_confirmed_requirements_always_apply_in_tools(repo):
    request = validate_fields(P, 100, date(2027, 1, 15), TODAY, requirements=reqs(STD)).request
    reg = ToolRegistry(repo, TODAY, request=request)
    out = reg.run("get_supplier_quotes", {"product": P, "quantity": 100})  # model passes no requirements
    assert "Siemens" in {q["supplier"] for q in out["quotes"]}
    assert all(q["meets_all_requirements"] for q in out["quotes"])
    assert "Pressure range (max): at least 150 psi" in out["requirements_checked"]


def test_MF18_requirements_round_trip_in_store(tmp_path, repo):
    from procurement.store import recommendation_from_dict, recommendation_to_dict
    from procurement.models import Recommendation
    request = validate_fields(P, 100, date(2027, 1, 15), TODAY, requirements=reqs(STD), max_unit_price=400).request
    quotes, ex = repo.find(P, 100, TODAY, request.requirements, 400)
    rec = Recommendation(request, compare(quotes, request.required_date), "e", ex)
    assert recommendation_from_dict(recommendation_to_dict(rec)) == rec


def test_MF19_po_names_model_and_specification(tmp_path, repo):
    import io
    from pypdf import PdfReader
    from procurement.approval import ApprovalService, User
    from procurement.models import Recommendation
    from procurement.po import FilePurchaseOrderIssuer
    svc = ApprovalService(tmp_path / "a.jsonl", po_issuer=FilePurchaseOrderIssuer(tmp_path / "pos"))
    request = validate_fields(P, 100, date(2027, 1, 15), TODAY, requirements=reqs(STD)).request
    quotes, ex = repo.find(P, 100, TODAY, request.requirements)
    cid = svc.submit(Recommendation(request, compare(quotes, request.required_date), "e", ex), "alice")
    svc.decide(cid, User("bob", "approver"), True, "ok")
    po = svc.get(cid).purchase_order
    assert po.model and "4-20 mA" in po.specification
    text = PdfReader(io.BytesIO(svc.po_pdf(cid))).pages[0].extract_text()
    assert po.model in text and po.specification.split(" · ")[0] in text and "4-20 mA" in text
