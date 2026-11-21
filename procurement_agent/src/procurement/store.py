"""Persistent case storage in SQLite (Python standard library, single file).

Each case is stored as one row: a few indexed columns for filtering plus the
full case as JSON. Serialization is explicit so the stored format is stable.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from .models import Comparison, Decision, PurchaseRequest, Quote, Recommendation, ScoredQuote
from .po import PurchaseOrder
from .specs import Requirement

if TYPE_CHECKING:
    from .approval import Case

SCHEMA_VERSION = 1


# ---- serialization -------------------------------------------------------
def _request_to_dict(r: PurchaseRequest) -> dict:
    return r.to_dict()


def _request_from_dict(d: dict) -> PurchaseRequest:
    budget = d.get("max_unit_price")
    return PurchaseRequest(d["product"], int(d["quantity"]), date.fromisoformat(d["required_date"]),
                           d.get("raw_text", ""), d.get("requester", ""),
                           tuple(Requirement.from_dict(r) for r in d.get("requirements") or []),
                           float(budget) if budget is not None else None)


def recommendation_to_dict(rec: Recommendation) -> dict:
    c = rec.comparison
    return {
        "request": _request_to_dict(rec.request),
        "comparison": {
            "ranked": [{"quote": s.quote.to_dict(), "eligible": s.eligible,
                        "days_late": s.days_late, "score": s.score} for s in c.ranked],
            # The recommended quote is always ranked[0] when present.
            "has_recommendation": c.recommended is not None,
            "warnings": list(c.warnings),
        },
        "explanation": rec.explanation,
        "excluded": list(rec.excluded),
    }


def recommendation_from_dict(d: dict) -> Recommendation:
    cd = d["comparison"]
    ranked = [ScoredQuote(Quote.from_dict(s["quote"]), bool(s["eligible"]), int(s["days_late"]),
                          float(s["score"])) for s in cd["ranked"]]
    recommended = ranked[0] if cd["has_recommendation"] and ranked else None
    return Recommendation(_request_from_dict(d["request"]), Comparison(ranked, recommended, list(cd["warnings"])),
                          d["explanation"], list(d.get("excluded", [])))


def case_to_dict(case: "Case") -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "case_id": case.case_id,
        "submitted_by": case.submitted_by,
        "submitted_at": case.submitted_at,
        "status": case.status,
        "recommendation": recommendation_to_dict(case.recommendation),
        "extra_lines": [recommendation_to_dict(r) for r in case.extra_lines],
        "title": case.title,
        "summary": case.summary,
        "build_id": case.build_id,
        "build_part": case.build_part,
        "build_parts": case.build_parts,
        "decision": asdict(case.decision) if case.decision else None,
        "chosen_quotes": [q.to_dict() for q in case.chosen_quotes],
        "purchase_orders": [po.to_dict() for po in case.purchase_orders],
        "po_error": case.po_error,
    }


def case_from_dict(d: dict) -> "Case":
    from .approval import Case  # local import avoids a cycle

    return Case(
        case_id=d["case_id"],
        recommendation=recommendation_from_dict(d["recommendation"]),
        submitted_by=d["submitted_by"],
        submitted_at=d.get("submitted_at", ""),
        status=d["status"],
        decision=_decision_from_dict(d["decision"]) if d.get("decision") else None,
        # Cases stored before multi-product support have single chosen_quote / purchase_order keys.
        chosen_quotes=[Quote.from_dict(q) for q in d.get("chosen_quotes")
                       or ([d["chosen_quote"]] if d.get("chosen_quote") else [])],
        purchase_orders=[_po_from_dict(p) for p in d.get("purchase_orders")
                         or ([d["purchase_order"]] if d.get("purchase_order") else [])],
        po_error=d.get("po_error"),
        extra_lines=[recommendation_from_dict(r) for r in d.get("extra_lines") or []],
        title=d.get("title", ""),
        summary=d.get("summary", ""),
        build_id=d.get("build_id", ""),
        build_part=int(d.get("build_part") or 0),
        build_parts=int(d.get("build_parts") or 0),
    )


def _decision_from_dict(d: dict) -> Decision:
    d = dict(d)
    d["line_suppliers"] = tuple(d.get("line_suppliers") or ())
    return Decision(**d)


def _po_from_dict(d: dict) -> PurchaseOrder:
    d = dict(d)
    d["lines"] = tuple(d.get("lines") or ())
    return PurchaseOrder(**d)


# ---- store ---------------------------------------------------------------
class SqliteCaseStore:
    """Thread-safe case store. Use ":memory:" for tests."""

    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        if str(path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS cases (
                    case_id      TEXT PRIMARY KEY,
                    submitted_by TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    status       TEXT NOT NULL,
                    data         TEXT NOT NULL
                )""")
            self._conn.execute("CREATE INDEX IF NOT EXISTS ix_cases_status ON cases(status)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS ix_cases_submitter ON cases(submitted_by)")

    def save(self, case: "Case") -> None:
        data = json.dumps(case_to_dict(case))
        with self._lock:
            self._conn.execute(
                "INSERT INTO cases(case_id, submitted_by, submitted_at, status, data) VALUES (?,?,?,?,?) "
                "ON CONFLICT(case_id) DO UPDATE SET status=excluded.status, data=excluded.data",
                (case.case_id, case.submitted_by, case.submitted_at, case.status, data),
            )

    def get(self, case_id: str) -> "Case | None":
        with self._lock:
            row = self._conn.execute("SELECT data FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        return case_from_dict(json.loads(row[0])) if row else None

    def list(self, submitted_by: str | None = None, statuses: list[str] | None = None) -> list["Case"]:
        sql, args = "SELECT data FROM cases WHERE 1=1", []
        if submitted_by is not None:
            sql += " AND submitted_by = ?"
            args.append(submitted_by)
        if statuses:
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            args.extend(statuses)
        sql += " ORDER BY submitted_at, rowid"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [case_from_dict(json.loads(r[0])) for r in rows]

    def reassign_submitter(self, old: str, new: str) -> int:
        """Move every case submitted by `old` to `new`. Returns the number of cases changed.

        Issued PO documents are not rewritten: they record who requested the order at the time.
        """
        with self._lock:
            rows = self._conn.execute("SELECT case_id, data FROM cases WHERE submitted_by = ?", (old,)).fetchall()
            self._conn.execute("BEGIN")
            try:
                for case_id, raw in rows:
                    d = json.loads(raw)
                    d["submitted_by"] = new
                    for line in [d["recommendation"], *d.get("extra_lines", [])]:
                        if line["request"].get("requester") == old:
                            line["request"]["requester"] = new
                    self._conn.execute("UPDATE cases SET submitted_by = ?, data = ? WHERE case_id = ?",
                                       (new, json.dumps(d), case_id))
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return len(rows)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
