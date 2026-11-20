"""Deterministic supplier comparison. No LLM involved."""
from __future__ import annotations

from datetime import date

from .models import Comparison, Quote, ScoredQuote


def _normalize(value: float, lo: float, hi: float) -> float:
    """100 for the best (lowest) value, 0 for the worst. 100 if all equal."""
    if hi == lo:
        return 100.0
    return (hi - value) / (hi - lo) * 100.0


def compare(
    quotes: list[Quote],
    required_date: date,
    price_weight: float = 0.6,
    delivery_weight: float = 0.4,
) -> Comparison:
    if price_weight < 0 or delivery_weight < 0 or abs(price_weight + delivery_weight - 1.0) > 1e-6:
        raise ValueError("price_weight and delivery_weight must be non-negative and sum to 1")

    if not quotes:
        return Comparison(ranked=[], recommended=None, warnings=["No quotations available."])

    def days_late(q: Quote) -> int:
        return max(0, (q.delivery_date - required_date).days)

    eligible = [q for q in quotes if days_late(q) == 0]
    late = [q for q in quotes if days_late(q) > 0]
    warnings: list[str] = []

    ranked: list[ScoredQuote] = []
    if eligible:
        prices = [q.total_price for q in eligible]
        dates = [q.delivery_date.toordinal() for q in eligible]
        p_lo, p_hi = min(prices), max(prices)
        d_lo, d_hi = min(dates), max(dates)
        scored = []
        for q in eligible:
            score = (
                price_weight * _normalize(q.total_price, p_lo, p_hi)
                + delivery_weight * _normalize(q.delivery_date.toordinal(), d_lo, d_hi)
            )
            scored.append(ScoredQuote(q, True, 0, score))
        # highest score, then earlier delivery, then lower price
        scored.sort(key=lambda s: (-s.score, s.quote.delivery_date, s.quote.total_price))
        ranked.extend(scored)
        if late:
            warnings.append(
                f"{len(late)} quotation(s) cannot deliver by {required_date.isoformat()} and were ranked below on-time options."
            )
    else:
        warnings.append(
            f"No supplier can deliver by {required_date.isoformat()}. Closest options are shown."
        )

    late_sorted = sorted(late, key=lambda q: (days_late(q), q.total_price))
    ranked.extend(ScoredQuote(q, False, days_late(q), 0.0) for q in late_sorted)

    return Comparison(ranked=ranked, recommended=ranked[0], warnings=warnings)
