import json

import pytest

from procurement.tools import AGENT_TOOLS, EXTRACT_SPEC, ToolRegistry


@pytest.fixture
def reg(repo, today):
    return ToolRegistry(repo, today)


def test_t1_specs_valid():
    for spec in AGENT_TOOLS + [EXTRACT_SPEC]:
        t = spec["toolSpec"]
        assert t["name"] and t["description"]
        schema = t["inputSchema"]["json"]
        assert schema["type"] == "object"
        assert set(schema.get("required", [])) <= set(schema["properties"])


def test_t2_dispatch_and_serializable(reg):
    out = reg.run("get_supplier_quotes", {"product": "laptop", "quantity": 50})
    json.dumps(out)
    assert len(out["quotes"]) == 3 and len(out["excluded"]) == 1
    cmp = reg.run("compare_quotes", {"required_date": "2026-12-15"})
    json.dumps(cmp)
    assert cmp["recommended"] in {"Acme Supplies", "TechWorld", "QuickShip Ltd"}
    assert reg.comparison is not None


def test_t3_errors_do_not_raise(reg):
    assert "unknown tool" in reg.run("buy_now", {})["error"]
    assert "error" in reg.run("get_supplier_quotes", {"product": "laptop"})
    assert "error" in reg.run("get_supplier_quotes", {"product": "laptop", "quantity": 0})
    assert "error" in reg.run("get_supplier_quotes", {"product": "laptop", "quantity": "x"})
    assert "call get_supplier_quotes first" in reg.run("compare_quotes", {"required_date": "2026-12-15"})["error"]
    reg.run("get_supplier_quotes", {"product": "laptop", "quantity": 1})
    assert "error" in reg.run("compare_quotes", {"required_date": "not-a-date"})
    assert "error" in reg.run("compare_quotes", {"required_date": "2026-12-15", "price_weight": 0.9})


def test_compare_uses_stored_quotes_not_model_input(reg):
    reg.run("get_supplier_quotes", {"product": "laptop", "quantity": 10})
    out = reg.run("compare_quotes", {"required_date": "2026-12-15", "quotes": [{"supplier": "Fake"}]})
    assert "Fake" not in json.dumps(out)


def test_no_purchase_tool_exposed(reg):
    names = {s["toolSpec"]["name"] for s in reg.specs()}
    assert names == {"get_supplier_quotes", "compare_quotes"}
