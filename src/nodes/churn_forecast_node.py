"""AgentCore Platform v1.0 - TEL-C2-016 ChurnForecastNode (inner node).

Forecasts churn probability over 30/60/90-day horizons from the validated
aggregate signals. Deterministic - no LLM.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.service import forecast_churn, validate_and_filter_signals


# FunctionNode resolves to Any (SDK ships no py.typed marker - see
# pyproject.toml [[tool.mypy.overrides]]); this is a real base class at
# runtime, just unverifiable by mypy until the SDK ships type stubs.
class ChurnForecastNode(FunctionNode):  # type: ignore[misc]
    """Forecast churn probability from aggregate subscriber signals."""

    # S-1: inner subgraph node - trust authenticated at outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        signals = from_json(state.get("validated_signals"), None)
        if not signals:
            envelope = from_json(state.get("user_input"), None)
            if isinstance(envelope, dict) and "validated_signals" in envelope:
                candidate = envelope.get("validated_signals")
                signals = from_json(candidate, None) if isinstance(candidate, str) else candidate
            else:
                signals = envelope

        if not signals:
            emit_trace_event("churn_forecast_rejected", {"reason": "validated_signals missing"}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ChurnForecastNode: validated_signals missing - upstream not trusted blindly"],
            }

        # Defense-in-depth: the outer pre_process -> main edge is unconditional
        # (framework backbone), so a pre_process ERROR does not by itself stop
        # this inner subgraph from running on a raw-fallback payload. Re-run
        # the 通信の秘密 boundary check here too - never trust that the outer
        # validation alone stopped an invalid/forbidden payload from reaching
        # this node ([[cat2-pre-process-error-still-dispatches-main]]).
        _, error = validate_and_filter_signals(signals)
        if error:
            emit_trace_event("churn_forecast_rejected", {"reason": error}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"ChurnForecastNode: {error}"],
            }

        forecast = forecast_churn(signals)

        emit_trace_event(
            "churn_forecasted",
            {"correlation_id": state.get("correlation_id"), "p90": forecast.get("90d")},
            state,
        )

        return {
            "churn_forecast": to_json(forecast),
            "status": AgentStatus.SUCCESS.value,
        }
