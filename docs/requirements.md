# Intelligent Procurement Agent: Business Requirements

Status: DRAFT for review. No implementation will start until this document is approved.
Date: 2026-11-20

## 1. Purpose and Business Problem

Requesters submit purchase needs in free text (email, chat). Procurement staff then manually extract details, ask suppliers for quotes, compare them in spreadsheets, and seek approval. This is slow, inconsistent, and hard to audit.

The Intelligent Procurement Agent turns a natural-language request into a structured request, gathers supplier quotations, compares them on price and delivery, recommends a supplier with an explanation, and produces a purchase recommendation. A human must approve before any purchase is confirmed.

## 2. Goals and Success Measures

| Goal | Measure (proposed targets, to be confirmed) |
|---|---|
| Reduce time from request to recommendation | Under 5 minutes, excluding supplier response time |
| Reduce manual data entry | 90% of requests need no manual correction of product/quantity/date |
| Make decisions explainable | 100% of recommendations include a written rationale |
| Ensure control | 0 purchases confirmed without recorded human approval |
| Auditability | 100% of requests have a full decision trail |

## 3. Scope

### In scope
- Free-text purchase request intake
- Extraction of product, quantity, required delivery date
- Retrieval of supplier quotations (from supplier catalog/quote sources, see assumption A2)
- Comparison of price and delivery timeline
- Supplier recommendation with explanation
- Purchase recommendation document
- Human approval/rejection step before purchase confirmation
- Audit log

### Out of scope (initial release)
- Payment processing and invoicing
- Contract negotiation and supplier onboarding
- Multi-line, multi-product requests (see open question Q3)
- Budget management integration (see Q6)
- Goods receipt and returns

## 4. Stakeholders and Roles

| Role | Interest |
|---|---|
| Requester | Submits requests, tracks status |
| Procurement Approver | Reviews recommendation, approves or rejects |
| Procurement Administrator | Manages supplier list and configuration |
| Finance / Audit | Reviews decision trail and spend |
| Suppliers | Provide quotations (external systems) |

## 5. Assumptions

- A1: Each request covers one product type. Multiple line items are deferred.
- A2: Quotations come from supplier APIs, catalogs, or a mocked quote service in the first release. Real supplier integrations are added later.
- A3: Approvers are authenticated internal users.
- A4: A single currency is used (to be confirmed, Q5).
- A5: "Best supplier" is determined by a weighted score of price and delivery. Default weights are price 60%, delivery 40%, configurable.
- A6: A supplier that cannot deliver by the required date is ineligible unless no supplier can, in which case the closest options are shown with a warning.

## 6. Business Requirements

### BR-1 Request intake
- BR-1.1 The system shall accept purchase requests as free text.
- BR-1.2 The system shall assign each request a unique ID and record submitter and timestamp.

### BR-2 Information extraction
- BR-2.1 The system shall extract product, quantity, and required delivery date.
- BR-2.2 The system shall resolve relative dates ("in two weeks", "by end of month") against the submission date.
- BR-2.3 The system shall show extracted values to the requester for confirmation or correction.
- BR-2.4 If any field is missing or ambiguous, the system shall ask a clarifying question and not guess.
- BR-2.5 Dates in the past and non-positive quantities shall be rejected with a clear message.

### BR-3 Quotation retrieval
- BR-3.1 The system shall request quotations from all active suppliers that can supply the product.
- BR-3.2 Each quotation shall capture supplier, unit price, total price, currency, lead time or delivery date, quote validity, and quote reference.
- BR-3.3 The system shall tolerate supplier failures or timeouts, continue with available quotes, and report which suppliers did not respond.
- BR-3.4 Expired quotations shall be excluded.

### BR-4 Comparison
- BR-4.1 The system shall compare quotations on total price and delivery date versus required date.
- BR-4.2 The system shall flag quotations that miss the required date and show the days late.
- BR-4.3 The system shall present a side-by-side comparison.

### BR-5 Recommendation
- BR-5.1 The system shall recommend one supplier and rank the rest.
- BR-5.2 The system shall give a plain-language explanation citing price, delivery, and trade-offs versus alternatives.
- BR-5.3 The explanation shall use only data in the quotations. No invented facts.
- BR-5.4 The scoring method and weights shall be visible to the approver.

### BR-6 Purchase recommendation
- BR-6.1 The system shall generate a purchase recommendation containing request details, quotation comparison, recommended supplier, rationale, total cost, delivery date, and risks or warnings.

### BR-7 Human approval
- BR-7.1 No purchase shall be confirmed without explicit approval by an authorized human.
- BR-7.2 The approver may approve the recommendation, choose a different quoted supplier (with a reason), reject, or request changes.
- BR-7.3 Approval shall record approver identity, decision, timestamp, and comments.
- BR-7.4 Requesters shall not approve their own requests.
- BR-7.5 Recommendations expire if the chosen quote's validity lapses before approval, and the approver is warned.

### BR-8 Audit and traceability
- BR-8.1 The system shall log the original text, extracted values, corrections, quotations, scores, recommendation, and approval decision.

## 7. Non-Functional Requirements

- NFR-1 Security: role-based access; only approvers can approve; secrets stored outside code.
- NFR-2 Performance: extraction and ranking complete within 10 seconds once quotes are in hand.
- NFR-3 Reliability: partial supplier failure does not fail the whole request.
- NFR-4 Transparency: AI-generated content is labeled; rationale is traceable to quote data.
- NFR-5 Data retention: audit records retained per company policy (to be confirmed, Q7).

## 8. User Stories and Acceptance Criteria

### US-1 Submit a request in natural language
As a requester, I want to describe what I need in plain English so that I do not fill in a form.

