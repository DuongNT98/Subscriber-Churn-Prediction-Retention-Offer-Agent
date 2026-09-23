"""AgentCore Platform v1.0 - TEL-C2-016 state schema.

Subscriber Churn Prediction & Retention Offer Agent.
Flat TypedDict extension of AgentState (ADR-005). Structured payloads
(dict/list) are JSON-string-encoded before being stored in state fields.
"""

import json
from typing import Any, NotRequired

from framework.schemas.agent_state import AgentState


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def from_json(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


# AgentState resolves to Any (SDK ships no py.typed marker - see pyproject.toml
# [[tool.mypy.overrides]]), so mypy cannot confirm it's a TypedDict here; both
# the subclass line and every NotRequired[] field below are real TypedDict
# usage at runtime, just unverifiable until the SDK ships type stubs.
class State(AgentState):  # type: ignore[misc]
    """Agent state for TEL-C2-016.

    validated_signals: JSON dict {subscriber_id, usage_volume, call_frequency,
        plan_change_events} - allowlisted aggregate signals only (通信の秘密
        boundary already enforced before this is set).
    churn_forecast: JSON dict {"30d": float, "60d": float, "90d": float}.
    risk_tier: "high" | "medium" | "low".
    selected_offer: JSON dict {offer_id, kind, copy} or null when no offer applies.
    dispatch_result: JSON dict {channel, opt_out_included, rate_limited}.
    acceptance_status: "accepted" | "declined" | "no_response" | null.
    campaign_report: JSON dict - cohort-level ROI report (final output).
    """

    validated_signals: NotRequired[str]  # type: ignore[valid-type]
    churn_forecast: NotRequired[str]  # type: ignore[valid-type]
    risk_tier: NotRequired[str]  # type: ignore[valid-type]
    selected_offer: NotRequired[str]  # type: ignore[valid-type]
    dispatch_result: NotRequired[str]  # type: ignore[valid-type]
    acceptance_status: NotRequired[str]  # type: ignore[valid-type]
    campaign_report: NotRequired[str]  # type: ignore[valid-type]
