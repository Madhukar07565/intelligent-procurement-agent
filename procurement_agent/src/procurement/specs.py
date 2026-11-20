"""Technical specifications for manufacturing products, and checks against requirements.

Each category declares its specs. A requirement such as "range 0-150 psi" or
"accuracy 0.25% or better" becomes a Requirement; `check` compares it with a
catalogue model's specs after converting units. All decisions here are plain
Python so they are testable and cannot be changed by the model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# kind: "number" (with a unit family) | "text" (substring match) | "ip" (IP code, higher is better)
# op: comparison applied when the requester gives a value (">=": at least, "<=": at most, "=": equals)
SCHEMA: dict[str, dict[str, dict[str, Any]]] = {
    "pressure sensor": {
        "range_max": {"label": "Pressure range (max)", "kind": "number", "unit": "psi", "op": ">="},
        "output": {"label": "Output signal", "kind": "text", "op": "="},
        "accuracy_pct": {"label": "Accuracy (% of span)", "kind": "number", "unit": "%", "op": "<="},
        "connection": {"label": "Process connection", "kind": "text", "op": "="},
        "ip_rating": {"label": "Ingress protection", "kind": "ip", "op": ">="},
        "temp_max": {"label": "Max process temperature", "kind": "number", "unit": "C", "op": ">="},
    },
    "temperature sensor": {
        "sensor_type": {"label": "Sensor type", "kind": "text", "op": "="},
        "range_max": {"label": "Max temperature", "kind": "number", "unit": "C", "op": ">="},
        "accuracy_class": {"label": "Accuracy class", "kind": "text", "op": "="},
        "connection": {"label": "Process connection", "kind": "text", "op": "="},
        "probe_length": {"label": "Probe length", "kind": "number", "unit": "mm", "op": ">="},
    },
    "flow meter": {
        "meter_type": {"label": "Meter type", "kind": "text", "op": "="},
        "pipe_size": {"label": "Pipe size", "kind": "number", "unit": "mm", "op": "="},
        "output": {"label": "Output signal", "kind": "text", "op": "="},
        "accuracy_pct": {"label": "Accuracy (% of rate)", "kind": "number", "unit": "%", "op": "<="},
        "ip_rating": {"label": "Ingress protection", "kind": "ip", "op": ">="},
    },
    "level sensor": {
        "sensor_type": {"label": "Sensor type", "kind": "text", "op": "="},
        "range_max": {"label": "Measuring range", "kind": "number", "unit": "mm", "op": ">="},
        "output": {"label": "Output signal", "kind": "text", "op": "="},
        "ip_rating": {"label": "Ingress protection", "kind": "ip", "op": ">="},
    },
    "proximity sensor": {
        "sensing_distance": {"label": "Sensing distance", "kind": "number", "unit": "mm", "op": ">="},
        "output": {"label": "Output", "kind": "text", "op": "="},
        "housing": {"label": "Housing", "kind": "text", "op": "="},
        "ip_rating": {"label": "Ingress protection", "kind": "ip", "op": ">="},
    },
}

# Unit families: factor to the canonical unit. Temperature is handled separately (offset).
_UNITS = {
    "psi": {"psi": 1.0, "psig": 1.0, "bar": 14.5038, "mbar": 0.0145038, "kpa": 0.145038, "mpa": 145.038},
    "mm": {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "inch": 25.4, '"': 25.4, "ft": 304.8},
    "%": {"%": 1.0, "pct": 1.0, "percent": 1.0},
}
OPS = (">=", "<=", "=")


@dataclass(frozen=True)
class Requirement:
    spec: str
    value: Any                 # canonical: float for numbers, str for text and ip
    op: str = "="
    unit: str = ""             # canonical unit, for display
    original: str = ""         # what the requester said, e.g. "150 psi"

    def to_dict(self) -> dict[str, Any]:
        return {"spec": self.spec, "value": self.value, "op": self.op, "unit": self.unit, "original": self.original}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Requirement":
        return Requirement(d["spec"], d["value"], d.get("op", "="), d.get("unit", ""), d.get("original", ""))

    def describe(self, category: str) -> str:
        label = SCHEMA.get(category, {}).get(self.spec, {}).get("label", self.spec)
        word = {">=": "at least", "<=": "at most", "=": ""}[self.op]
        value = fmt_value(self.value, self.unit)
        return f"{label}: {word} {value}".replace(":  ", ": ")


def fmt_value(value: Any, unit: str = "") -> str:
    if isinstance(value, (int, float)) and unit == "mm" and value >= 1000:
        value, unit = value / 1000, "m"
    if isinstance(value, (int, float)):
        v = f"{round(value, 2) if abs(value) < 10 else round(value, 1):g}"
        return f"{v}{unit}" if unit in ("%",) else f"{v} {unit}".strip()
    return str(value)


def _norm_text(s: Any) -> str:
    s = str(s).lower().replace("–", "-").replace("—", "-").replace('"', " ").replace("inch", " ")
    s = re.sub(r"(\d)\s*-\s*(\d)", r"\1-\2", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"(\d) (ma|v)\b", r"\1\2", s).strip()


def _parse_number(raw: Any) -> tuple[float, str]:
    """'150 psi' -> (150.0, 'psi'); '0-150 psi' -> (150.0, 'psi'); 2 -> (2.0, '')."""
    if isinstance(raw, (int, float)):
        return float(raw), ""
    text = str(raw).strip().lower().replace(",", "")
    # A hyphen directly after a digit is a range ("0-150"), not a minus sign.
    nums = re.findall(r"(?<![\d.])-?\d+(?:\.\d+)?", text)
    if not nums:
        raise ValueError(f"no number in {raw!r}")
    unit = re.sub(r"[-\d.\s]+", " ", text).strip().split(" ")[-1] if re.search(r"[a-z%\"°]", text) else ""
    return float(nums[-1]), unit.replace("°", "")


def to_canonical(spec_def: dict, raw: Any, unit: str = "") -> float:
    value, parsed_unit = _parse_number(raw)
    unit = (unit or parsed_unit or spec_def["unit"]).lower().replace("°", "").strip()
    canonical = spec_def["unit"]
    if canonical == "C":
        if unit in ("f", "degf", "fahrenheit"):
            return round((value - 32) * 5 / 9, 2)
        if unit in ("c", "degc", "celsius", ""):
            return value
        raise ValueError(f"unknown temperature unit {unit!r}")
    table = _UNITS[canonical]
    if unit in ("", canonical.lower()):
        return value
    if unit not in table:
        raise ValueError(f"unknown unit {unit!r} for {spec_def['label']}")
    return round(value * table[unit], 4)


def _ip_level(code: Any) -> int:
    m = re.search(r"ip\s*(\d)(\d)", str(code).lower())
    if not m:
        raise ValueError(f"not an IP code: {code!r}")
    return int(m.group(1)) * 10 + int(m.group(2))


def parse_requirements(category: str, items: list[dict] | None) -> tuple[list[Requirement], list[str]]:
    """Turn model-extracted items into validated Requirements. Returns (requirements, notes)."""
    schema = SCHEMA.get(category)
    reqs: list[Requirement] = []
    notes: list[str] = []
    if not items:
        return reqs, notes
    if schema is None:
        return reqs, [f"Technical requirements are not checked for {category} products."]
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("spec", "")).strip()
        if key not in schema:
            notes.append(f"Ignored unknown requirement '{key}' for {category}.")
            continue
        if key in seen:
            continue
        d = schema[key]
        raw, unit = item.get("value"), str(item.get("unit") or "")
        original = f"{raw} {unit}".strip()
        op = item.get("op") if item.get("op") in OPS else d["op"]
        try:
            if d["kind"] == "number":
                value: Any = to_canonical(d, raw, unit)
                unit_out = d["unit"]
                if unit_out == "C":
                    unit_out = "°C"
            elif d["kind"] == "ip":
                value, unit_out = f"IP{_ip_level(raw):02d}", ""
            else:
                value, unit_out = str(raw).strip(), ""
                if not value:
                    raise ValueError("empty value")
        except (ValueError, KeyError) as exc:
            notes.append(f"Could not read requirement {d['label']} = {original!r} ({exc}).")
            continue
        seen.add(key)
        reqs.append(Requirement(key, value, op, unit_out, original))
    return reqs, notes


@dataclass(frozen=True)
class Check:
    label: str
    ok: bool
    detail: str  # e.g. "0-150 psi meets at least 150 psi"


def check(category: str, specs: dict[str, Any], reqs: list[Requirement] | tuple) -> list[Check]:
    """Compare a catalogue model's specs with every requirement."""
    schema = SCHEMA.get(category, {})
    out: list[Check] = []
    for r in reqs:
        d = schema.get(r.spec)
        if d is None:
            continue
        have = specs.get(r.spec)
        want = r.describe(category).split(": ", 1)[1]
        if have is None:
            out.append(Check(d["label"], False, f"not stated by supplier (required {want})"))
            continue
        if d["kind"] == "number":
            have_v = to_canonical(d, have)
            ok = {">=": have_v >= r.value, "<=": have_v <= r.value, "=": abs(have_v - r.value) < 1e-6}[r.op]
            shown = fmt_value(have_v, r.unit)
        elif d["kind"] == "ip":
            ok = _ip_level(have) >= _ip_level(r.value) if r.op == ">=" else _ip_level(have) == _ip_level(r.value)
            shown = str(have)
        else:
            ok = _norm_text(r.value) in _norm_text(have)
            shown = str(have)
        out.append(Check(d["label"], ok, f"{shown} {'meets' if ok else 'does not meet'} {want}".strip()))
    return out


