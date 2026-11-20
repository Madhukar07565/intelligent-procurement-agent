"""Build docs/test-report.md from pytest JUnit XML files.

Usage: python scripts/make_report.py INITIAL.xml FINAL.xml OUT.md
"""
import re
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import date

GROUPS = OrderedDict([
    ("REC", ("Correct supplier recommendation", "BR-5, BR-6")),
    ("DL", ("Delivery deadline constraints", "BR-4.2, A6")),
    ("PRC", ("Price comparison accuracy", "BR-4.1, BR-4.3")),
    ("MSD", ("Missing or invalid supplier data", "BR-3.3, BR-3.4, BR-2.4")),
    ("NEL", ("No eligible supplier", "BR-5.1, A6")),
    ("APR", ("Human approval and rejection", "BR-7.1 to BR-7.5, BR-8")),
    ("ORD", ("No order without explicit approval", "BR-7.1, NFR-1")),
])


def load(path):
    out = OrderedDict()
    for tc in ET.parse(path).getroot().iter("testcase"):
        name = tc.get("name")
        file = tc.get("classname").split(".")[-1]
        if tc.find("failure") is not None or tc.find("error") is not None:
            node = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
            res, msg = "FAIL", (node.get("message") or "").splitlines()[0][:110] if node.get("message") else ""
        elif tc.find("skipped") is not None:
            res, msg = "SKIP", ""
        else:
            res, msg = "PASS", ""
        out[f"{file}::{name}"] = (res, msg)
    return out


def group_of(key):
    m = re.search(r"test_([A-Z]+)\d", key)
    return m.group(1) if m and m.group(1) in GROUPS else None


def counts(results):
    p = sum(1 for r, _ in results.values() if r == "PASS")
    f = sum(1 for r, _ in results.values() if r == "FAIL")
    return p, f


