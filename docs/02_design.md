# Template Design Specification — TEL-C2-016

## Position in AgentCore Architecture

- **Agent Class**: `TELChurnRetentionAgent` (`src/graph/graph.py`)
- **L1 Base**: `AgentBaseGraph` (outer) — Cat 2 composition with `GraphNode` in the `main` slot
  wrapping an inner `BaseGraph` (`ChurnRetentionWorkflowGraph`, `src/graph/domain_workflow_graph.py`)
- **Three-Layer Separation**:
  - State: flat TypedDict composition (`src/schemas/state.py`, `NotRequired`-wrapped fields, no Pydantic)
  - Node: L1 inheritance (`FunctionNode.execute(self, state) -> dict` override only)
  - Graph: composition (outer `register_nodes()` for pre/main/post substitution; inner
    `register_nodes()`/`add_edges()` for the 5-step domain workflow)

## Architecture Overview

### Outer graph (backbone)

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | schema_version, session_id, trust_level | — | — | InitializeNode (default) |
| pre_process | `UsageDataIngestNode` — parse + validate subscriber signals; **hard-reject 通信の秘密-forbidden keys** (browsing_url, dns_query, ...) | `user_input` (JSON) | `validated_signals` | FunctionNode |
| main | `ChurnRetentionGraphNode` — wraps the inner 5-step domain workflow | `validated_signals` | `churn_forecast`, `risk_tier`, `selected_offer`, `dispatch_result`, `acceptance_status` | GraphNode |
| post_process | `CampaignReportNode` — assemble cohort-level ROI report (LLM narrative, S-3 anonymized) | `risk_tier`, `selected_offer`, `acceptance_status` | `campaign_report`, `formatted_output` | FunctionNode |
| finalize | response_metadata, total_time_ms | — | — | FinalizeNode (default) |

### Inner domain workflow (`ChurnRetentionWorkflowGraph`)

| Step | Node | Responsibility | LLM? |
|---|---|---|---|
| 1 | `ChurnForecastNode` | 30/60/90-day churn probability from aggregate signals | ❌ |
| 2 | `RiskSegmentNode` | high/medium/low risk-tier segmentation | ❌ |
| 3 | `OfferSelectNode` | select offer strictly from `config/retention_offers.yaml` (S-5); LLM renders copy only, never chooses the offer | ✅ (copy only) |
| 4 | `ChannelDispatchNode` | dispatch via carrier app/SMS with mandatory opt-out link (特定商取引法) + rate limit; S-3 strips PII | ❌ |
| 5 | `AcceptanceTrackNode` | record initial acceptance-tracking status | ❌ |

**Risk-tier gate**: `route()` in the inner graph sends only `risk_tier == "high"` subscribers to
`offer_select` → `channel_dispatch` → `acceptance_track`; medium/low risk terminates immediately after
`risk_segment` — a normal successful terminal state, not an error.

### Data Flow

```
START → initialize → pre_process(UsageDataIngest) → main(GraphNode)
                                                        │
                                                        ▼ (inner subgraph)
                              churn_forecast → risk_segment → {route}
                                                  high risk │      │ medium/low
                                                             ▼      ▼
                                              offer_select → channel_dispatch → acceptance_track → END
                                                                                                     │
      → post_process(CampaignReport) → finalize → END  ◄──────────────────────────────────────────┘
```

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `validated_signals` | `NotRequired[str]` (JSON) | Allowlisted aggregate signals after 通信の秘密 boundary check | No (set by pre_process) |
| `churn_forecast` | `NotRequired[str]` (JSON) | `{"30d","60d","90d"}` churn probability | No |
| `risk_tier` | `NotRequired[str]` | `"high"\|"medium"\|"low"` | No |
| `selected_offer` | `NotRequired[str]` (JSON or `"null"`) | Offer chosen from matrix, or none | No |
| `dispatch_result` | `NotRequired[str]` (JSON or `"null"`) | Channel + opt-out + rate-limit result | No |
| `acceptance_status` | `NotRequired[str]` | `"accepted"\|"declined"\|"no_response"` | No |
| `campaign_report` | `NotRequired[str]` (JSON) | Cohort-level ROI report (final output) | No |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types); complex payloads are JSON-string-encoded
  (`to_json`/`from_json` helpers in `src/schemas/state.py`)
