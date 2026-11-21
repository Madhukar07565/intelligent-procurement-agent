# Intelligent Procurement Agent: Hackathon Architecture

> This describes the current local build. The proposed AWS target architecture, following the AgentCore end-to-end blueprint, is in [architecture/agentcore-design.md](architecture/agentcore-design.md).

Target: 4 hours, one developer. Python 3.11, Amazon Bedrock (Converse API), Streamlit, JSON quote file.

## 1. Design principles

1. **LLM understands and explains. Python decides and enforces.** The model extracts fields, chooses tools and writes the explanation. Ranking math and the approval gate are plain Python, so they are testable and cannot be talked around.
2. **No purchase tool exists.** The model has no way to confirm a purchase. Only the approval service, called from a Streamlit button, can do that.
3. **LLM behind an interface.** Tests use a fake client, so everything except the Bedrock call runs offline.
4. **Small local stores.** The supplier catalogue is a JSON file. Requests, decisions and alerts are kept in SQLite, the audit trail in a JSON-lines file, and POs as PDF and JSON files.

> **Current build (updated 21 November 2026).** Manufacturing products from five simulated supplier catalogues (real supplier names, mocked prices), technical spec matching, multi-product requests split into one approval request and one purchase order per supplier, separate requester and approver logins, and approver alerts.

## 2. Architecture diagram

Rendered: [architecture/current-build.png](architecture/current-build.png)

```mermaid
flowchart LR
    R[Requester] --> UI
    A[Approver] --> UI
    UI[Streamlit app<br/>app.py, ui.py<br/>login, live agent panel] --> AUTH[auth.py<br/>users.json, scrypt hashes]
    UI --> AG[ProcurementAgent<br/>agent.py]
    AG <-->|Converse API + tools<br/>rate limit under 1 req/s| BR[(Amazon Bedrock<br/>Nova Lite, us-east-1)]
    AG -->|tool call per product line| TR[ToolRegistry<br/>tools.py]
    TR --> QT[get_supplier_quotes]
    TR --> CT[compare_quotes]
    QT --> QR[QuoteRepository<br/>quotes.py: volume price,<br/>stock, MOQ, budget]
    QR --> SP[specs.py<br/>unit conversion,<br/>spec checks]
    QR --> JS[(data/quotes.json<br/>5 suppliers, 29 models<br/>mocked prices)]
    CT --> CMP[comparison.py<br/>deadline first,<br/>60% price / 40% delivery]
    AG -.->|BuildRecommendation:<br/>lines + PO plan| UI
    UI -->|submit_build:<br/>1 request per supplier| AP[ApprovalService<br/>approval.py]
    AP --> DB[(data/cases.db<br/>SQLite: requests, alerts)]
    AP --> NT[notifications.py<br/>in-app alerts, optional SNS email]
    AP -->|on approval:<br/>1 PO per request| PO[po.py, po_pdf.py<br/>PDF + JSON POs]
    AP --> AUD[(data/audit.jsonl)]
```

## 3. Flow

1. **Extract:** the requester describes one or several products. The agent calls Bedrock with a forced `extract_request` tool. It returns product, quantity, technical specs and budget for each product, plus one required date. Python validates every value, converts units (bar to psi, inches to mm), and splits specs the model merged, using the words in the catalogue.
2. **Confirm:** the UI shows one block per product with an editable requirements table. Products can be excluded. Missing fields are asked for, never guessed.
3. **Search:** the agent runs a tool loop. For each product line the model calls `get_supplier_quotes`, then `compare_quotes`. The confirmed values for that line always apply. `get_supplier_quotes` searches every supplier catalogue for the category and checks each model's specs. It applies volume pricing, stock, minimum order and budget, and keeps each supplier's best qualifying model. Rejected models are listed with their reasons. Any line the model skips is completed by the app. Bedrock then writes the summary. The live panel shows each step.
4. **Plan:** lines won by the same supplier are grouped. The requester sees one card per supplier, which is one approval request and one purchase order.
5. **Submit:** one click creates one approval request per supplier, linked by an order ID, and alerts the approvers.
6. **Decide:** each request is approved or rejected on its own. The approver can move a request to another supplier only if that supplier quoted every product in it, and only with a comment. Role, self-approval, quote expiry and one-decision rules apply.
7. **Purchase order:** approval issues exactly one numbered PDF PO per request, listing all of that supplier's products, with RoyalCyber as buyer.

## 4. Components

