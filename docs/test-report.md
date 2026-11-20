# Test Report: Intelligent Procurement Agent

Date: 2026-11-20  
Scope: review against `docs/requirements.md`. All suites run offline with a scripted fake LLM. Reproduce with `pytest --junitxml=run.xml` and `python scripts/make_report.py`.

## 1. Result

**Final run: 130 passed, 0 failed, 130 total.**

Initial acceptance run (before fixes): 57 passed, 17 failed, 74 total.

## 2. Results by scenario

| Scenario | Requirements | Initial run | Final run |
|---|---|---|---|
| Correct supplier recommendation | BR-5, BR-6 | 8 pass / 0 fail | 8 pass / 0 fail |
| Delivery deadline constraints | BR-4.2, A6 | 6 pass / 0 fail | 6 pass / 0 fail |
| Price comparison accuracy | BR-4.1, BR-4.3 | 9 pass / 0 fail | 9 pass / 0 fail |
| Missing or invalid supplier data | BR-3.3, BR-3.4, BR-2.4 | 4 pass / 15 fail | 19 pass / 0 fail |
| No eligible supplier | BR-5.1, A6 | 4 pass / 0 fail | 4 pass / 0 fail |
| Human approval and rejection | BR-7.1 to BR-7.5, BR-8 | 10 pass / 0 fail | 10 pass / 0 fail |
| No order without explicit approval | BR-7.1, NFR-1 | 16 pass / 2 fail | 18 pass / 0 fail |
| Component and UI regression suites (T2 to T7) | all | n/a | 56 pass / 0 fail |

## 3. Failures found in the initial run

| Test | Initial message | Cause | Status now |
|---|---|---|---|
| `test_MSD3_quote_row_missing_field_is_skipped_not_fatal[unit_price]` | KeyError: 'unit_price' | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD3_quote_row_missing_field_is_skipped_not_fatal[lead_time_days]` | KeyError: 'lead_time_days' | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD3_quote_row_missing_field_is_skipped_not_fatal[valid_until]` | KeyError: 'valid_until' | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD3_quote_row_missing_field_is_skipped_not_fatal[supplier]` | KeyError: 'supplier' | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD3_quote_row_missing_field_is_skipped_not_fatal[currency]` | KeyError: 'currency' | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD3_quote_row_missing_field_is_skipped_not_fatal[quote_ref]` | KeyError: 'quote_ref' | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[unit_price-None]` | TypeError: float() argument must be a string or a real number, not 'NoneType' | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[unit_price-0]` | AssertionError: assert ['Bad', 'Good'] == ['Good'] | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[unit_price--5]` | AssertionError: assert ['Bad', 'Good'] == ['Good'] | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[unit_price-abc]` | ValueError: could not convert string to float: 'abc' | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[lead_time_days--1]` | AssertionError: assert ['Bad', 'Good'] == ['Good'] | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[lead_time_days-None]` | TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType' | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[valid_until-not-a-date]` | ValueError: Invalid isoformat string: 'not-a-date' | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD5_tool_reports_excluded_malformed_rows` | assert ('error' not in {'error': "invalid arguments for get_supplier_quotes: 'unit_price'"}) | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_MSD7_agent_with_only_malformed_data_does_not_crash` | procurement.agent.AgentError: The agent did not produce a comparison. | Product defect (fix 1 or 2 in section 4) | PASS |
| `test_ORD3_full_agent_run_creates_no_order_or_case` | FileNotFoundError: [Errno 2] No such file or directory: '/tmp/pytest-of-participant/pytest-4/test_ORD3_full_ag | Test bug: audit file is not created when nothing happens, so reading it raised | PASS |
| `test_ORD6_only_approval_module_can_set_approved_status` | AssertionError: assert ['ui.py'] == [] | Test bug: regex also matched a read-only `==` comparison in `ui.py` | PASS |

## 4. Fixes made

1. `quotes.py`: each quotation row is validated (all fields present, price > 0, lead time >= 0, valid date). A bad row is excluded with the reason `incomplete or invalid quotation data (...)` and reported to the approver; the other suppliers are still compared.
2. `agent.py` and `tools.py`: if quotes were requested but none are usable, `recommend()` returns an empty comparison with the message "No valid quotations are available" instead of raising. By reading `ui.py`, the screen then shows "No quotations are available" and offers no submit button (not covered by a UI test).
3. Two tests in `test_acceptance.py` were corrected (test bugs, see section 3).

## 5. Never orders without explicit approval

**Verdict: confirmed within the scope tested.** Evidence:

