"""Agent: LLM-based extraction and a bounded tool-calling loop."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .comparison import compare
from .llm import LLMClient
from .models import BuildRecommendation, PurchaseRequest, Recommendation
from .quotes import ProgressFn, QuoteRepository, _emit
from .specs import SCHEMA, Requirement, parse_requirements, split_compound
from .tools import COMPARE_QUOTES, EXTRACT_GUIDE, EXTRACT_REQUEST, EXTRACT_SPEC, GET_SUPPLIER_QUOTES, ToolRegistry

MAX_TOOL_ITERATIONS = 6
MAX_LINES = 8


class AgentError(RuntimeError):
    pass


@dataclass
class ExtractionResult:
    request: PurchaseRequest | None
    missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # e.g. requirements that could not be read
    lines: list[PurchaseRequest] = field(default_factory=list)  # all products; lines[0] is `request`
    drafts: list[dict] = field(default_factory=list)  # per product, raw values to prefill the form
    title: str = ""
    required_date: date | None = None  # the shared date, if it was valid

    @property
    def ok(self) -> bool:
        return self.request is not None

    @property
    def is_build(self) -> bool:
        return len(self.drafts) > 1


def _tool_uses(response: dict) -> list[dict]:
    content = response["output"]["message"]["content"]
    return [b["toolUse"] for b in content if "toolUse" in b]


def _text(response: dict) -> str:
    content = response["output"]["message"]["content"]
    raw = "\n".join(b["text"] for b in content if "text" in b)
    text = _WRAPPER_TAGS.sub("", _THINKING.sub("", raw)).strip()
    return re.sub(r"^(summary|recommendation)\s*:\s*", "", text, flags=re.IGNORECASE)


def validate_fields(
    product, quantity, required_date, today: date, raw_text: str = "", requester: str = "",
    requirements: tuple[Requirement, ...] | list = (), max_unit_price=None,
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

    budget = None
    if max_unit_price not in (None, "", 0):
        try:
            budget = float(max_unit_price)
            if budget <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("Budget per unit must be a positive number.")

    if missing or errors:
        return ExtractionResult(None, missing, errors)
    return ExtractionResult(PurchaseRequest(product, qty, req_date, raw_text, requester,
                                            tuple(requirements), budget))


EXTRACT_SYSTEM = (
    "You extract purchase request details. Today's date is {today} ({weekday}). "
    "Call the extract_request tool exactly once. Resolve relative dates against today's date and "
    "give the date as YYYY-MM-DD. If the user gives a month and day without a year, use the next "
    "occurrence of that date. If the product, quantity or date is missing or vague (for example "
    "'ASAP' or 'some'), omit it and list it in `missing`. Never guess.\n"
    "Also record technical requirements the user states, using these spec keys per product type:\n"
    "{guide}\n"
    "Examples: '0-150 psi' -> range_max 150 psi; '4-20 mA output' -> output '4-20 mA'; "
    "'1/4 inch NPT' -> connection '1/4 NPT'; 'accuracy 0.25% or better' -> accuracy_pct 0.25 op '<='; "
    "'IP67' -> ip_rating 'IP67'; 'Pt100' -> sensor_type 'Pt100 RTD'; 'M18 PNP' -> housing 'M18' and "
    "output 'PNP' (one spec per item). Only include what the user said.\n"
    "If the user needs two or more different products (for example the parts to build something), put "
    "EVERY product, including the first, with its own quantity, requirements and budget in `items`, "
    "leave the top-level product empty, give the build a short `title`, and use one required_date."
)

RECOMMEND_SYSTEM = (
    "You are a procurement assistant. For the confirmed purchase request, first call "
    "get_supplier_quotes, then call compare_quotes. Then write a short recommendation for a human "
    "approver (under 120 words): name the recommended supplier and model, say whether it meets all "
    "stated requirements, state its total price and delivery date, explain why it ranks first using the `winner_vs_runner_up` sentence (copy its facts "
    "exactly; do not call a supplier cheaper unless that sentence says so), and mention any "
    "warnings, late suppliers or excluded quotes. Use only numbers returned by the tools. Reply with "
    "the recommendation text only, no reasoning tags. You cannot place orders; a human must "
    "approve the purchase."
)

PLAN_SYSTEM = (
    "You are a procurement assistant for a request with several products, numbered by line. For EVERY "
    "line, call get_supplier_quotes with that line number, then compare_quotes with the same line "
    "number. You may call several tools in one turn. When every line is compared, compare_quotes "
    "returns purchase_order_plan: one purchase order per supplier. Then write a summary for a human "
    "approver (under 150 words), referring to products by name, never by line number: for each "
    "product name the recommended supplier, model and total; "
    "say how many purchase orders will be created and to which suppliers, and the grand total; mention "
    "any product no supplier can fulfil. Use only numbers returned by the tools. Reply with the summary "
    "text only, no reasoning tags. You cannot place orders; a human must approve."
)

_THINKING = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)
_WRAPPER_TAGS = re.compile(r"</?(summary|answer|response|recommendation)>?", re.IGNORECASE)


class ProcurementAgent:
    def __init__(self, llm: LLMClient, repo: QuoteRepository):
        self._llm = llm
        self._repo = repo

    def available_products(self) -> list[str]:
        return self._repo.products()

    def resolve_product(self, name: str) -> str | None:
        return self._repo.resolve(name)

    def extract_request(self, text: str, today: date, requester: str = "") -> ExtractionResult:
        system = EXTRACT_SYSTEM.format(today=today.isoformat(), weekday=today.strftime("%A"), guide=EXTRACT_GUIDE)
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
        items = [i for i in (args.get("items") or []) if isinstance(i, dict) and str(i.get("product") or "").strip()]
        top = str(args.get("product") or "").strip()
        if top and items:
            # The model sometimes puts the first product in the top-level fields and the rest in items.
            names = {self._repo.resolve(str(i["product"])) or str(i["product"]).lower() for i in items}
            if (self._repo.resolve(top) or top.lower()) not in names:
                items = [args, *items]
        if len(items) < 2:  # one product: use the top-level fields (or the single item)
            items = [items[0] if items and not top else args]
        title = str(args.get("title") or "").strip()[:80] if len(items) > 1 else ""
        result = self.validate_lines(items[:MAX_LINES], args.get("required_date"), today, text, requester)
        result.title = title
        if len(items) > MAX_LINES:
            result.notes.append(f"Only the first {MAX_LINES} products were taken from the request.")
        # Python validation is authoritative. Fields the model flagged as missing are added so the
        # user is asked for them even when the model filled in a junk value.
        if not result.ok and len(items) == 1:
            for name in args.get("missing") or []:
                if name in ("product", "quantity", "required_date") and name not in result.missing:
                    result.missing.append(name)
        return result

    def validate_lines(self, items: list[dict], required_date, today: date, raw_text: str = "",
                       requester: str = "") -> ExtractionResult:
        """Validate one or more product lines that share a required date.

        Each item: product, quantity, requirements (spec items as extracted, or {"spec", "value"}),
        max_unit_price. Used for the model's extraction and for the user's edits.
        """
        lines, drafts, missing, errors, notes = [], [], [], [], []
        multi = len(items) > 1
        for n, item in enumerate(items, start=1):
            category = self._repo.resolve(str(item.get("product") or "")) or ""
            raw_reqs, split_notes = split_compound(category, item.get("requirements"),
                                                   self._repo.spec_vocabulary(category))
            reqs, req_notes = parse_requirements(category, raw_reqs)
            req_notes = split_notes + req_notes
            product = category if category in SCHEMA else item.get("product")
            label = f"Item {n} ({product or 'unnamed'}): " if multi else ""
            notes.extend(label + x for x in req_notes)
            drafts.append({"product": product or "", "quantity": item.get("quantity"),
                           "requirements": [(r.spec, r.original or str(r.value)) for r in reqs],
                           "max_unit_price": item.get("max_unit_price")})
            res = validate_fields(product, item.get("quantity"), required_date, today, raw_text=raw_text,
                                  requester=requester, requirements=reqs,
                                  max_unit_price=item.get("max_unit_price"))
            for m in res.missing:
                if m == "required_date":
                    if m not in missing:
                        missing.append(m)
                else:
                    missing.append(f"{label}{m}" if multi else m)
            errors.extend(e if (not multi or "delivery date" in e) else label + e for e in res.errors)
            if res.ok:
                lines.append(res.request)
        errors = list(dict.fromkeys(errors))
        ok = not missing and not errors and len(lines) == len(items)
        when = None
        try:
            parsed = required_date if isinstance(required_date, date) else date.fromisoformat(str(required_date))
            when = parsed if parsed >= today else None
        except (TypeError, ValueError):
            pass
        return ExtractionResult(lines[0] if ok else None, missing, errors, notes,
                                lines if ok else [], drafts, required_date=when)

    def recommend_plan(self, requests: list[PurchaseRequest], today: date, title: str = "",
                       progress: ProgressFn | None = None) -> BuildRecommendation:
        """Search and rank every line, then summarise. Lines won by one supplier share one PO.

        The model drives the tool calls. Any line the model does not finish is completed by the
        app, so every line always gets a deterministic ranking.
        """
        if not requests:
            raise AgentError("Nothing to search for.")
        if len(requests) == 1:
            rec = self.recommend(requests[0], today, progress=progress)
            return BuildRecommendation(title, (rec,), rec.explanation)

        registry = ToolRegistry(self._repo, today, progress=progress, requests=requests)
        listing = "\n".join(
            f"line {i}: {r.quantity} x {r.product}; requirements: "
            f"{'; '.join(x.describe(r.product) for x in r.requirements) or 'none'}; "
            f"budget: {f'{r.max_unit_price:,.2f} per unit' if r.max_unit_price else 'none'}"
            for i, r in enumerate(requests))
        messages: list[dict] = [{"role": "user", "content": [{"text": (
            f"Confirmed multi-product request{f' for {title}' if title else ''}, all needed by "
            f"{requests[0].required_date.isoformat()}:\n{listing}")}]}]

        def _say(event: dict) -> None:
            _emit(progress, event)

        explanation = ""
        for _ in range(min(3 + 2 * len(requests), 16)):
            _say({"type": "thinking"})
            response = self._llm.converse(PLAN_SYSTEM, messages, tools=registry.specs())
            messages.append(response["output"]["message"])
            uses = _tool_uses(response)
            if not uses:
                explanation = _text(response)
                break
            results = []
            for use in uses:
                _say({"type": "tool", "name": use["name"], "line": use["input"].get("line", 0)})
                out = registry.run(use["name"], dict(use["input"]))
                results.append({"toolResult": {"toolUseId": use["toolUseId"], "content": [{"json": out}],
                                               **({"status": "error"} if "error" in out else {})}})
            messages.append({"role": "user", "content": results})

        # Complete any line the model skipped, so the plan never silently drops a product.
        for i in range(len(requests)):
            if i not in registry.line_quotes:
                _say({"type": "auto", "line": i, "step": "search"})
                registry.run(GET_SUPPLIER_QUOTES, {"line": i})
            if registry.line_quotes[i] and i not in registry.line_comparisons:
                _say({"type": "auto", "line": i, "step": "compare"})
                registry.run(COMPARE_QUOTES, {"line": i})

        recs = []
        for i, req in enumerate(requests):
            comparison = registry.line_comparisons.get(i) or compare([], req.required_date)
            recs.append(Recommendation(req, comparison, _line_explanation(req, comparison),
                                       registry.line_excluded.get(i, [])))
        build = BuildRecommendation(title, tuple(recs))
        return BuildRecommendation(title, build.lines, explanation or _plan_summary(build))

    def recommend(self, request: PurchaseRequest, today: date, progress: ProgressFn | None = None) -> Recommendation:
        """progress(event) receives live search and reasoning events for display."""
        registry = ToolRegistry(self._repo, today, request=request, progress=progress)
        reqs = "; ".join(r.describe(request.product) for r in request.requirements) or "none"
        budget = f"{request.max_unit_price:,.2f} per unit" if request.max_unit_price else "none"
        messages: list[dict] = [{
            "role": "user",
            "content": [{"text": (
                f"Confirmed request: product={request.product}, quantity={request.quantity}, "
                f"required delivery date={request.required_date.isoformat()}, "
                f"technical requirements: {reqs}, budget: {budget}."
            )}],
        }]
        def _say(event: dict) -> None:
            _emit(progress, event)  # display problems never break the agent
        explanation = ""
        for _ in range(MAX_TOOL_ITERATIONS):
            _say({"type": "thinking"})
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
                _say({"type": "tool", "name": use["name"]})
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


def _line_explanation(req: PurchaseRequest, comparison) -> str:
    """Factual one-paragraph explanation of one line, built from tool results only."""
    best = comparison.recommended
    if best is None:
        return f"No supplier has a {req.product} that meets every requirement."
    q = best.quote
    model = f" {q.model}" if q.model else ""
    text = (f"{q.supplier}{model}: {q.total_price:,.2f} {q.currency} for {req.quantity} units "
            f"({q.unit_price:,.2f} each), delivery {q.delivery_date.isoformat()}.")
    if q.checks:
        text += " Meets all stated requirements." if all(ok for _, ok, _ in q.checks) else ""
    vs = comparison.versus_runner_up()
    return f"{text} {vs}" if vs else text


def _plan_summary(build: BuildRecommendation) -> str:
    """Summary used when the model did not write one."""
    groups = build.po_groups()
    orderable = build.orderable
    parts = [f"{len(groups)} purchase order(s) for {len(orderable)} product(s), total "
             f"{build.total():,.2f} {orderable[0].comparison.recommended.quote.currency}." if orderable
             else "No product could be matched to a supplier."]
    for supplier, idx in groups:
        items = ", ".join(orderable[i].request.product for i in idx)
        parts.append(f"{supplier}: {items}.")
    for r in build.unfilled:
        parts.append(f"No supplier can fulfil {r.request.product}.")
    return " ".join(parts)
