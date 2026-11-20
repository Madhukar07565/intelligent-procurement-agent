"""Tool specs (Bedrock Converse format) and a dispatcher.

The registry keeps the quotes fetched by `get_supplier_quotes`, and
`compare_quotes` scores exactly those quotes. The model therefore cannot
alter prices or dates between the two calls.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .comparison import compare
from .models import Comparison, Quote
from .quotes import QuoteRepository

EXTRACT_REQUEST = "extract_request"
GET_SUPPLIER_QUOTES = "get_supplier_quotes"
COMPARE_QUOTES = "compare_quotes"


def _spec(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "toolSpec": {
            "name": name,
            "description": description,
            "inputSchema": {"json": {"type": "object", "properties": properties, "required": required}},
        }
    }


EXTRACT_SPEC = _spec(
    EXTRACT_REQUEST,
    "Record the product, quantity and required delivery date found in the user's purchase request. "
    "Omit a field if the user did not provide it and list its name in `missing`. Never guess.",
    {
        "product": {"type": "string", "description": "Product name, singular, e.g. 'laptop'"},
        "quantity": {"type": "integer", "description": "Number of units"},
        "required_date": {"type": "string", "description": "Delivery date, YYYY-MM-DD"},
        "missing": {"type": "array", "items": {"type": "string"},
                    "description": "Names of fields that were not provided or are ambiguous"},
    },
    [],
)

QUOTES_SPEC = _spec(
    GET_SUPPLIER_QUOTES,
    "Retrieve current supplier quotations for a product and quantity. Returns valid quotes with total "
    "price and delivery date, plus quotes excluded (for example expired).",
    {
        "product": {"type": "string"},
        "quantity": {"type": "integer", "minimum": 1},
    },
    ["product", "quantity"],
)

COMPARE_SPEC = _spec(
    COMPARE_QUOTES,
    "Score and rank the quotations retrieved by get_supplier_quotes against the required delivery date. "
    "Call get_supplier_quotes first. Returns the ranking, the recommended supplier and warnings.",
    {
        "required_date": {"type": "string", "description": "YYYY-MM-DD"},
        "price_weight": {"type": "number", "description": "Default 0.6"},
        "delivery_weight": {"type": "number", "description": "Default 0.4. Must sum to 1 with price_weight"},
    },
    ["required_date"],
)

AGENT_TOOLS = [QUOTES_SPEC, COMPARE_SPEC]


class ToolRegistry:
    def __init__(self, repo: QuoteRepository, today: date):
        self._repo = repo
        self._today = today
        self.quotes: list[Quote] = []
        self.excluded: list[dict] = []
        self.comparison: Comparison | None = None
        self.fetched = False  # True once get_supplier_quotes has run successfully

    def specs(self) -> list[dict]:
        return AGENT_TOOLS

    def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool. Never raises; errors are returned as {"error": ...}."""
        try:
            if name == GET_SUPPLIER_QUOTES:
                return self._get_quotes(args)
            if name == COMPARE_QUOTES:
                return self._compare(args)
            return {"error": f"unknown tool: {name}"}
        except (KeyError, ValueError, TypeError) as exc:
            return {"error": f"invalid arguments for {name}: {exc}"}

    def _get_quotes(self, args: dict) -> dict:
        quantity = int(args["quantity"])
        quotes, excluded = self._repo.find(str(args["product"]), quantity, self._today)
        self.quotes, self.excluded, self.comparison = quotes, excluded, None
        self.fetched = True
        out = {"quotes": [q.to_dict() for q in quotes], "excluded": excluded}
        if not quotes and not excluded:
            out["available_products"] = self._repo.products()
        return out

    def _compare(self, args: dict) -> dict:
        if not self.quotes:
            return {"error": "no quotes available; call get_supplier_quotes first"}
        comparison = compare(
            self.quotes,
            date.fromisoformat(str(args["required_date"])),
            float(args.get("price_weight", 0.6)),
            float(args.get("delivery_weight", 0.4)),
        )
        self.comparison = comparison
        return comparison.to_dict()
