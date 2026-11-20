"""Plain dataclasses shared by all components."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any

from .specs import Requirement


@dataclass(frozen=True)
class PurchaseRequest:
    product: str
    quantity: int
    required_date: date
    raw_text: str = ""
    requester: str = ""
    requirements: tuple[Requirement, ...] = ()   # technical specs, checked by specs.check
    max_unit_price: float | None = None          # budget per unit, in the quote currency

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["required_date"] = self.required_date.isoformat()
        d["requirements"] = [r.to_dict() for r in self.requirements]
        return d


@dataclass(frozen=True)
class Quote:
    supplier: str
    quote_ref: str
    product: str
    unit_price: float
    total_price: float
    currency: str
    lead_time_days: int
    delivery_date: date
    valid_until: date
    model: str = ""
    description: str = ""
    supplier_site: str = ""
    specs: tuple[tuple[str, Any], ...] = ()      # (key, value) pairs; a tuple keeps the dataclass hashable
    checks: tuple[tuple[str, bool, str], ...] = ()  # (label, ok, detail) against the request's requirements
    simulated: bool = False
    from_stock: bool = False

    @property
    def spec_dict(self) -> dict[str, Any]:
        return dict(self.specs)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["delivery_date"] = self.delivery_date.isoformat()
        d["valid_until"] = self.valid_until.isoformat()
        d["specs"] = dict(self.specs)
        d["checks"] = [{"label": a, "ok": b, "detail": c} for a, b, c in self.checks]
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Quote":
        return Quote(
            supplier=d["supplier"],
            quote_ref=d["quote_ref"],
            product=d["product"],
            unit_price=float(d["unit_price"]),
            total_price=float(d["total_price"]),
            currency=d["currency"],
            lead_time_days=int(d["lead_time_days"]),
            delivery_date=date.fromisoformat(d["delivery_date"]),
            valid_until=date.fromisoformat(d["valid_until"]),
            model=d.get("model", ""),
            description=d.get("description", ""),
            supplier_site=d.get("supplier_site", ""),
            specs=tuple((d.get("specs") or {}).items()),
            checks=tuple((c["label"], bool(c["ok"]), c["detail"]) for c in d.get("checks") or []),
            simulated=bool(d.get("simulated", False)),
            from_stock=bool(d.get("from_stock", False)),
        )


@dataclass(frozen=True)
class ScoredQuote:
    quote: Quote
    eligible: bool
    days_late: int
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "supplier": self.quote.supplier,
            "model": self.quote.model,
            "quote_ref": self.quote.quote_ref,
            "unit_price": self.quote.unit_price,
            "total_price": self.quote.total_price,
            "currency": self.quote.currency,
            "delivery_date": self.quote.delivery_date.isoformat(),
            "days_late": self.days_late,
            "eligible": self.eligible,
            "score": round(self.score, 2),
        }


@dataclass(frozen=True)
class Comparison:
    ranked: list[ScoredQuote]
    recommended: ScoredQuote | None
    warnings: list[str] = field(default_factory=list)

    def versus_runner_up(self) -> str | None:
        """Precomputed, factual sentence comparing the winner with the second-ranked quote."""
        if self.recommended is None or len(self.ranked) < 2:
            return None
        a, b = self.ranked[0].quote, self.ranked[1].quote
        price_diff = round(a.total_price - b.total_price, 2)
        days_diff = (b.delivery_date - a.delivery_date).days
        if price_diff > 0:
            price = f"costs {price_diff:,.2f} {a.currency} more than"
        elif price_diff < 0:
            price = f"costs {-price_diff:,.2f} {a.currency} less than"
        else:
            price = "costs the same as"
        if days_diff > 0:
            timing = f"delivers {days_diff} day(s) earlier"
        elif days_diff < 0:
            timing = f"delivers {-days_diff} day(s) later"
        else:
            timing = "delivers on the same day"
        return f"{a.supplier} {price} {b.supplier} and {timing}."

    def to_dict(self) -> dict[str, Any]:
        return {
            "ranked": [s.to_dict() for s in self.ranked],
            "recommended": self.recommended.quote.supplier if self.recommended else None,
            "winner_vs_runner_up": self.versus_runner_up(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class Recommendation:
    request: PurchaseRequest
    comparison: Comparison
    explanation: str
    excluded: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    case_id: str
    approved: bool
    approver: str
    comment: str
    chosen_supplier: str | None
    timestamp: str