Acceptance criteria
- Given I enter "I need 50 laptops delivered by December 15", when I submit, then a request with a unique ID is created.
- Given I submit an empty message, then I see an error and no request is created.

### US-2 Extract and confirm details
As a requester, I want to see what the system understood so that I can correct mistakes before quotes are sought.

Acceptance criteria
- Given the text above, then product = "laptops", quantity = 50, delivery date = December 15 of the next applicable year, shown for confirmation.
- Given "ASAP" or no date, then the system asks for a specific date.
- Given "some monitors", then the system asks for a quantity.
- Given a date in the past, then it is rejected with an explanation.
- Given I edit an extracted value, then the edited value is used and logged.

### US-3 Retrieve quotations
As a procurement officer, I want quotes gathered automatically so that I save time contacting suppliers.

Acceptance criteria
- Given a confirmed request, then all active suppliers for the product are queried.
- Given one supplier times out, then the others are still shown and the failure is listed.
- Given a quote is past its validity date, then it is excluded and noted.
- Given no supplier responds, then the request is marked "No quotes available" and the requester is notified.

### US-4 Compare suppliers
As a procurement officer, I want price and delivery compared side by side so that I can judge trade-offs.

Acceptance criteria
- Then each quote shows unit price, total price, delivery date, and days earlier or later than required.
- Given a quote delivers after the required date, then it is flagged "Late by N days".
- Given two quotes with equal total price, then delivery date breaks the tie.

### US-5 Receive a recommendation with explanation
As an approver, I want a recommended supplier and the reasons so that I can decide quickly and with confidence.

Acceptance criteria
- Then exactly one supplier is recommended and others are ranked.
- Then the explanation states the price and delivery of the recommendation and why it beats the next best option.
- Given the cheapest supplier is late and a pricier one is on time, then the recommendation favors the on-time supplier and says so.
- Given no supplier meets the date, then the system recommends the closest and shows a warning.
- Then every figure in the explanation matches the quote data.

### US-6 Generate a purchase recommendation
As an approver, I want a single summary document so that I can review everything in one place.

Acceptance criteria
- Then the document includes request details, comparison table, recommendation, rationale, total cost, expected delivery, and warnings.
- Then it shows the scoring weights used.

### US-7 Approve before purchase
As an approver, I want to approve or reject so that no purchase happens without my consent.

Acceptance criteria
- Given a recommendation is pending, then status is "Awaiting approval" and no purchase is confirmed.
- Given I approve, then the purchase is confirmed, and my name, time, and comments are recorded.
- Given I reject, then no purchase is made and a reason is required.
- Given I select a non-recommended supplier, then I must give a reason and it is recorded.
- Given I am the requester, then I cannot approve my own request.
- Given the quote has expired, then I am warned and approval is blocked until quotes are refreshed.
- Given a user without approver rights, then approval actions are unavailable.

### US-8 Track status
As a requester, I want to see where my request stands so that I know what is happening.

Acceptance criteria
- Statuses: Submitted, Awaiting clarification, Gathering quotes, Awaiting approval, Approved, Rejected, No quotes available.
- Status changes are visible with timestamps.

### US-9 Audit trail
As an auditor, I want the full decision history so that I can verify compliance.

Acceptance criteria
- Given any request, then I can see original text, extracted values and edits, all quotes, scores, the recommendation, and the approval decision.
- Records cannot be edited after approval.

### US-10 Configure scoring and suppliers
As a procurement administrator, I want to manage suppliers and weights so that the recommendation reflects company priorities.

Acceptance criteria
- I can activate or deactivate suppliers.
- I can set price and delivery weights summing to 100%.
- Weight changes apply to new requests only and are logged.

## 9. Recommendation Logic (proposed, for review)

1. Exclude expired quotes.
2. Mark quotes that meet the required date as eligible.
3. Normalize price and delivery to 0-100 among eligible quotes.
4. Score = price weight x price score + delivery weight x delivery score (default 60/40).
5. Highest score is recommended. Ties go to earlier delivery, then lower price.
6. If none are eligible, rank by days late, then price, and attach a warning.

## 10. Process Flow

Submit text -> Extract fields -> Requester confirms or clarifies -> Retrieve quotes -> Compare and score -> Recommend and explain -> Generate purchase recommendation -> Human approval -> Confirm purchase (or reject) -> Audit log.

## 11. Risks

| Risk | Mitigation |
|---|---|
| Misread product, quantity, or date | Confirmation step; clarifying questions |
| Inaccurate or invented explanation | Explanation built only from quote data; figures checked |
| Supplier outages | Partial results; failure reporting |
| Rubber-stamp approvals | Show alternatives, warnings, and score breakdown |
| Unauthorized purchase | Approval gate and role checks |

## 12. Open Questions for Review

- Q1: Which suppliers and quote sources are available? Is a mock quote service acceptable for the first release?
- Q2: Are the default weights (price 60 / delivery 40) acceptable? Should other factors (supplier rating, payment terms) be included?
- Q3: Must a request support multiple products?
- Q4: Does "confirming a purchase" mean creating a PO in an ERP, sending an email to the supplier, or only recording the decision?
- Q5: Single currency or multi-currency?
- Q6: Is there a budget limit or spend threshold that changes who must approve?
- Q7: Retention period and compliance requirements for audit records?
- Q8: Preferred interface: web chat, email, or Slack/Teams?
- Q9: Should a late supplier ever be recommended over an on-time one if much cheaper?
- Q10: Is one approver enough, or are multi-level approvals needed?

## 13. Review Sign-off

| Name | Role | Decision | Date |
|---|---|---|---|
| | | | |
