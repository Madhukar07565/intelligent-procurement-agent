"""Supplier quotation repository backed by a JSON file."""
from __future__ import annotations

import json
import random
import time
from collections import OrderedDict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from .models import Quote
from .specs import SCHEMA, Requirement, check

ProgressFn = Callable[[dict[str, Any]], None]

ALIASES = {
    "notebook": "laptop",
    "notebook computer": "laptop",
    "screen": "monitor",
    "display": "monitor",
    "chair": "office chair",
    "desk chair": "office chair",
    "pressure transducer": "pressure sensor",
    "pressure transmitter": "pressure sensor",
    "pressure gauge transmitter": "pressure sensor",
    "transducer": "pressure sensor",
    "temperature probe": "temperature sensor",
    "temperature transmitter": "temperature sensor",
    "rtd": "temperature sensor",
    "rtd sensor": "temperature sensor",
    "thermocouple": "temperature sensor",
    "flowmeter": "flow meter",
    "flow sensor": "flow meter",
    "flow transmitter": "flow meter",
    "level transmitter": "level sensor",
    "radar level transmitter": "level sensor",
    "inductive sensor": "proximity sensor",
    "proximity switch": "proximity sensor",
    "inductive proximity sensor": "proximity sensor",
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


def _unit_price(row: dict, base: float, quantity: int) -> float:
    """Volume pricing: the lowest price whose minimum quantity the order reaches."""
    price = base
    for min_qty, p in sorted(row.get("price_breaks") or [], key=lambda b: b[0]):
        if quantity >= int(min_qty):
            price = float(p)
    return price


class QuoteRepository:
    def __init__(self, path: str | Path, latency: tuple[float, float] = (0.0, 0.0)):
        """latency: simulated per-supplier response time range in seconds (0 in tests)."""
        self._path = Path(path)
        self._latency = latency
        with self._path.open(encoding="utf-8") as f:
            self._rows: list[dict] = json.load(f)

    def products(self) -> list[str]:
        """Distinct normalized product names in the quote file."""
        names = set()
        for row in self._rows:
            if isinstance(row, dict) and isinstance(row.get("product"), str) and row["product"].strip():
                names.add(normalize_product(row["product"]))
        return sorted(names)

    def spec_vocabulary(self, category: str) -> dict[str, set[str]]:
        """Words used for each text spec of a category across the catalogues (normalized)."""
        from .specs import _norm_text
        vocab: dict[str, set[str]] = {}
        text_specs = {k for k, d in SCHEMA.get(category, {}).items() if d["kind"] == "text"}
        for row in self._rows:
            try:
                if normalize_product(str(row["product"])) != category:
                    continue
            except (KeyError, TypeError):
                continue
            for k, v in (row.get("specs") or {}).items():
                if k in text_specs:
                    vocab.setdefault(k, set()).update(_norm_text(v).split())
        return vocab

    def resolve(self, product: str) -> str | None:
        return resolve_product(product, self.products())

    def find(self, product: str, quantity: int, today: date, requirements: tuple | list = (),
             max_unit_price: float | None = None, progress: ProgressFn | None = None,
             ) -> tuple[list[Quote], list[dict]]:
        """Return (valid quotes, excluded entries) for a product.

        Catalogues are searched supplier by supplier. A model is excluded when its quote has
        expired, the data is invalid, the order is below its minimum quantity, it is over budget,
        or it fails a technical requirement. Each supplier contributes its best qualifying model
        (lowest total, then earliest delivery).
        """
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        wanted = resolve_product(product, self.products())
        if wanted is None:
            return [], []
        by_supplier: "OrderedDict[str, list[dict]]" = OrderedDict()
        for row in self._rows:
            try:
                if normalize_product(str(row["product"])) == wanted:
                    by_supplier.setdefault(str(row.get("supplier") or "unknown supplier"), []).append(row)
            except (KeyError, TypeError):
                continue  # no product name: cannot belong to this request
        sites = {s: next((r.get("supplier_site") for r in rows if r.get("supplier_site")), "")
                 for s, rows in by_supplier.items()}
        simulated = any(r.get("simulated") for rows in by_supplier.values() for r in rows)
        _emit(progress, {"type": "search_start", "product": wanted, "simulated": simulated,
                         "suppliers": [{"supplier": s, "site": sites[s]} for s in by_supplier]})
        quotes: list[Quote] = []
        excluded: list[dict] = []
        for supplier, rows in by_supplier.items():
            started = time.monotonic()
            lo, hi = self._latency
            if hi > 0:
                time.sleep(random.uniform(lo, hi))  # simulated catalogue response time
            found, rejected = [], []
            for row in rows:
                q, reason = self._evaluate(row, wanted, quantity, today, requirements, max_unit_price)
                if q is not None:
                    found.append(q)
                else:
                    rejected.append(reason)
            excluded.extend(rejected)
            best = min(found, key=lambda q: (q.total_price, q.delivery_date)) if found else None
            if best is not None:
                quotes.append(best)
            _emit(progress, {
                "type": "supplier", "supplier": supplier, "site": sites[supplier], "models": len(rows),
                "matching": len(found), "seconds": round(time.monotonic() - started, 2),
                "best": None if best is None else {
                    "model": best.model, "unit_price": best.unit_price, "currency": best.currency,
                    "lead_time_days": best.lead_time_days, "from_stock": best.from_stock},
                "reasons": [e["reason"] for e in rejected[:2]],
            })
        _emit(progress, {"type": "search_done", "qualifying": len(quotes), "suppliers": len(by_supplier)})
        return quotes, excluded

    def _evaluate(self, row: dict, wanted: str, quantity: int, today: date, requirements,
                  max_unit_price: float | None) -> tuple[Quote | None, dict | None]:
        """One catalogue row -> (Quote, None) if it qualifies, else (None, excluded entry)."""
        model = str(row.get("model") or "")
        label = f"{model}: " if model else ""
        try:
            unit, lead, valid_until = _validate_row(row)
        except ValueError as exc:
            return None, _excluded(row, f"incomplete or invalid quotation data ({exc})")
        if valid_until < today:
            return None, _excluded(row, f"{label}expired on {valid_until.isoformat()}")
        moq = int(row.get("min_order_qty") or 1)
        if quantity < moq:
            return None, _excluded(row, f"{label}minimum order is {moq} units")
        unit = _unit_price(row, unit, quantity)
        currency = row["currency"]
        if max_unit_price is not None and unit > max_unit_price:
            return None, _excluded(row, f"{label}{unit:,.2f} {currency} per unit is over the budget of "
                                        f"{max_unit_price:,.2f} {currency}")
        specs = row.get("specs") if isinstance(row.get("specs"), dict) else {}
        checks = []
        if requirements and wanted in SCHEMA:
            try:
                checks = check(wanted, specs, requirements)
            except ValueError as exc:
                return None, _excluded(row, f"{label}specification data could not be read ({exc})")
            failed = [c for c in checks if not c.ok]
            if failed:
                return None, _excluded(row, label + "; ".join(f"{c.label} {c.detail}" for c in failed))
        stock = int(row.get("in_stock") or 0)
        from_stock = stock >= quantity and row.get("stock_lead_days") is not None
        if from_stock:
            lead = int(row["stock_lead_days"])
        return Quote(
            supplier=row["supplier"], quote_ref=row["quote_ref"], product=wanted,
            unit_price=unit, total_price=round(unit * quantity, 2), currency=currency,
            lead_time_days=lead, delivery_date=today + timedelta(days=lead), valid_until=valid_until,
            model=model, description=str(row.get("description") or ""),
            supplier_site=str(row.get("supplier_site") or ""), specs=tuple(specs.items()),
            checks=tuple((c.label, c.ok, c.detail) for c in checks),
            simulated=bool(row.get("simulated")), from_stock=from_stock,
        ), None


def _excluded(row: dict, reason: str) -> dict:
    return {"supplier": str(row.get("supplier") or "unknown supplier"),
            "quote_ref": str(row.get("quote_ref") or "-"), "model": str(row.get("model") or ""),
            "reason": reason}


def _emit(progress: ProgressFn | None, event: dict) -> None:
    if progress is not None:
        try:
            progress(event)
        except Exception:  # a display problem must never break the search
            pass