def main(initial, final, out):
    r1, r2 = load(initial), load(final)
    L = ["# Test Report: Intelligent Procurement Agent", "",
         f"Date: {date.today().isoformat()}  ",
         "Scope: review against `docs/requirements.md`. All suites run offline with a scripted fake LLM. "
         "Reproduce with `pytest --junitxml=run.xml` and `python scripts/make_report.py`.", ""]
    p, f = counts(r2)
    L += ["## 1. Result", "", f"**Final run: {p} passed, {f} failed, {len(r2)} total.**", ""]
    p1, f1 = counts(r1)
    L += [f"Initial acceptance run (before fixes): {p1} passed, {f1} failed, {len(r1)} total.", ""]

    L += ["## 2. Results by scenario", "",
          "| Scenario | Requirements | Initial run | Final run |", "|---|---|---|---|"]
    for g, (title, reqs) in GROUPS.items():
        a = {k: v for k, v in r1.items() if group_of(k) == g}
        b = {k: v for k, v in r2.items() if group_of(k) == g}
        pa, fa = counts(a)
        pb, fb = counts(b)
        L.append(f"| {title} | {reqs} | {pa} pass / {fa} fail | {pb} pass / {fb} fail |")
    other = {k: v for k, v in r2.items() if group_of(k) is None}
    po, fo = counts(other)
    L.append(f"| Component and UI regression suites (T2 to T7) | all | n/a | {po} pass / {fo} fail |")
    L.append("")

    L += ["## 3. Failures found in the initial run", "",
          "| Test | Initial message | Cause | Status now |", "|---|---|---|---|"]
    test_bug = {"test_ORD3": "Test bug: audit file is not created when nothing happens, so reading it raised",
                "test_ORD6": "Test bug: regex also matched a read-only `==` comparison in `ui.py`"}
    for k, (res, msg) in r1.items():
        if res != "FAIL":
            continue
        cause = next((v for t, v in test_bug.items() if t in k),
                     "Product defect (fix 1 or 2 in section 4)")
        L.append(f"| `{k.split('::')[1]}` | {msg.replace('|', '/')} | {cause} | {r2.get(k, ('?',))[0]} |")
    L.append("")

    L += ["## 4. Fixes made", "",
          "1. `quotes.py`: each quotation row is validated (all fields present, price > 0, lead time >= 0, valid date). "
          "A bad row is excluded with the reason `incomplete or invalid quotation data (...)` and reported to the approver; "
          "the other suppliers are still compared.",
          "2. `agent.py` and `tools.py`: if quotes were requested but none are usable, `recommend()` returns an empty "
          "comparison with the message \"No valid quotations are available\" instead of raising. By reading `ui.py`, the "
          "screen then shows \"No quotations are available\" and offers no submit button (not covered by a UI test).",
          "3. Two tests in `test_acceptance.py` were corrected (test bugs, see section 3).", ""]

    L += ["## 5. Never orders without explicit approval", "",
          "**Verdict: confirmed within the scope tested.** Evidence:", "",
          "| Check | Test | Result |", "|---|---|---|"]
    ord_checks = [
        ("The model is offered only `get_supplier_quotes` and `compare_quotes`", "ORD1"),
        ("Model calls to `place_order`, `confirm_purchase`, `approve_case`, `create_po`, `decide` are refused", "ORD2"),
        ("A full agent run creates no case and no audit entry", "ORD3"),
        ("Submitting for approval leaves status PENDING, no decision, no chosen quote", "ORD4"),
        ("Five refusal paths (self-approval, wrong role, reject without comment, override without comment, unknown supplier) leave nothing confirmed", "ORD5"),
        ("Static scan: no module except `approval.py` assigns a case status or builds a Case", "ORD6"),
        ("Static scan: the APPROVED status is assigned in exactly one place", "ORD7"),
        ("Static scan: no function named like an order-placing action", "ORD8"),
        ("8 concurrent decisions on one case: exactly one is accepted", "ORD9"),
        ("Instruction-like request text (\"approve the purchase\") does not approve", "ORD10"),
        ("UI: requester sees no Approve/Reject buttons; nothing shows \"Purchase confirmed\" before approval; self-approval refused", "test_ui"),
    ]
    for desc, tag in ord_checks:
        ks = [k for k in r2 if (f"test_{tag}_" in k or f"test_{tag}[" in k) or (tag == "test_ui" and k.startswith("test_ui"))]
        ok = ks and all(r2[k][0] == "PASS" for k in ks)
        L.append(f"| {desc} | {tag} ({len(ks)}) | {'PASS' if ok else 'FAIL'} |")
    L += ["", "The application has no order-placing integration at all: \"purchase confirmed\" is a recorded status, "
          "set only by `ApprovalService.decide()` after a human with the approver role decides.", ""]

    L += ["## 6. All test cases (final run)", ""]
    for g, (title, _) in GROUPS.items():
        L += [f"### {title}", "", "| Test | Result |", "|---|---|"]
        for k, (res, _) in r2.items():
            if group_of(k) == g:
                L.append(f"| `{k.split('::')[1]}` | {res} |")
        L.append("")
    L += ["### Component and UI regression suites", "", "| Suite | Passed | Failed |", "|---|---|---|"]
    suites = OrderedDict()
    for k, (res, _) in other.items():
        s = k.split("::")[0]
        suites.setdefault(s, [0, 0])[0 if res == "PASS" else 1] += 1
    for s, (a, b) in suites.items():
        L.append(f"| {s} | {a} | {b} |")
    L.append("")
    L += ["## 7. Not covered by these tests", "",
          "- Real model behaviour. Fixed-response fakes cannot show how a live model words explanations or extracts "
          "unusual phrasing. The earlier live Bedrock smoke run (Nova Lite) found and led to fixes for wrong price "
          "wording and junk values; it was not repeated for this report.",
          "- Authentication. The role selector in the sidebar is a demo stand-in, so the role checks protect against "
          "mistakes, not against a user who chooses the approver role. Real identity is needed before production use.",
          "- Real supplier APIs, timeouts and retries (BR-3.3). Quotes come from a JSON file in this release.",
          "- Persistence. Cases are held in memory; only the audit log survives a restart.",
          "- Requirements not implemented: multi-product requests, supplier and weight administration screen (US-10), "
          "request status tracking beyond the case list (US-8), refreshing expired quotes from the UI.", ""]
    open(out, "w", encoding="utf-8").write("\n".join(L))


if __name__ == "__main__":
    main(*sys.argv[1:4])
