"""Deterministic stand-in for the LLM, used by UI tests."""


class ScriptedLLM:
    """Extraction returns fixed fields; recommend() calls the two tools then writes text."""

    def __init__(self, extraction: dict):
        self.extraction = extraction

    def converse(self, system, messages, tools=None, force_tool=None):
        if force_tool == "extract_request":
            return self._use("extract_request", self.extraction)
        # count tool results already in the conversation
        done = sum(1 for m in messages if m["role"] == "user" and "toolResult" in m["content"][0])
        if done == 0:
            return self._use("get_supplier_quotes", {"product": "laptop", "quantity": 50})
        if done == 1:
            return self._use("compare_quotes", {"required_date": "2026-12-15"})
        return {"output": {"message": {"role": "assistant", "content": [{"text": "Scripted explanation."}]}},
                "stopReason": "end_turn"}

    @staticmethod
    def _use(name, args):
        return {"output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": name, "name": name, "input": args}}]}}, "stopReason": "tool_use"}
