# Intelligent Procurement Agent: AgentCore Target Architecture

Status: PROPOSED, for review before implementation. Nothing in this document is deployed yet.
Date: 2026-11-20

Reference pattern: [awslabs/agentcore-samples, 05-blueprints/end-to-end-customer-service-agent](https://github.com/awslabs/agentcore-samples/tree/main/05-blueprints/end-to-end-customer-service-agent) (MIT-0). Content from that repository is summarized, not copied.

## 1. Diagrams

- Platform architecture: [agentcore-architecture.svg](agentcore-architecture.svg) (PNG: [agentcore-architecture.png](agentcore-architecture.png))
- End-to-end interaction flow: [sequence.mmd](sequence.mmd) (PNG: [sequence.png](sequence.png))

The layout follows the blueprint's two diagrams: the platform view (users and Streamlit on the left, AgentCore in the middle, Amazon Bedrock below, data on the right) and the numbered user interaction sequence.

## 2. Rules taken from the blueprint

The blueprint is a customer service agent. Its structure, read from its README and `infra/main.tf`, reduces to these rules. Each rule below says how this project applies it.

| # | Blueprint rule | How the procurement agent applies it | Today | Change needed |
|---|---|---|---|---|
| R1 | The agent runs as a container on **AgentCore Runtime** (image in ECR, HTTP protocol), not on a server you manage. | `agent.py` becomes the Runtime entrypoint. | Runs in-process inside Streamlit | Add Runtime entrypoint and Dockerfile; image pushed to ECR by CDK |
| R2 | Users sign in with **Amazon Cognito**. The Runtime and Gateway use a Cognito **JWT authorizer**, so only signed-in users can call the agent. | Cognito user pool with `requester` and `approver` groups. The role comes from the `cognito:groups` claim. | Local `users.json` with scrypt hashes | Replace `auth.py` with Cognito sign-in |
| R3 | Tools are reached through **AgentCore Gateway** (MCP), not called directly by the agent. | `get_supplier_quotes` and `compare_quotes` become Lambda targets behind the Gateway. Their input schemas stay as in `tools.py`. | Python functions in `tools.py` | Move each tool into a Lambda; agent lists tools from the Gateway |
| R4 | A **Gateway request interceptor** (Lambda) applies a per-caller rate limit stored in **DynamoDB** with TTL, plus guardrail checks on tool traffic, with an **SQS dead-letter queue**. | Same pattern, and it also enforces the hackathon's Bedrock limit across users. | Rate limiter inside the app process only | Add interceptor Lambda, RateLimitCounters table, DLQ |
| R5 | **Bedrock Guardrails** screen user input (prompt attacks, denied topics) and agent output (PII, policy) before it reaches the user. | Guardrail with a prompt-attack filter, denied non-procurement topics, PII masking and contextual grounding of the explanation. | Not used (the app escapes output and checks values in Python) | Create guardrail in CDK; apply to input and output |
| R6 | **AgentCore Memory** keeps session and chat history (the blueprint uses a 30-day event expiry). | Stores the clarification turns of one purchase request, for example "how many?" and "by when?". | Streamlit session state | Add Memory resource; agent reads and writes session events |
| R7 | **AgentCore Identity** handles agent and tool authentication; secrets are never in code. | The agent gets an OAuth token (Cognito client credentials) to call the Gateway. | Not needed (no Gateway yet) | Add credential provider |
| R8 | **Observability**: AgentCore Observability exports OpenTelemetry traces, metrics and token usage to **CloudWatch**. | Traces for every request and tool call; approval-service audit events in CloudWatch Logs. | `audit.jsonl` file; no traces | Turn on AgentCore Observability; log the approval service to CloudWatch |
| R9 | **Configuration in SSM Parameter Store, secrets in Secrets Manager**, both encrypted with **KMS**. The agent role can read only those. | Model ID, table names, guardrail ID and buyer details in SSM; Cognito client secret in Secrets Manager. | Environment variables | Move config to SSM and Secrets Manager |
| R10 | **Least-privilege IAM**: each component has its own role, scoped to named resources (the agent role lists the specific memory, KB, guardrail and keys). | One role each for Runtime, Gateway, interceptor, tool Lambdas, approval Lambda and PO Lambda. | n/a (local) | Define roles in CDK |
| R11 | **Evaluation** runs test queries from `groundtruth.json` with expected tool usage, then scores answers with an LLM judge (faithfulness, correctness, helpfulness). | `groundtruth.json` of purchase requests with expected tools and the expected winning supplier. | 213 offline pytest tests; no LLM-judged evaluation | Add evaluation set; run with AgentCore Evaluations |
| R12 | **Infrastructure as code**, deployed from the repo; **clean-up** documented (destroy, then empty buckets and ECR). | All resources in one CDK app; `cdk destroy` plus a clean-up checklist. | No IaC | Write the CDK app |
| R13 | Optional **Knowledge Base** (Bedrock KB over S3 documents) for retrieval. | Phase 2 only: procurement policy documents (approval limits, preferred suppliers). | Not used | None for the hackathon |

## 3. Where this design deliberately differs from the blueprint

| Blueprint choice | This design | Reason |
|---|---|---|
| Terraform | **AWS CDK (Python)** | The hackathon brief says "Infrastructure in CDK, pushed to git". |
| LangGraph agent framework | Keep the existing plain Python tool loop | It already works and is covered by tests. A framework change adds risk without a requirement behind it. |
| LiteLLM multi-provider LLM gateway | **Bedrock Converse API directly**, rate limited in the agent and in the Gateway interceptor | One model provider only. The gateway is a separate deployment with an API key (a secret) and its own cost. |
| Langfuse tracing (third party) | **AgentCore Observability + CloudWatch** | No third-party services or extra secrets under the hackathon rules. |
| Custom offline evaluation scripts | **AgentCore Evaluations** (generally available since March 2026), with `groundtruth.json` kept in the repo | Uses the same test-set idea with a managed service. |
| Tavily web search, Zendesk tickets | Not used | No third-party data or keys allowed. Quotes come from synthetic data. |
| Interceptor-only tool control | **AgentCore Policy** (Cedar, default deny, generally available since March 2026) on the Gateway, plus the interceptor | The agent may call only the two read-only tools. This is enforced outside the agent's code. |
| Customer-service agent can create tickets | **The agent has no write tools at all.** Approval and PO issuing are a separate API reached only from the app with an approver JWT. | Requirement BR-7.1: no purchase without explicit human approval. |

## 4. Components and interfaces

### 4.1 Agent on AgentCore Runtime
- **Entrypoint:** `POST /invocations` with a body of `{"action": "extract" | "recommend", "session_id": "...", "text" | "request": ...}`.
- **Authorization:** Runtime JWT authorizer, Cognito user pool, app client allow-list.
- **Behaviour:** same as today's `ProcurementAgent`. The confirmed product, quantity and date always override what the model passes to tools.
- **Outbound calls:** Bedrock Converse (Nova Lite, model ID from SSM), Bedrock Guardrails, AgentCore Memory and Gateway (MCP).

### 4.2 Gateway tools (Lambda targets, read-only)

| Tool | Input | Output | Data |
|---|---|---|---|
| `get_supplier_quotes` | `product`, `quantity` | quotes, excluded rows, available products | reads `SupplierQuotes` |
| `compare_quotes` | `required_date`, `price_weight`, `delivery_weight`, plus the quotes from the same session | ranking, recommended supplier, `winner_vs_runner_up`, warnings | none |

In this design the quotes stored by the first tool are passed to the second by session ID. The model can't change prices between the two calls, which keeps today's rule.

### 4.3 Approval and PO service (no agent access)

| Endpoint | Caller | Rules (from `approval.py`) |
|---|---|---|
| `POST /cases` | requester JWT | needs a recommendation with at least one supplier |
| `GET /cases?mine=true` / `GET /cases?status=PENDING_APPROVAL` | requester / approver | requesters see only their own cases |
| `POST /cases/{id}/decision` | approver JWT | approver group, no self-approval, quote not expired, one decision per case, comment for rejection or override |
| `GET /cases/{id}/po` | either role on the case | returns a presigned S3 URL for the PDF |

Cases and the audit log move from SQLite and `audit.jsonl` to DynamoDB. A conditional write on `status = PENDING_APPROVAL` keeps "one decision per case" safe across Lambda instances. PO numbers come from an atomic DynamoDB counter, so a number is never reused.

## 5. Security summary
- **Agent permissions:** the agent role can't reach the approval API, the Cases table or the PO bucket. Policy allows only the two tool names; any other tool call is denied by default.
- **Authentication:** every entry point validates a Cognito JWT. Group membership is checked in code, not trusted from the request body.
- **Encryption:** data is encrypted with KMS. S3 blocks public access, and POs are downloaded through short-lived presigned URLs.
- **Guardrails:** they screen user text and model output. The UI also keeps HTML escaping of all model and supplier text.
- **Secrets:** no secrets in code or git. The Cognito client secret is in Secrets Manager.
- **Credentials:** the demo password `1234` must not be carried into Cognito. Cognito enforces its own password policy.

## 6. Cost notes (for the cost-optimization category)
- **Pay per use:** Runtime, Gateway, Lambda, DynamoDB on-demand and Bedrock are billed per use, so there's no idle compute for the demo.
- **No LLM gateway:** skipping the LiteLLM gateway and Langfuse avoids two always-on deployments.
- **No Knowledge Base yet:** it's left out of the hackathon scope because its OpenSearch Serverless vector store bills for capacity even when idle.
- **Small model:** Nova Lite, `maxTokens` 1024, 4 model calls per request.
- **Clean-up:** `cdk destroy` after the event, because event accounts close.

## 7. Implementation plan (for approval)

Estimates assume one developer who knows CDK. Not all of it fits in the four-hour build window. The phase 1 items are the ones the judging criteria reward most.

| Phase | Task | Estimate | Blueprint rules |
|---|---|---|---|
| 1 | CDK app skeleton: KMS, SSM parameters, Cognito user pool with groups, DynamoDB tables seeded with synthetic quotes, S3 PO bucket | 60 min | R2, R9, R10, R12 |
| 1 | Bedrock Guardrail and its use in the agent (input and output) | 30 min | R5 |
| 1 | Agent container on AgentCore Runtime with JWT authorizer; Streamlit calls it | 60 min | R1, R2 |
| 1 | Approval and PO service: API Gateway, 2 Lambdas, DynamoDB conditional writes, S3 PDFs | 75 min | BR-7 |
| 2 | Gateway with 2 Lambda tools, Policy (default deny), interceptor with rate limit and DLQ, Identity credential provider | 90 min | R3, R4, R7 |
| 2 | AgentCore Memory and Observability, CloudWatch dashboard | 45 min | R6, R8 |
| 2 | `groundtruth.json` and AgentCore Evaluations run | 45 min | R11 |
| 3 | Knowledge Base for policy documents (optional) | 60 min | R13 |

Every phase keeps the existing pytest suite green and adds tests for the new boundaries. Examples: a requester token is refused by the decision endpoint, and a Policy-denied tool name is refused by the Gateway.

## 8. Open questions
1. **Scope:** should implementation start, and which phases fit the time left before demos?
2. **Deployment:** may we deploy to the event account now? It creates billable resources (small at demo volume) and requires `cdk bootstrap` in us-east-1.
3. **Streamlit hosting:** keep it local, like the blueprint, or host it on ECS Fargate behind an ALB for the demo?
4. **Region availability:** AgentCore Policy and Evaluations must be confirmed in us-east-1 in the event account before phase 2 starts.
