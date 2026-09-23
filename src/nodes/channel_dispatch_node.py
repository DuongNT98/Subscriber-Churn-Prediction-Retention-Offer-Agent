"""AgentCore Platform v1.0 - TEL-C2-016 ChannelDispatchNode (inner node).

Dispatches the selected offer via carrier app / SMS / call brief. Every
dispatched message carries a mandatory opt-out link (特定商取引法) and
respects a per-day rate limit. S-3 strips PII before any dispatch log - the
dispatch result never contains subscriber_id or raw contact info.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.service import dispatch_offer, load_offer_matrix


# FunctionNode resolves to Any (SDK ships no py.typed marker - see
# pyproject.toml [[tool.mypy.overrides]]); this is a real base class at
# runtime, just unverifiable by mypy until the SDK ships type stubs.
class ChannelDispatchNode(FunctionNode):  # type: ignore[misc]
    """Dispatch the selected offer with a mandatory opt-out link + rate limit."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        offer = from_json(state.get("selected_offer"), None)
        if not offer:
            # No offer for this risk tier - not an error, nothing to dispatch.
            emit_trace_event("channel_dispatch_skipped", {"reason": "no_offer"}, state)
            return {
                "dispatch_result": to_json(None),
                "status": AgentStatus.SUCCESS.value,
            }

        matrix = load_offer_matrix()
        result = dispatch_offer(offer, matrix)

        emit_trace_event(
            "offer_dispatched",
            {
                "correlation_id": state.get("correlation_id"),
                "channel": result.get("channel"),
                "opt_out_included": result.get("opt_out_included"),
            },
            state,
        )

        return {
            "dispatch_result": to_json(result),
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """Non-suppressible re-check: dispatch_result must never carry PII."""
        result = from_json(state.get("dispatch_result"), None)
        if result and any(k in result for k in ("subscriber_id", "phone_number", "email")):
            emit_trace_event("channel_dispatch_pii_recheck_blocked", {}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ChannelDispatchNode: S-3 re-check found PII in dispatch_result"],
            }
        return state
