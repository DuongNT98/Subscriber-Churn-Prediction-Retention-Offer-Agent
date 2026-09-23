"""AgentCore Platform v1.0 - TEL-C2-016 RiskSegmentNode (inner node).

Segments the forecast into a high/medium/low risk tier. Only high-risk
subscribers proceed to offer selection + dispatch downstream (see
domain_workflow_graph.py routing). Deterministic - no LLM.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json
from src.services.service import segment_risk


# FunctionNode resolves to Any (SDK ships no py.typed marker - see
# pyproject.toml [[tool.mypy.overrides]]); this is a real base class at
# runtime, just unverifiable by mypy until the SDK ships type stubs.
class RiskSegmentNode(FunctionNode):  # type: ignore[misc]
    """Segment subscriber into a high/medium/low churn-risk tier."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        forecast = from_json(state.get("churn_forecast"), None)
        if not forecast:
            emit_trace_event("risk_segment_rejected", {"reason": "churn_forecast missing"}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["RiskSegmentNode: churn_forecast missing - upstream not trusted blindly"],
            }

        tier = segment_risk(forecast)

        emit_trace_event(
            "risk_segmented",
            {"correlation_id": state.get("correlation_id"), "risk_tier": tier},
            state,
        )

        return {
            "risk_tier": tier,
            "status": AgentStatus.SUCCESS.value,
        }
