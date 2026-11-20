"""Agent: LLM-based extraction and a bounded tool-calling loop."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .comparison import compare
from .llm import LLMClient
from .models import PurchaseRequest, Recommendation
from .quotes import QuoteRepository
from .tools import COMPARE_QUOTES, EXTRACT_REQUEST, EXTRACT_SPEC, GET_SUPPLIER_QUOTES, ToolRegistry

MAX_TOOL_ITERATIONS = 6


class AgentError(RuntimeError):
    pass


@dataclass
class ExtractionResult:
    request: PurchaseRequest | None
    missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.request is not None


def _tool_uses(response: dict) -> list[dict]:
    content = response["output"]["message"]["content"]
    return [b["toolUse"] for b in content if "toolUse" in b]


def _text(response: dict) -> str:
    content = response["output"]["message"]["content"]
    raw = "\n".join(b["text"] for b in content if "text" in b)
    return _THINKING.sub("", raw).strip()


def validate_fields(
    product, quantity, required_date, today: date, raw_text: str = "", requester: str = ""
) -> ExtractionResult:
    """Validate raw field values. Used for LLM output and for user edits in the UI."""
    missing: list[str] = []
    errors: list[str] = []

    product = (product or "").strip() if isinstance(product, str) else ""
    if not product:
        missing.append("product")

    qty = None
    if quantity is None or quantity == "":
        missing.append("quantity")
    else:
        try:
            qty = int(quantity)
            if qty != float(quantity) or qty <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("Quantity must be a positive whole number.")
            qty = None

    req_date = None
    if not required_date:
        missing.append("required_date")
    else:
        try:
            req_date = required_date if isinstance(required_date, date) else date.fromisoformat(str(required_date))
            if req_date < today:
                errors.append("Required delivery date is in the past.")
                req_date = None
        except ValueError:
            errors.append("Required delivery date is not a valid date.")

    if missing or errors:
        return ExtractionResult(None, missing, errors)
    return ExtractionResult(PurchaseRequest(product, qty, req_date, raw_text, requester))


EXTRACT_SYSTEM = (
    "You extract purchase request details. Today's date is {today} ({weekday}). "
    "Call the extract_request tool exactly once. Resolve relative dates against today's date and "
    "give the date as YYYY-MM-DD. If the user gives a month and day without a year, use the next "
    "occurrence of that date. If the product, quantity or date is missing or vague (for example "
    "'ASAP' or 'some'), omit it and list it in `missing`. Never guess."
)

RECOMMEND_SYSTEM = (
    "You are a procurement assistant. For the confirmed purchase request, first call "
    "get_supplier_quotes, then call compare_quotes. Then write a short recommendation for a human "
    "approver (under 120 words): name the recommended supplier, state its total price and delivery "
    "date, explain why it ranks first using the `winner_vs_runner_up` sentence (copy its facts "
    "exactly; do not call a supplier cheaper unless that sentence says so), and mention any "
    "warnings, late suppliers or excluded quotes. Use only numbers returned by the tools. Reply with "
    "the recommendation text only, no reasoning tags. You cannot place orders; a human must "
    "approve the purchase."
)

_THINKING = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)


class ProcurementAgent:
    def __init__(self, llm: LLMClient, repo: QuoteRepository):
        self._llm = llm
        self._repo = repo

    def available_products(self) -> list[str]:
        return self._repo.products()

    def extract_request(self, text: str, today: date, requester: str = "") -> ExtractionResult:
        system = EXTRACT_SYSTEM.format(today=today.isoformat(), weekday=today.strftime("%A"))
        response = self._llm.converse(
            system,
            [{"role": "user", "content": [{"text": text}]}],
            tools=[EXTRACT_SPEC],
            force_tool=EXTRACT_REQUEST,
        )
        uses = [u for u in _tool_uses(response) if u["name"] == EXTRACT_REQUEST]
        if not uses:
            return ExtractionResult(None, errors=["Could not understand the request. Please rephrase."])
        args = uses[0]["input"]
        result = validate_fields(
            args.get("product"), args.get("quantity"), args.get("required_date"),
            today, raw_text=text, requester=requester,
        )
        # Python validation is authoritative. Fields the model flagged as missing are added so the
        # user is asked for them even when the model filled in a junk value.
        if not result.ok:
            for name in args.get("missing") or []:
                if name in ("product", "quantity", "required_date") and name not in result.missing:
                    result.missing.append(name)
        return result

    def recommend(self, request: PurchaseRequest, today: date) -> Recommendation:
        registry = ToolRegistry(self._repo, today)
        messages: list[dict] = [{
            "role": "user",
            "content": [{"text": (
                f"Confirmed request: product={request.product}, quantity={request.quantity}, "
                f"required delivery date={request.required_date.isoformat()}."
            )}],
        }]
        explanation = ""
        for _ in range(MAX_TOOL_ITERATIONS):
            response = self._llm.converse(RECOMMEND_SYSTEM, messages, tools=registry.specs())
            messages.append(response["output"]["message"])
            uses = _tool_uses(response)
            if not uses:
                explanation = _text(response)
                break
            results = []
            for use in uses:
                args = dict(use["input"])
                # The confirmed request is authoritative, whatever the model passed.
                if use["name"] == COMPARE_QUOTES:
                    args["required_date"] = request.required_date.isoformat()
                elif use["name"] == GET_SUPPLIER_QUOTES:
                    args["product"], args["quantity"] = request.product, request.quantity
                out = registry.run(use["name"], args)
                results.append({"toolResult": {
                    "toolUseId": use["toolUseId"],
                    "content": [{"json": out}],
                    **({"status": "error"} if "error" in out else {}),
                }})
            messages.append({"role": "user", "content": results})
        else:
            raise AgentError("Tool loop did not finish within the iteration limit.")

        if registry.comparison is None and registry.fetched and not registry.quotes:
            # Quotes were requested but none are usable: report that instead of failing.
            comparison = compare([], request.required_date)
            explanation = "No valid quotations are available for this product."
        elif registry.comparison is None:
            raise AgentError("The agent did not produce a comparison.")
        else:
            comparison = registry.comparison
        if not explanation:
            best = comparison.recommended
            explanation = (
                f"Recommended supplier: {best.quote.supplier} at {best.quote.total_price:,.2f} "
                f"{best.quote.currency}, delivery {best.quote.delivery_date.isoformat()}."
                if best else "No supplier could be recommended."
            )
        return Recommendation(request, comparison, explanation, registry.excluded)