def summarize_specs(category: str, specs: dict[str, Any]) -> str:
    """'0-150 psi · 4-20 mA · 0.25% · 1/4" NPT · IP65' for tables and the PO."""
    schema = SCHEMA.get(category, {})
    parts = []
    for key, d in schema.items():
        if key in specs:
            v = specs[key]
            if key == "range_max" and d.get("unit") == "psi":
                # Show the supplier's own figure ("0-16 bar"), not a converted one.
                parts.append(f"0-{v}" if isinstance(v, str) else f"0-{fmt_value(float(v))} psi")
            elif d["kind"] == "number" and d["unit"] == "%":
                parts.append(f"±{fmt_value(float(v), '%')}")
            elif d["kind"] == "number" and d["unit"] == "C":
                parts.append(f"{fmt_value(float(v))} °C")
            elif d["kind"] == "number" and d["unit"] == "mm":
                parts.append(fmt_value(to_canonical(d, v), "mm"))
            else:
                parts.append(str(v))
    return " · ".join(parts)


def extraction_guide() -> str:
    """Text for the extraction prompt listing categories and spec keys."""
    lines = []
    for cat, specs in SCHEMA.items():
        keys = ", ".join(f"{k} ({d['label']}{', ' + d['unit'] if d.get('unit') else ''})" for k, d in specs.items())
        lines.append(f"- {cat}: {keys}")
    return "\n".join(lines)