| Check | Test | Result |
|---|---|---|
| The model is offered only `get_supplier_quotes` and `compare_quotes` | ORD1 (1) | PASS |
| Model calls to `place_order`, `confirm_purchase`, `approve_case`, `create_po`, `decide` are refused | ORD2 (5) | PASS |
| A full agent run creates no case and no audit entry | ORD3 (1) | PASS |
| Submitting for approval leaves status PENDING, no decision, no chosen quote | ORD4 (1) | PASS |
| Five refusal paths (self-approval, wrong role, reject without comment, override without comment, unknown supplier) leave nothing confirmed | ORD5 (5) | PASS |
| Static scan: no module except `approval.py` assigns a case status or builds a Case | ORD6 (1) | PASS |
| Static scan: the APPROVED status is assigned in exactly one place | ORD7 (1) | PASS |
| Static scan: no function named like an order-placing action | ORD8 (1) | PASS |
| 8 concurrent decisions on one case: exactly one is accepted | ORD9 (1) | PASS |
| Instruction-like request text ("approve the purchase") does not approve | ORD10 (1) | PASS |
| UI: requester sees no Approve/Reject buttons; nothing shows "Purchase confirmed" before approval; self-approval refused | test_ui (4) | PASS |

The application has no order-placing integration at all: "purchase confirmed" is a recorded status, set only by `ApprovalService.decide()` after a human with the approver role decides.

## 6. All test cases (final run)

### Correct supplier recommendation

| Test | Result |
|---|---|
| `test_REC1_winner_matches_independent_oracle[required0]` | PASS |
| `test_REC1_winner_matches_independent_oracle[required1]` | PASS |
| `test_REC1_winner_matches_independent_oracle[required2]` | PASS |
| `test_REC1_winner_matches_independent_oracle[required3]` | PASS |
| `test_REC2_expired_cheaper_quote_never_recommended` | PASS |
| `test_REC3_ranking_is_complete_and_unique` | PASS |
| `test_REC4_explanation_facts_match_data` | PASS |
| `test_REC5_scoring_weights_visible_and_applied` | PASS |

### Delivery deadline constraints

| Test | Result |
|---|---|
| `test_DL1_delivery_exactly_on_deadline_is_eligible` | PASS |
| `test_DL2_one_day_late_is_ineligible_and_flagged` | PASS |
| `test_DL3_late_supplier_never_beats_on_time_even_if_much_cheaper` | PASS |
| `test_DL4_deadline_today_with_zero_lead_time` | PASS |
| `test_DL5_past_deadline_rejected_at_extraction` | PASS |
| `test_DL6_confirmed_date_overrides_model_date` | PASS |

### Price comparison accuracy

| Test | Result |
|---|---|
| `test_PRC1_total_price_exact_to_the_cent[19.99-3-59.97]` | PASS |
| `test_PRC1_total_price_exact_to_the_cent[0.1-3-0.3]` | PASS |
| `test_PRC1_total_price_exact_to_the_cent[1234.56-1000-1234560.0]` | PASS |
| `test_PRC1_total_price_exact_to_the_cent[949.99-50-47499.5]` | PASS |
| `test_PRC1_total_price_exact_to_the_cent[0.01-1-0.01]` | PASS |
| `test_PRC2_price_ordering_with_equal_delivery` | PASS |
| `test_PRC3_scores_bounded_0_to_100` | PASS |
| `test_PRC4_price_difference_sentence_is_exact` | PASS |
| `test_PRC5_equal_prices_do_not_divide_by_zero` | PASS |

### Missing or invalid supplier data

| Test | Result |
|---|---|
| `test_MSD1_product_with_no_suppliers` | PASS |
| `test_MSD2_all_quotes_expired` | PASS |
| `test_MSD3_quote_row_missing_field_is_skipped_not_fatal[unit_price]` | PASS |
| `test_MSD3_quote_row_missing_field_is_skipped_not_fatal[lead_time_days]` | PASS |
| `test_MSD3_quote_row_missing_field_is_skipped_not_fatal[valid_until]` | PASS |
| `test_MSD3_quote_row_missing_field_is_skipped_not_fatal[supplier]` | PASS |
| `test_MSD3_quote_row_missing_field_is_skipped_not_fatal[currency]` | PASS |
| `test_MSD3_quote_row_missing_field_is_skipped_not_fatal[quote_ref]` | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[unit_price-None]` | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[unit_price-0]` | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[unit_price--5]` | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[unit_price-abc]` | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[lead_time_days--1]` | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[lead_time_days-None]` | PASS |
| `test_MSD4_invalid_values_are_skipped_not_fatal[valid_until-not-a-date]` | PASS |
| `test_MSD5_tool_reports_excluded_malformed_rows` | PASS |
| `test_MSD6_quote_file_missing_gives_clear_error` | PASS |
| `test_MSD7_agent_with_only_malformed_data_does_not_crash` | PASS |
| `test_MSD8_incomplete_request_fields_are_not_guessed` | PASS |