| Component | File | Responsibility |
|---|---|---|
| Models | `models.py` | `PurchaseRequest`, `Quote`, `ScoredQuote`, `Comparison`, `Recommendation`, `BuildRecommendation`, `Decision`, `group_by_supplier` |
| Specs | `specs.py` | Spec schema per category, unit conversion, requirement parsing, spec checks, merged-spec splitting |
| QuoteRepository | `quotes.py` | Catalogue search per supplier, validation, volume pricing, stock, MOQ, budget, progress events |
| Comparison | `comparison.py` | Eligibility, normalization, weighted score, tie-breaks, late flags |
| Tools | `tools.py` | Tool specs (Bedrock format) and a line-aware registry that enforces the confirmed request |
| LLM client | `llm.py` | `BedrockClient` (Converse), shared rate limiter, retries |
| Agent | `agent.py` | `extract_request()`, `validate_lines()`, `recommend()`, `recommend_plan()` |
| ApprovalService | `approval.py` | `submit_build()` (one request per supplier), decisions, PO issuing, audit log |
| Store | `store.py` | SQLite persistence of requests |
| Auth | `auth.py` | Requester and approver accounts, scrypt hashes, lockout |
| Notifications | `notifications.py` | In-app approver alerts, optional Amazon SNS email |
| Purchase orders | `po.py`, `po_pdf.py` | Numbered PO records and multi-line PDF documents |
| UI | `app.py`, `ui.py` | Streamlit screens for both roles, live agent activity panel |

## 5. Project structure

```
procurement_agent/
  app.py
  requirements.txt
  README.md
  data/
    quotes.json
  src/procurement/
    __init__.py
    models.py
    quotes.py
    comparison.py
    tools.py
    llm.py
    agent.py
    approval.py
    ui.py            # Streamlit screens, injectable for tests
  tests/
    conftest.py
    test_quotes.py
    test_comparison.py
    test_tools.py
    test_agent.py
    test_approval.py
    test_ui.py
    fakes.py
```

## 6. Data

`quotes.json` (one entry per supplier quote):

```json
{
  "supplier": "Acme Supplies",
  "product": "laptop",
  "unit_price": 950.0,
  "currency": "USD",
  "lead_time_days": 10,
  "valid_until": "2026-12-31",
  "quote_ref": "ACM-1001"
}
```

Delivery date = request date + `lead_time_days`. Total = `unit_price x quantity`. Product matching is a case-insensitive match on a normalized name plus a small alias list.

## 7. Tool definitions and interfaces

Tool specs use the Bedrock Converse `toolSpec` format.

### 7.1 `extract_request` (forced on step 1)
Input:
```json
{"product": "string", "quantity": "integer", "required_date": "YYYY-MM-DD", "missing": ["string"]}
```
`product`, `quantity`, `required_date` are optional. Unknown fields go in `missing`. The prompt includes today's date so relative dates resolve correctly. Python validates the result (quantity > 0, date not in the past).

### 7.2 `get_supplier_quotes`
Input: `{"product": "string", "quantity": "integer"}`
Output:
```json
{"quotes": [{"supplier": "...", "quote_ref": "...", "unit_price": 0, "total_price": 0,
             "currency": "USD", "lead_time_days": 0, "delivery_date": "YYYY-MM-DD"}],
 "excluded": [{"supplier": "...", "reason": "expired"}]}
```

### 7.3 `compare_quotes`
Input: `{"required_date": "YYYY-MM-DD", "price_weight": 0.6, "delivery_weight": 0.4}`

The tool scores the quotes stored by the last `get_supplier_quotes` call. The model does not pass quotes back in, so it cannot change prices or dates between the two calls.
Output:
```json
{"ranked": [{"supplier": "...", "total_price": 0, "delivery_date": "...", "days_late": 0,
             "eligible": true, "score": 0.0}],
 "recommended": "supplier name or null",
 "warnings": ["..."]}
```

### 7.4 Python interfaces

```python
class QuoteRepository:
    def find(self, product: str, quantity: int, today: date) -> tuple[list[Quote], list[dict]]: ...

def compare(quotes: list[Quote], required_date: date,
            price_weight: float = 0.6, delivery_weight: float = 0.4) -> Comparison: ...

class LLMClient(Protocol):
    def converse(self, system: str, messages: list[dict], tools: list[dict] | None,
                 force_tool: str | None = None) -> dict: ...   # Bedrock Converse-shaped response

class ProcurementAgent:
    def extract_request(self, text: str, today: date, requester: str = "") -> ExtractionResult: ...  # request or missing/errors
    def recommend(self, request: PurchaseRequest, today: date) -> Recommendation: ...

class ApprovalService:
    def submit(self, rec: Recommendation, submitted_by: str) -> str: ...        # returns case id
    def decide(self, case_id: str, user: User, approve: bool, comment: str,
               chosen_supplier: str | None = None) -> Decision: ...
```

