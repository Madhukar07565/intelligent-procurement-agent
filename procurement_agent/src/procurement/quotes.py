"""Supplier quotation repository backed by a JSON file."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .models import Quote

ALIASES = {
    "notebook": "laptop",
    "notebook computer": "laptop",
    "screen": "monitor",
    "display": "monitor",
    "chair": "office chair",
    "desk chair": "office chair",
}


def _singular(word: str) -> str:
    return word[:-1] if word.endswith("s") and not word.endswith("ss") and len(word) > 3 else word


def normalize_product(name: str) -> str:
    n = " ".join(name.lower().strip().split())
    if n in ALIASES:
        return ALIASES[n]
    if n.endswith("s") and not n.endswith("ss"):
        singular = n[:-1]
        return ALIASES.get(singular, singular)
    return n


def _words(name: str) -> list[str]:
    cleaned = "".join(c if c.isalnum() or c == " " else " " for c in name.lower())
    return [_singular(w) for w in cleaned.split()]


def resolve_product(requested: str, catalog: list[str]) -> str | None:
    """Map a requested product to a catalog product, or None.

    Matches, in order: exact or alias match; a catalog product whose words appear
    together in the request ("Dell laptops" -> laptop, "24-inch monitors" -> monitor);
    an alias of the request's last word ("ergonomic chairs" -> office chair).
    """
    wanted = normalize_product(requested)
    if wanted in catalog:
        return wanted
    words = _words(wanted)
    for product in sorted(catalog, key=lambda p: -len(p.split())):
        pw = _words(product)
        if any(words[i:i + len(pw)] == pw for i in range(len(words) - len(pw) + 1)):
            return product
    if words:
        alias = ALIASES.get(words[-1])
        if alias in catalog:
            return alias
    return None


REQUIRED_FIELDS = ("supplier", "product", "unit_price", "currency", "lead_time_days", "valid_until", "quote_ref")


def _validate_row(row: dict) -> tuple[float, int, date]:
    """Return (unit_price, lead_time_days, valid_until) or raise ValueError describing the problem."""
    if not isinstance(row, dict):
        raise ValueError("row is not an object")
    missing = [f for f in REQUIRED_FIELDS if row.get(f) in (None, "")]
    if missing:
        raise ValueError("missing " + ", ".join(missing))
    try:
        unit = float(row["unit_price"])
        lead = int(row["lead_time_days"])
        valid_until = date.fromisoformat(str(row["valid_until"]))
    except (TypeError, ValueError):
        raise ValueError("unit_price, lead_time_days or valid_until is not valid") from None
    if not unit > 0:
        raise ValueError("unit_price must be positive")
    if lead < 0:
        raise ValueError("lead_time_days must not be negative")
    return unit, lead, valid_until


class QuoteRepository:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        with self._path.open(encoding="utf-8") as f:
            self._rows: list[dict] = json.load(f)

    def products(self) -> list[str]:
        """Distinct normalized product names in the quote file."""
        names = set()
        for row in self._rows:
            if isinstance(row, dict) and isinstance(row.get("product"), str) and row["product"].strip():
                names.add(normalize_product(row["product"]))
        return sorted(names)

    def find(self, product: str, quantity: int, today: date) -> tuple[list[Quote], list[dict]]:
        """Return (valid quotes, excluded entries) for a product.

        A quote is excluded when its validity date is before `today`.
        """
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        wanted = resolve_product(product, self.products())
        if wanted is None:
            return [], []
        quotes: list[Quote] = []
        excluded: list[dict] = []
        for row in self._rows:
            try:
                if normalize_product(str(row["product"])) != wanted:
                    continue
            except (KeyError, TypeError):
                continue  # no product name: cannot belong to this request
            try:
                unit, lead, valid_until = _validate_row(row)
            except ValueError as exc:
                excluded.append({
                    "supplier": str(row.get("supplier") or "unknown supplier"),
                    "quote_ref": str(row.get("quote_ref") or "-"),
                    "reason": f"incomplete or invalid quotation data ({exc})",
                })
                continue
            if valid_until < today:
                excluded.append({
                    "supplier": row["supplier"],
                    "quote_ref": row["quote_ref"],
                    "reason": f"expired on {valid_until.isoformat()}",
                })
                continue
            quotes.append(Quote(
                supplier=row["supplier"],
                quote_ref=row["quote_ref"],
                product=wanted,
                unit_price=unit,
                total_price=round(unit * quantity, 2),
                currency=row["currency"],
                lead_time_days=lead,
                delivery_date=today + timedelta(days=lead),
                valid_until=valid_until,
            ))
        return quotes, excluded