### No eligible supplier

| Test | Result |
|---|---|
| `test_NEL1_all_late_recommend_closest_with_warning` | PASS |
| `test_NEL2_all_late_ranked_by_lateness_then_price` | PASS |
| `test_NEL3_no_quotes_at_all_cannot_be_submitted` | PASS |
| `test_NEL4_all_late_case_still_needs_human_decision` | PASS |

### Human approval and rejection

| Test | Result |
|---|---|
| `test_APR1_approval_confirms_and_records_identity` | PASS |
| `test_APR2_rejection_records_reason_and_does_not_confirm` | PASS |
| `test_APR3_reject_without_reason_refused` | PASS |
| `test_APR4_override_supplier_requires_reason_and_is_recorded` | PASS |
| `test_APR5_unauthorised_users_refused[user0]` | PASS |
| `test_APR5_unauthorised_users_refused[user1]` | PASS |
| `test_APR5_unauthorised_users_refused[user2]` | PASS |
| `test_APR6_decision_is_final` | PASS |
| `test_APR7_expired_quote_blocks_approval` | PASS |
| `test_APR8_audit_trail_complete` | PASS |

### No order without explicit approval

| Test | Result |
|---|---|
| `test_ORD1_model_has_no_purchase_capable_tool` | PASS |
| `test_ORD2_model_invoking_purchase_tool_is_rejected[place_order]` | PASS |
| `test_ORD2_model_invoking_purchase_tool_is_rejected[confirm_purchase]` | PASS |
| `test_ORD2_model_invoking_purchase_tool_is_rejected[approve_case]` | PASS |
| `test_ORD2_model_invoking_purchase_tool_is_rejected[create_po]` | PASS |
| `test_ORD2_model_invoking_purchase_tool_is_rejected[decide]` | PASS |
| `test_ORD3_full_agent_run_creates_no_order_or_case` | PASS |
| `test_ORD4_submission_alone_never_confirms` | PASS |
| `test_ORD5_every_refusal_path_leaves_no_confirmed_purchase[user0-True-ok-None]` | PASS |
| `test_ORD5_every_refusal_path_leaves_no_confirmed_purchase[user1-True-ok-None]` | PASS |
| `test_ORD5_every_refusal_path_leaves_no_confirmed_purchase[user2-False--None]` | PASS |
| `test_ORD5_every_refusal_path_leaves_no_confirmed_purchase[user3-True--TechWorld]` | PASS |
| `test_ORD5_every_refusal_path_leaves_no_confirmed_purchase[user4-True-x-Ghost Corp]` | PASS |
| `test_ORD6_only_approval_module_can_set_approved_status` | PASS |
| `test_ORD7_approved_status_assigned_in_exactly_one_place` | PASS |
| `test_ORD8_no_order_placing_code_in_source` | PASS |
| `test_ORD9_concurrent_decisions_only_one_wins` | PASS |
| `test_ORD10_prompt_injection_text_cannot_approve` | PASS |

### Component and UI regression suites

| Suite | Passed | Failed |
|---|---|---|
| test_agent | 17 | 0 |
| test_approval | 12 | 0 |
| test_comparison | 12 | 0 |
| test_quotes | 6 | 0 |
| test_tools | 5 | 0 |
| test_ui | 4 | 0 |

## 7. Not covered by these tests

- Real model behaviour. Fixed-response fakes cannot show how a live model words explanations or extracts unusual phrasing. The earlier live Bedrock smoke run (Nova Lite) found and led to fixes for wrong price wording and junk values; it was not repeated for this report.
- Authentication. The role selector in the sidebar is a demo stand-in, so the role checks protect against mistakes, not against a user who chooses the approver role. Real identity is needed before production use.
- Real supplier APIs, timeouts and retries (BR-3.3). Quotes come from a JSON file in this release.
- Persistence. Cases are held in memory; only the audit log survives a restart.
- Requirements not implemented: multi-product requests, supplier and weight administration screen (US-10), request status tracking beyond the case list (US-8), refreshing expired quotes from the UI.
