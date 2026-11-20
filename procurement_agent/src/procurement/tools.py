"""Tool specs (Bedrock Converse format) and a dispatcher.

The registry keeps the quotes fetched by `get_supplier_quotes`, and
`compare_quotes` scores exactly those quotes. The model therefore cannot
alter prices or dates between the two calls.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .comparison import compare
from .models import Comparison, PurchaseRequest, Quote, group_by_supplier
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
        "items": {
            "type": "array",
            "description": "Use ONLY when the user needs two or more different products: one entry per "
                           "product, and leave the top-level product, quantity and requirements empty.",
            "items": {"type": "object", "properties": {
                "product": {"type": "string"},
                "quantity": {"type": "integer"},
                "requirements": {"type": "array", "items": {"type": "object", "properties": {
                    "spec": {"type": "string", "enum": _SPEC_KEYS}, "value": {"type": "string"},
                    "unit": {"type": "string"}, "op": {"type": "string", "enum": [">=", "<=", "="]}},
                    "required": ["spec", "value"]}},
                "max_unit_price": {"type": "number"},
            }, "required": ["product"]},
        },
        "title": {"type": "string", "description": "Short name of what is being built, if the user says, "
                                                   "e.g. 'Rocket engine test stand'"},
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
        "line": {"type": "integer", "minimum": 0,
                 "description": "Line number of the confirmed request (0 for the first product)"},
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
        "line": {"type": "integer", "minimum": 0, "description": "Line number, as for get_supplier_quotes"},
        "required_date": {"type": "string", "description": "YYYY-MM-DD"},
        "price_weight": {"type": "number", "description": "Default 0.6"},
        "delivery_weight": {"type": "number", "description": "Default 0.4. Must sum to 1 with price_weight"},
    },
    ["required_date"],
)

AGENT_TOOLS = [QUOTES_SPEC, COMPARE_SPEC]


class ToolRegistry:
    """Runs the agent's tools. State is kept per line of the confirmed request.

    With confirmed requests, each line's product, quantity, requirements, budget and date always
    apply, whatever the model passes. `quotes`, `excluded`, `comparison` and `fetched` refer to line 0.
    """

    def __init__(self, repo: QuoteRepository, today: date, request: PurchaseRequest | None = None,
                 progress: ProgressFn | None = None, requests: list[PurchaseRequest] | None = None):
        self._repo = repo
        self._today = today
        self.requests: list[PurchaseRequest] = list(requests or ([request] if request else []))
        self._progress = progress
        self.line_quotes: dict[int, list[Quote]] = {}
        self.line_excluded: dict[int, list[dict]] = {}
        self.line_comparisons: dict[int, Comparison] = {}

    @property
    def quotes(self) -> list[Quote]:
        return self.line_quotes.get(0, [])

    @property
    def excluded(self) -> list[dict]:
        return self.line_excluded.get(0, [])

    @property
    def comparison(self) -> Comparison | None:
        return self.line_comparisons.get(0)

    @property
    def fetched(self) -> bool:  # True once get_supplier_quotes has run for line 0
        return 0 in self.line_quotes

    def specs(self) -> list[dict]:
        return AGENT_TOOLS

    def _line(self, args: dict) -> int:
        line = int(args.get("line", 0) or 0)
        if self.requests and not 0 <= line < len(self.requests):
            raise ValueError(f"line must be between 0 and {len(self.requests) - 1}")
        return line

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
        line = self._line(args)
        req = self.requests[line] if self.requests else None
        product = req.product if req else str(args["product"])
        quantity = req.quantity if req else int(args["quantity"])
        reqs = req.requirements if req else ()
        budget = req.max_unit_price if req else None
        progress = self._progress
        if progress is not None and len(self.requests) > 1:
            progress = lambda e, _p=self._progress, _l=line: _p({**e, "line": _l})  # noqa: E731
        quotes, excluded = self._repo.find(product, quantity, self._today, reqs, budget, progress=progress)
        self.line_quotes[line], self.line_excluded[line] = quotes, excluded
        self.line_comparisons.pop(line, None)
        out = {"line": line, "quotes": [_quote_for_model(q) for q in quotes], "excluded": excluded}
        if reqs:
            out["requirements_checked"] = [r.describe(quotes[0].product if quotes else product) for r in reqs]
        if not quotes and not excluded:
            out["available_products"] = self._repo.products()
        return out

    def _compare(self, args: dict) -> dict:
        line = self._line(args)
        quotes = self.line_quotes.get(line)
        if not quotes:
            if line in self.line_quotes:
                return {"line": line, "error": "no supplier qualifies for this line; nothing to compare"}
            return {"error": "no quotes available; call get_supplier_quotes first"}
        required = self.requests[line].required_date if self.requests else date.fromisoformat(str(args["required_date"]))
        comparison = compare(
            quotes, required,
            float(args.get("price_weight", 0.6)),
            float(args.get("delivery_weight", 0.4)),
        )
        self.line_comparisons[line] = comparison
        out = comparison.to_dict()
        if len(self.requests) > 1:
            out["line"] = line
            if self.all_compared():
                out["purchase_order_plan"] = self.po_plan()
        return out

    def all_compared(self) -> bool:
        """Every line has been searched, and every line with quotes has been compared."""
        return all(i in self.line_quotes and (i in self.line_comparisons or not self.line_quotes[i])
                   for i in range(len(self.requests)))

    def po_plan(self) -> list[dict]:
        """One purchase order per winning supplier, for the model's summary."""
        winners = [self.line_comparisons[i].recommended.quote if i in self.line_comparisons
                   and self.line_comparisons[i].recommended else None for i in range(len(self.requests))]
        plan = []
        for supplier, idx in group_by_supplier(winners):
            plan.append({"supplier": supplier, "lines": idx,
                         "products": [self.requests[i].product for i in idx],
                         "total": round(sum(winners[i].total_price for i in idx), 2),
                         "currency": winners[idx[0]].currency})
        return plan


def _quote_for_model(q: Quote) -> dict:
    """Compact quote for the model: enough to explain the choice, nothing it could act on."""
    d = {"supplier": q.supplier, "model": q.model, "quote_ref": q.quote_ref, "unit_price": q.unit_price,
         "total_price": q.total_price, "currency": q.currency, "delivery_date": q.delivery_date.isoformat(),
         "lead_time_days": q.lead_time_days, "from_stock": q.from_stock}
    if q.checks:
        d["meets_all_requirements"] = all(ok for _, ok, _ in q.checks)
    return {k: v for k, v in d.items() if v not in ("", None)}
