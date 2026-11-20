from datetime import date

import pytest

from procurement.agent import AgentError, MAX_TOOL_ITERATIONS, ProcurementAgent, validate_fields
from procurement.models import PurchaseRequest


def tool_use(name, args, tid="t1"):
    return {"output": {"message": {"role": "assistant", "content": [
        {"toolUse": {"toolUseId": tid, "name": name, "input": args}}]}}, "stopReason": "tool_use"}


def text(t):
    return {"output": {"message": {"role": "assistant", "content": [{"text": t}]}}, "stopReason": "end_turn"}


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def converse(self, system, messages, tools=None, force_tool=None):
        self.calls.append({"system": system, "messages": list(messages), "tools": tools, "force_tool": force_tool})
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def agent_with(repo, responses):
    llm = FakeLLM(responses)
    return ProcurementAgent(llm, repo), llm


def test_a1_extraction_valid(repo, today):
    agent, llm = agent_with(repo, [tool_use("extract_request",
                            {"product": "laptop", "quantity": 50, "required_date": "2026-12-15"})])
    res = agent.extract_request("I need 50 laptops by Dec 15", today, requester="alice")
    assert res.ok
    assert res.request == PurchaseRequest("laptop", 50, date(2026, 12, 15), "I need 50 laptops by Dec 15", "alice")
    assert llm.calls[0]["force_tool"] == "extract_request"
    assert "2026-11-20" in llm.calls[0]["system"]


def test_a2_missing_fields_reported(repo, today):
    agent, _ = agent_with(repo, [tool_use("extract_request",
                         {"product": "monitors", "missing": ["quantity", "required_date"]})])
    res = agent.extract_request("some monitors asap", today)
    assert not res.ok and set(res.missing) == {"quantity", "required_date"}


@pytest.mark.parametrize("qty,d,msg", [
    (0, "2026-12-15", "positive"),
    (-3, "2026-12-15", "positive"),
    (5, "2026-01-01", "past"),
    (5, "garbage", "valid date"),
    (2.5, "2026-12-15", "positive"),
])
def test_a3_invalid_values_rejected(repo, today, qty, d, msg):
    agent, _ = agent_with(repo, [tool_use("extract_request", {"product": "laptop", "quantity": qty, "required_date": d})])
    res = agent.extract_request("x", today)
    assert not res.ok and any(msg in e for e in res.errors)


def test_extraction_without_tool_call(repo, today):
    agent, _ = agent_with(repo, [text("hello")])
    res = agent.extract_request("hi", today)
    assert not res.ok and res.errors


REQ = PurchaseRequest("laptop", 50, date(2026, 12, 15))


def test_a4_tool_loop_and_explanation(repo, today):
    agent, llm = agent_with(repo, [
        tool_use("get_supplier_quotes", {"product": "laptop", "quantity": 50}, "t1"),
        tool_use("compare_quotes", {"required_date": "2026-12-15"}, "t2"),
        text("Recommend X because..."),
    ])
    rec = agent.recommend(REQ, today)
    assert rec.explanation == "Recommend X because..."
    assert rec.comparison.recommended is not None
    assert [e["supplier"] for e in rec.excluded] == ["OldDeals Inc"]
    assert len(llm.calls) == 3
    # tool results were fed back to the model
    last_user = llm.calls[2]["messages"][-1]
    assert last_user["role"] == "user" and "toolResult" in last_user["content"][0]


def test_a5_loop_bounded(repo, today):
    agent, llm = agent_with(repo, [tool_use("get_supplier_quotes", {"product": "laptop", "quantity": 50})])
    with pytest.raises(AgentError):
        agent.recommend(REQ, today)
    assert len(llm.calls) == MAX_TOOL_ITERATIONS


def test_a6_recommendation_comes_from_tool_not_text(repo, today):
    agent, _ = agent_with(repo, [
        tool_use("get_supplier_quotes", {"product": "laptop", "quantity": 50}),
        tool_use("compare_quotes", {"required_date": "2026-12-15"}),
        text("I recommend Totally Made Up Corp."),
    ])
    rec = agent.recommend(REQ, today)
    assert rec.comparison.recommended.quote.supplier in {"Acme Supplies", "TechWorld", "QuickShip Ltd"}


def test_confirmed_date_overrides_model_date(repo, today):
    agent, _ = agent_with(repo, [
        tool_use("get_supplier_quotes", {"product": "laptop", "quantity": 50}),
        tool_use("compare_quotes", {"required_date": "2030-01-01"}),  # model tries a lax date
        text("ok"),
    ])
    tight = PurchaseRequest("laptop", 50, date(2026, 11, 26))  # only QuickShip (5d) is on time
    rec = agent.recommend(tight, today)
    assert rec.comparison.recommended.quote.supplier == "QuickShip Ltd"


def test_no_comparison_raises(repo, today):
    agent, _ = agent_with(repo, [text("I did nothing")])
    with pytest.raises(AgentError):
        agent.recommend(REQ, today)


def test_tool_error_is_passed_back_to_model(repo, today):
    agent, llm = agent_with(repo, [
        tool_use("compare_quotes", {"required_date": "2026-12-15"}, "t1"),   # before fetching quotes
        tool_use("get_supplier_quotes", {"product": "laptop", "quantity": 50}, "t2"),
        tool_use("compare_quotes", {"required_date": "2026-12-15"}, "t3"),
        text("done"),
    ])
    rec = agent.recommend(REQ, today)
    first_result = llm.calls[1]["messages"][-1]["content"][0]["toolResult"]
    assert first_result["status"] == "error"
    assert rec.comparison.recommended is not None


def test_validate_fields_accepts_ui_edits(today):
    res = validate_fields("laptop", 10, date(2026, 12, 1), today)
    assert res.ok and res.request.quantity == 10


def test_thinking_tags_stripped_from_explanation(repo, today):
    agent, _ = agent_with(repo, [
        tool_use("get_supplier_quotes", {"product": "laptop", "quantity": 50}),
        tool_use("compare_quotes", {"required_date": "2026-12-15"}),
        text("<thinking>private</thinking>\nFinal answer."),
    ])
    assert agent.recommend(REQ, today).explanation == "Final answer."


def test_model_missing_list_merged_when_values_junk(repo, today):
    agent, _ = agent_with(repo, [tool_use("extract_request", {
        "product": "monitor", "quantity": "some", "required_date": "asap",
        "missing": ["quantity", "required_date"]})])
    res = agent.extract_request("some monitors asap", today)
    assert not res.ok and {"quantity", "required_date"} <= set(res.missing)


def test_confirmed_product_and_quantity_override_model(repo, today):
    agent, llm = agent_with(repo, [
        tool_use("get_supplier_quotes", {"product": "monitor", "quantity": 1}),  # model drifts
        tool_use("compare_quotes", {"required_date": "2026-12-15"}),
        text("ok"),
    ])
    rec = agent.recommend(REQ, today)  # laptop x 50
    assert rec.comparison.recommended.quote.product == "laptop"
    assert rec.comparison.recommended.quote.total_price == rec.comparison.recommended.quote.unit_price * 50


def test_unknown_product_reports_available_products(repo, today):
    from procurement.tools import ToolRegistry
    out = ToolRegistry(repo, today).run("get_supplier_quotes", {"product": "printer", "quantity": 1})
    assert "pressure sensor" in out["available_products"] and "laptop" in out["available_products"]
