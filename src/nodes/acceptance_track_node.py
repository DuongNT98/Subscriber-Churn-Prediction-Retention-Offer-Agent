"""AgentCore Platform v1.0 - TEL-C2-016 AcceptanceTrackNode (inner node).

Records the acceptance outcome (accepted / declined / no_response) for
analytics. Deterministic - no LLM. The real acceptance signal arrives later
via a downstream channel webhook (not available at agent-invoke time), so
this node records the initial 'no_response' state when an offer was
dispatched, or 'no_response' as a neutral placeholder when none was.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json
from src.services.service import track_acceptance


# FunctionNode resolves to Any (SDK ships no py.typed marker - see
# pyproject.toml [[tool.mypy.overrides]]); this is a real base class at
# runtime, just unverifiable by mypy until the SDK ships type stubs.
class AcceptanceTrackNode(FunctionNode):  # type: ignore[misc]
    """Record the initial acceptance-tracking status for the dispatched offer."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        dispatch_result = from_json(state.get("dispatch_result"), None)
        status = track_acceptance(dispatch_result)

        emit_trace_event(
            "acceptance_tracked",
            {"correlation_id": state.get("correlation_id"), "acceptance_status": status},
            state,
        )

        return {
            "acceptance_status": status,
            "status": AgentStatus.SUCCESS.value,
        }
