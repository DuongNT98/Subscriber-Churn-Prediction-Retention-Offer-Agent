# Test Specification — TEL-C2-016

## Test Strategy
- Coverage target: every node ≥1 success + ≥1 error/edge unit test; ≥1 full-graph integration compile+invoke
- Test types: Unit (`tests/unit/`) / Integration (`tests/integration/`) / Proof-of-Boundary (`tests/proof_of_boundary/`)

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | Type check pass, no Pydantic/dataclass | PASS |
| TC-02 | Fail-closed validation on invalid/empty/通信の秘密-forbidden input | ERROR dict, no raise | PASS |
| TC-03 | No JWT/Credential in State or source | 0 credential literals, no `os.environ` secret reads | PASS |
| TC-04 | InvocationContext via configurable only | Never appears in post-invoke state | PASS |
| TC-05 | S-4: domain event per node, no duplicate backbone events in `execute()` | `usage_signals_ingested` etc. present; no `node_start/complete/error` in `execute()` | PASS |
| TC-06 | S-2: `_security_gate_input()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden | PASS |
| TC-07 | S-3: `_security_gate_output()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden | PASS |
| TC-08 | `required_trust_level` declared valid + enforced | Insufficient trust → ERROR, no raise | PASS |
| TC-09 | S-2: `_extra_security_gate_input()` | N/A — default framework PII scan is sufficient; domain check (通信の秘密) is business validation in `execute()`, not a gate hook | N/A |
| TC-10 | S-3: `_extra_security_gate_output()` non-trivial | `ChannelDispatchNode`/`CampaignReportNode` hooks block PII-shaped output | PASS |
| TC-11 | S-4: ≥1 domain `emit_trace_event()` per `execute()` | Present on all 7 nodes | PASS |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | No silent failures | PASS |
| PB-2 | State serialization | Post-invoke State is primitives only | No Pydantic/dataclass | PASS |
| PB-4 | Import isolation | No Level 0 imports | AST scan: 0 violations | PASS |
| PB-5 | Checkpoint safety | No JWT/Pydantic in checkpoint | Inspection pass | PASS |
| PB-6 | Invoke execution order | S-1 → node_start → S-2 → execute() → S-3 → node_complete | Order verified for every `src/nodes/` class | PASS |
| PB-7 | HITL interrupt propagation | `hitl.enabled` is false — auto-skip stub | Skipped (N/A) | SKIP |

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01 | 通信の秘密 boundary rejects `browsing_url` | payload with `browsing_url` key | ERROR, "通信の秘密" in error_log | PASS |
| BL-02 | 通信の秘密 boundary rejects `dns_query` | payload with `dns_query` key | ERROR | PASS |
| BL-03 | High-risk subscriber gets an offer + dispatch with opt-out | high churn signals | `risk_tier=="high"`, offer selected, `opt_out_included=True` | PASS |
| BL-04 | Low-risk subscriber gets no offer | low churn signals | `risk_tier=="low"`, `selected_offer` is null, dispatch skipped | PASS |
| BL-05 | Campaign report never leaks subscriber-level fields | any risk tier | `campaign_report` has no `subscriber_id`/`usage_volume_gb` | PASS |
| BL-06 | LLM (test double) renders offer copy / campaign narrative | well-formed `{"content": str}` response | Rendered text used verbatim; offer_id / risk_tier fields unaffected | PASS |
| BL-07 | Malformed/empty LLM response falls back to deterministic text | `{"content": ""}` / `{}` | Original `copy_template` / summary text used, no error | PASS |
| BL-08 | LLM raising an exception falls back to deterministic text | `complete()` raises `RuntimeError` | Original `copy_template` / summary text used, `status=success` | PASS |
| BL-09 | No LLM injected + no bound secrets falls back to deterministic text | production shape, no `bound_secrets()` scope | `resolve_llm()` returns `None`; original text used | PASS |
| BL-10 | `resolve_llm()` degrades on malformed endpoint / missing secret / bare PB-6 state | see `tests/unit/test_llm_provider.py` | Returns `None` in every case, never raises | PASS |

## Test Execution Summary
- Execution date: 2026-07-12 (local verify before push)
- Total tests: unit (test_nodes.py + test_framework_compliance.py) + integration (test_graph.py) + PB-2/4/6/7
- Pass / Fail / Skip: see CI pipeline for the authoritative run (local wheel-rc1 artifacts may differ per
  `_shared-rules/coe-standards/test-artifacts.md` "Xử fail local" section)
- Coverage: every node has ≥1 success + ≥1 error/edge unit test; full graph has ≥4 integration scenarios