- No JWT, API keys, credentials in State
- InvocationContext via `config["configurable"]` only (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (session_id, caller_trust_level, caller_id)
- [x] S-4: `emit_trace_event()` — at least one domain event inside every node's `execute()`
      (`usage_signals_ingested`/`usage_signal_rejected`, `churn_forecasted`, `risk_segmented`,
      `offer_selected`, `offer_dispatched`/`channel_dispatch_skipped`, `acceptance_tracked`,
      `campaign_report_generated`; GraphNode wrapper emits via `extract_input`/`merge_output` hooks:
      `churn_retention_workflow_dispatched`/`_completed`)
- [x] S-3: `_extra_security_gate_output()` on `ChannelDispatchNode` (blocks PII in `dispatch_result`)
      and `CampaignReportNode` (blocks subscriber-level data in `campaign_report`) — both re-check
      the node's own output dict, not upstream state fields
- [ ] S-2: `_extra_security_gate_input()` — not needed beyond the default framework PII scan; the
      domain-specific 通信の秘密 boundary check is business validation inside `execute()`
      (fail-closed ERROR return, never a raise), not a security-gate hook

### Composition Pattern

- **Pattern**: GraphNode (subgraph) — `ChurnRetentionGraphNode` wraps `ChurnRetentionWorkflowGraph`
- **Composition target**: `src/graph/domain_workflow_graph.py`
- **Error propagation strategy**: `propagate` (fail fast — inner ERROR surfaces as outer ERROR)

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: `framework/` and `shared/` only (no `agents/base/` required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | `AgentBaseGraph` | `AutonomousBaseGraph` | `AgentBaseGraph` | Fixed multi-step pipeline, not an autonomous reasoning loop — no HITL needed |
| Composition pattern | Flat 3-slot (Cat 1 style) | GraphNode + inner subgraph | GraphNode + inner subgraph | Cat 2 requires the 3-layer composition (`gate-composition`); flat would fail CI |
| Offer selection | LLM chooses offer | Config-matrix-only + LLM copy | Config-matrix-only | S-5: offers must be pre-approved, never LLM-invented |
| Risk-tier gate location | Inside `OfferSelectNode` only | Graph-level `route()` conditional edge | Graph-level `route()` | Explicit, testable topology; matches proposal §4 "only high-risk proceed" |

## LLM Integration (Azure OpenAI, graceful degrade)

`OfferSelectNode` (offer copy) and `CampaignReportNode` (campaign narrative) are the only two
LLM-touching nodes; both already produce a valid deterministic result without the LLM
(`copy_template` from `config/retention_offers.yaml`, and a plain-text cohort summary
respectively) — the LLM only enhances that text, it never decides anything (`generation_mode:
"llm"` in `config/agent.yaml`, flipped from `deterministic` for this reason).

- **Client**: `shared.services.llm.azure_openai_client.AzureOpenAIClient`, resolved by
  `src/services/llm_provider.py::resolve_llm()`.
- **Secrets**: `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_DEPLOYMENT`,
  declared under `config/agent.yaml`'s `requires.secrets` (not `config/config.yaml` — these are
  credentials/endpoints, not tunable runtime parameters).
- **Per-invocation, never cached**: the client is built fresh inside each node's `execute()` from
  the invocation's own bound `SecretProvider` (`ctx.secrets.require(...)` via
  `InvocationContext.from_state(state)`) — never in `__init__`/`register_nodes()`/`server.py` module
  scope. Node instances are constructed once and reused across every caller via the registry's LRU
  cache, so caching a client built from one caller's secrets would leak it to the next caller
  (S-2/S-4 timing rule).
- **Fail-open by design**: any failure — no `bound_secrets()` scope active, a missing secret, a
  malformed `AZURE_OPENAI_ENDPOINT` (must be the bare resource endpoint, no `/openai` path
  segment), an API error, or a malformed/empty response — degrades to the existing deterministic
  text. Neither node ever raises or sets `status=error` because of the LLM path; `resolve_llm()`
  and `select_offer()`/`build_campaign_report()`'s own `except Exception` both fail toward "no
  LLM this invocation", not toward an error state.
- **Error handling boundary**: `resolve_llm()` owns client construction failures (secret/endpoint
  problems); `service.py`'s `select_offer()`/`build_campaign_report()` own the `llm.complete(...)`
  call failure and response-shape validation (non-empty string in `response["content"]`).

## Pattern-dependency fallbacks (per Engineer Review §12)

Four pattern references cited in the proposal are not released templates — this implementation
does not import them. `ChurnForecastNode`/`RiskSegmentNode` implement local, self-contained
deterministic logic in `src/services/service.py` instead of depending on those unreleased
patterns.

## Open item (Stage II, not a code blocker)

The 通信の秘密 signal-methodology legal sign-off (Engineer Review §12 dependency #5) is a
Stage II PM/legal-owned gate. This implementation already enforces the boundary at ingest
(allowlist + hard rejection of `browsing_url`/`dns_query`/`url`/`destination_ip`/`call_content`)
regardless of the legal sign-off status.
