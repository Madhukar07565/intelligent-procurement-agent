# Intelligent Procurement Agent

Natural-language purchase request -> extracted fields -> supplier quotes (JSON) -> ranked comparison -> recommendation -> human approval.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

AWS credentials must be available (standard boto3 chain) with access to a Bedrock model that supports tool use in your region.

| Variable | Default |
|---|---|
| `AWS_REGION` | `us-east-1` |
| `BEDROCK_MODEL_ID` | `us.amazon.nova-lite-v1:0` |
| `QUOTES_PATH` | `data/quotes.json` |
| `AUDIT_PATH` | `data/audit.jsonl` |
| `BEDROCK_MIN_INTERVAL_SECONDS` | `1.2` (cannot be set below 1.05; hackathon rule is under 1 request/second) |
| `PO_DIR` | `data/purchase_orders` |
| `BUYER_NAME`, `BUYER_ADDRESS`, `BUYER_EMAIL` | RoyalCyber, 55 Shuman Blvd, Suite 275, Naperville, Illinois 60563, USA; email is a placeholder. Printed on the PO PDF |

## Run

```bash
.venv/bin/streamlit run app.py
```

## Test

```bash
.venv/bin/pytest -q
```

Tests run offline with a fake LLM.

## Demo script

1. As `alice` (requester): "I need 50 laptops delivered by December 15" -> Extract details -> Confirm and get quotes -> Submit for approval.
2. Switch the sidebar to name `bob`, role `approver`, open the Approvals tab -> Approve (or Reject with a comment). Approval issues a purchase order (for example `PO-2026-0001`), shown on the case with a **Download PO (PDF)** button and saved as PDF (for the supplier) and JSON (record) in `data/purchase_orders/`.
3. Try "some monitors asap" to see the clarification step.
4. Try approving as `alice` with the approver role to see the self-approval block.
5. `data/audit.jsonl` holds the decision trail.

## Design notes

- The LLM extracts fields, calls tools, and writes the explanation. Ranking (`comparison.py`) and the approval gate (`approval.py`) are plain Python.
- The model has no purchase tool. Only `ApprovalService.decide()` can move a case to APPROVED, and a PO is generated only for an APPROVED case (status PO_ISSUED), at most once per case.
- PO generation sits behind `PurchaseOrderIssuer` (`po.py`). Email, ERP or queue delivery can be added as another issuer without changing the approval logic.
- `compare_quotes` scores the quotes stored by `get_supplier_quotes`, and the agent forces the confirmed delivery date, so the model cannot alter prices or dates.

## Hackathon rules in code

- Region `us-east-1`; synthetic data only (`data/quotes.json`); no secrets in the repo.
- Bedrock under 1 request/second: every call, including retries, passes one process-wide rate limiter
  in `llm.py` (default 1.2 s between calls). botocore retries are disabled so they cannot bypass it.
  Throttling is retried with backoff (2, 4, 8 s) and then shown as "The AI service is busy".

## Change workflow

`main` holds reviewed work. Make changes on a branch, run `.venv/bin/pytest -q`, and merge only after
a person has reviewed the diff:

```bash
git switch -c feature/<name>
# ...edit, test...
git commit -am "Describe the change"
git switch main && git merge --no-ff feature/<name>   # after review
```
