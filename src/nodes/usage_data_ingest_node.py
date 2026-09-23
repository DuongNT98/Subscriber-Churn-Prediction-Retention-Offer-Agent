"""AgentCore Platform v1.0 - TEL-C2-016 UsageDataIngestNode (outer pre_process slot).

Validates the incoming subscriber signal payload and enforces the 通信の秘密
(電気通信事業法) hard boundary: only allowlisted aggregate signals
(usage_volume_gb, call_frequency, plan_change_events) are accepted;
individual-communication-level fields (browsing_url, dns_query, ...) are
hard-rejected here, before any downstream node ever sees them. This is the
single most important boundary check in this template.
"""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import to_json
from src.services.service import validate_and_filter_signals


# FunctionNode resolves to Any (SDK ships no py.typed marker - see
# pyproject.toml [[tool.mypy.overrides]]); this is a real base class at
# runtime, just unverifiable by mypy until the SDK ships type stubs.
class UsageDataIngestNode(FunctionNode):  # type: ignore[misc]
    """Ingest + validate BSS/OSS aggregate signals; reject 通信の秘密-forbidden fields."""

    # S-1: outer boundary node - matches agent.yaml required_trust_level.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        user_input = state.get("user_input", "")
        if not user_input or not user_input.strip():
            emit_trace_event("usage_signal_rejected", {"reason": "user_input is empty or missing"}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["UsageDataIngestNode: user_input is empty or missing"],
            }

        try:
            payload = json.loads(user_input)
        except (TypeError, ValueError):
            emit_trace_event("usage_signal_rejected", {"reason": "payload is not valid JSON"}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["UsageDataIngestNode: payload is not valid JSON"],
            }

        signals, error = validate_and_filter_signals(payload)
        if error:
            emit_trace_event("usage_signal_rejected", {"reason": error}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"UsageDataIngestNode: {error}"],
            }
        assert signals is not None  # guaranteed by validate_and_filter_signals's own contract

        emit_trace_event(
            "usage_signals_ingested",
            {"correlation_id": state.get("correlation_id"), "signal_keys": sorted(signals.keys())},
            state,
        )

        return {
            "validated_signals": to_json(signals),
            "status": AgentStatus.SUCCESS.value,
        }