## 8. Scoring (from requirements section 9)

1. Eligible = delivery_date <= required_date.
2. Among eligible quotes, price score = (max - price) / (max - min) x 100 and delivery score likewise; if max == min the score is 100.
3. Score = 0.6 x price + 0.4 x delivery. Ties: earlier delivery, then lower price.
4. If none are eligible: rank by days late, then price, and add a warning.

## 9. Approval workflow

States: `PENDING_APPROVAL -> APPROVED -> PO_ISSUED`, or `PENDING_APPROVAL -> REJECTED`. On approval, `ApprovalService` calls a `PurchaseOrderIssuer` (`po.py`). The file issuer writes `data/purchase_orders/PO-YYYY-NNNN.pdf` (the document sent to the supplier) and `.json` (the record). If issuing fails, the case stays APPROVED and an approver can retry; a case never gets two POs. Rules: requester cannot approve their own case, only role `approver` may decide, a decision is final, a rejection needs a comment, choosing a non-recommended supplier needs a comment, and expired quotes block approval. Each transition appends a line to `audit.jsonl`.

## 10. Configuration

Environment variables: `AWS_REGION`, `BEDROCK_MODEL_ID` (any Converse-capable model with tool use), `QUOTES_PATH`, `AUDIT_PATH`. Credentials come from the standard AWS chain.

## 11. Implementation tasks (about 4 hours)

| # | Task | Est. | Validation |
|---|---|---|---|
| T1 | Scaffold, models, sample `quotes.json`, deps | 20 min | Import test, JSON loads |
| T2 | QuoteRepository | 25 min | `test_quotes.py` |
| T3 | Comparison engine | 35 min | `test_comparison.py` |
| T4 | Tool specs and dispatcher | 25 min | `test_tools.py` |
| T5 | LLM client and agent (extract + tool loop) with fake client | 50 min | `test_agent.py`, one live Bedrock smoke call |
| T6 | ApprovalService and audit log | 30 min | `test_approval.py` |
| T7 | Streamlit UI | 40 min | Manual run, Streamlit AppTest |
| T8 | README and demo script | 15 min | Demo walk-through |

## 12. Test cases

**Quotes (T2)**
- Q1 matches product case-insensitively and by alias ("laptops" matches laptop).
- Q2 expired quotes are excluded and reported.
- Q3 total price = unit price x quantity; delivery date = today + lead time.
- Q4 unknown product returns empty list.

**Comparison (T3)**
- C1 cheapest on-time supplier wins when delivery is equal.
- C2 cheapest but late supplier loses to an on-time one.
- C3 no supplier on time: closest wins and a warning is present.
- C4 equal score: earlier delivery wins, then lower price.
- C5 single quote: it is recommended with score 100.
- C6 empty input: no recommendation, warning present.
- C7 weights not summing to 1 are rejected.

**Tools (T4)**
- T-1 each spec has name, description and valid input schema.
- T-2 dispatcher routes by name and returns JSON-serializable output.
- T-3 unknown tool or bad arguments return an error result and do not raise.

**Agent (T5, fake LLM)**
- A1 extraction returns a validated `PurchaseRequest`.
- A2 missing quantity or date is reported, not guessed.
- A3 past date and quantity <= 0 are rejected.
- A4 tool loop executes `get_supplier_quotes` then `compare_quotes` and returns the explanation.
- A5 loop stops after the max iteration count.
- A6 the recommended supplier in the result comes from `compare_quotes` output, not model text.

**Approval (T6)**
- P1 approve by an approver changes state to APPROVED and writes an audit line.
- P2 requester cannot approve own case.
- P3 non-approver is refused.
- P4 reject without a comment is refused.
- P5 second decision on a decided case is refused.
- P6 choosing a different supplier requires a comment.
- P7 expired quote blocks approval.

**UI (T7)**
- U1 Approve button is not shown to the requester role.
- U2 No purchase status is shown as confirmed before approval.

## 13. Risks and shortcuts

- Bedrock model access must be enabled in the account and region beforehand.
- Date extraction can drift, so the user confirms values before quotes are fetched.
- The UI role selector stands in for real authentication in the hackathon.
