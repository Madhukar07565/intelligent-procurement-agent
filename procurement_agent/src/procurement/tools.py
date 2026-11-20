"""Tool specs (Bedrock Converse format) and a dispatcher.

The registry keeps the quotes fetched by `get_supplier_quotes`, and
`compare_quotes` scores exactly those quotes. The model therefore cannot
alter prices or dates between the two calls.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .comparison import compare
from .models import Comparison, PurchaseRequest, Quote
from .quotes import ProgressFn, QuoteRepository
from .specs import SCHEMA, extraction_guide

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


_SPEC_KEYS = sorted({k for specs in SCHEMA.values() for k in specs})

EXTRACT_SPEC = _spec(
    EXTRACT_REQUEST,
    "Record the product, quantity, required delivery date and any technical requirements or budget found "
    "in the user's purchase request. Omit a field if the user did not provide it and list its name in "
    "`missing`. Never guess or invent requirements the user did not state.",
    {
        "product": {"type": "string", "description": "Product name, singular, e.g. 'pressure sensor' or 'laptop'"},
        "quantity": {"type": "integer", "description": "Number of units"},
        "required_date": {"type": "string", "description": "Delivery date, YYYY-MM-DD"},
        "requirements": {
            "type": "array",
            "description": "Technical requirements stated by the user, one item per spec",
            "items": {"type": "object", "properties": {
                "spec": {"type": "string", "enum": _SPEC_KEYS},
                "value": {"type": "string", "description": "Value as stated, e.g. '150', '4-20 mA', 'IP67'"},
                "unit": {"type": "string", "description": "Unit as stated, e.g. 'psi', 'bar', 'C', 'in', 'm'"},
                "op": {"type": "string", "enum": [">=", "<=", "="],
                       "description": "'>=' for 'at least'/'up to a range of', '<=' for 'or better' accuracy"},
            }, "required": ["spec", "value"]},
        },
        "max_unit_price": {"type": "number", "description": "Budget per unit, only if the user states one"},
        "missing": {"type": "array", "items": {"type": "string"},
                    "description": "Names of fields that were not provided or are ambiguous"},
    },
    [],
)

EXTRACT_GUIDE = extraction_guide()

QUOTES_SPEC = _spec(
    GET_SUPPLIER_QUOTES,
    "Search every supplier catalogue for a product and quantity, apply volume pricing, stock, minimum "
    "order quantities, the budget and the confirmed technical requirements. Returns each supplier's best "
    "qualifying model with total price, delivery date and spec checks, plus excluded models with reasons.",
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
    def __init__(self, repo: QuoteRepository, today: date, request: PurchaseRequest | None = None,
                 progress: ProgressFn | None = None):
        self._repo = repo
        self._today = today
        self._request = request    # confirmed request: its requirements and budget always apply
        self._progress = progress
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
        reqs = self._request.requirements if self._request else ()
        budget = self._request.max_unit_price if self._request else None
        quotes, excluded = self._repo.find(str(args["product"]), quantity, self._today, reqs, budget,
                                           progress=self._progress)
        self.quotes, self.excluded, self.comparison = quotes, excluded, None
        self.fetched = True
        out = {"quotes": [_quote_for_model(q) for q in quotes], "excluded": excluded}
        if reqs:
            out["requirements_checked"] = [r.describe(quotes[0].product if quotes else str(args["product"]))
                                           for r in reqs]
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


def _quote_for_model(q: Quote) -> dict:
    """Compact quote for the model: enough to explain the choice, nothing it could act on."""
    d = {"supplier": q.supplier, "model": q.model, "quote_ref": q.quote_ref, "unit_price": q.unit_price,
         "total_price": q.total_price, "currency": q.currency, "delivery_date": q.delivery_date.isoformat(),
         "lead_time_days": q.lead_time_days, "from_stock": q.from_stock}
    if q.checks:
        d["meets_all_requirements"] = all(ok for _, ok, _ in q.checks)
    return {k: v for k, v in d.items() if v not in ("", None)}
