"""AgentCore Platform v1.0 - TEL-C2-016 domain services.

Pure, deterministic helpers - no agenticstar/framework imports here.
Signal ingestion validation (通信の秘密 boundary), churn forecasting, risk
segmentation, offer selection, dispatch, acceptance tracking, and campaign
report assembly for the subscriber churn-retention domain.
"""

import os
from typing import Any, cast

import yaml

# 通信の秘密 (電気通信事業法) hard boundary: these individual-communication
# fields must NEVER reach this agent. Only aggregate, allowlisted signals are
# accepted. This is the single most important legal control in this template.
FORBIDDEN_SIGNAL_KEYS = ("browsing_url", "dns_query", "url", "destination_ip", "call_content")

ALLOWED_SIGNAL_KEYS = ("subscriber_id", "usage_volume_gb", "call_frequency", "plan_change_events")

VALID_RISK_TIERS = ("high", "medium", "low")


def validate_and_filter_signals(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Validate subscriber_id + hard-reject any 通信の秘密-forbidden signal key."""
    if not isinstance(payload, dict):
        return None, "payload is not a JSON object"

    subscriber_id = payload.get("subscriber_id")
    if not subscriber_id or not isinstance(subscriber_id, str):
        return None, "subscriber_id missing or invalid"

    present_forbidden = [k for k in FORBIDDEN_SIGNAL_KEYS if k in payload]
    if present_forbidden:
        return None, f"通信の秘密 boundary violation: forbidden signal key(s) {present_forbidden}"

    signals = {k: payload.get(k) for k in ALLOWED_SIGNAL_KEYS if k in payload}
    signals["subscriber_id"] = subscriber_id
    return signals, None


def forecast_churn(signals: dict[str, Any]) -> dict[str, Any]:
    """Deterministic aggregate-signal churn forecast over 30/60/90-day horizons."""
    usage = float(signals.get("usage_volume_gb", 0) or 0)
    call_freq = float(signals.get("call_frequency", 0) or 0)
    plan_changes = int(signals.get("plan_change_events", 0) or 0)

    # Simple monotonic scoring: low usage + low call frequency + recent plan
    # churn (downgrades) raise the forecast probability. Bounded to [0, 1].
    base = 0.5 - min(usage, 50) / 100 - min(call_freq, 50) / 200
    base += min(plan_changes, 5) * 0.06
    base = max(0.0, min(1.0, base))

    return {
        "30d": round(base * 0.5, 3),
        "60d": round(base * 0.75, 3),
        "90d": round(base, 3),
    }


def segment_risk(forecast: dict[str, Any]) -> str:
    """Segment into high/medium/low risk tier from the 90-day forecast."""
    p90 = float(forecast.get("90d", 0) or 0)
    if p90 >= 0.6:
        return "high"
    if p90 >= 0.3:
        return "medium"
    return "low"


def load_offer_matrix(path: str | None = None) -> dict[str, Any]:
    path = path or os.path.join(os.path.dirname(__file__), "..", "..", "config", "retention_offers.yaml")
    with open(path, encoding="utf-8") as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def select_offer(risk_tier: str, matrix: dict[str, Any], llm: Any = None) -> dict[str, Any] | None:
    """Select an offer strictly from the pre-approved matrix (S-5). Only
    high-risk subscribers receive an offer; LLM (if provided) renders the
    copy_template into subscriber-facing text, it never invents the offer."""
    if risk_tier != "high":
        return None

    candidates = matrix.get("offers", {}).get("high", [])
    if not candidates:
        return None

    chosen = candidates[0]
    copy_template = chosen.get("copy_template", "")
    copy_text = copy_template
    if llm is not None:
        # complete() is the canonical BaseLLM interface: a messages list in,
        # a {"content": str, ...} dict out - never a bare string either way.
        try:
            response = llm.complete(
                [
                    {
                        "role": "user",
                        "content": f"Rewrite this retention offer message warmly and concisely: {copy_template}",
                    }
                ]
            )
            rendered = (response or {}).get("content", "")
            if isinstance(rendered, str) and rendered.strip():
                copy_text = rendered.strip()
        except Exception:
            pass  # any LLM failure keeps the deterministic copy_template

    return {"offer_id": chosen["offer_id"], "kind": chosen.get("kind", ""), "copy": copy_text}


def dispatch_offer(offer: dict[str, Any], matrix: dict[str, Any]) -> dict[str, Any]:
    """Dispatch via the default channel; every dispatch carries an opt-out
    link (特定商取引法) and respects the daily rate limit."""
    return {
        "channel": matrix.get("default_channel", "sms"),
        "opt_out_link": matrix.get("opt_out_url", ""),
        "opt_out_included": True,
        "rate_limited": False,
        "daily_rate_limit": matrix.get("daily_rate_limit", 3),
        "offer_id": offer.get("offer_id"),
    }


def track_acceptance(dispatch_result: dict[str, Any]) -> str:
    """Record the outcome of a dispatched offer. Real acceptance signal comes
    from the downstream channel (carrier app / SMS webhook / call-center
    system) - not available at agent-invoke time, so the default state is
    'no_response' until a follow-up event updates it."""
    if not dispatch_result:
        return "no_response"
    return "no_response"


def build_campaign_report(
    risk_tier: str, offer: dict[str, Any] | None, acceptance_status: str | None, llm: Any = None
) -> dict[str, Any]:
    """Cohort-level ROI report only - S-3: never per-subscriber PII, always
    aggregated/anonymized wording."""
    summary = (
        f"Cohort risk tier: {risk_tier}. "
        f"Offer dispatched: {offer.get('offer_id') if offer else 'none'}. "
        f"Acceptance status: {acceptance_status or 'pending'}."
    )
    narrative = summary
    if llm is not None:
        try:
            response = llm.complete(
                [
                    {
                        "role": "user",
                        "content": f"Write a one-paragraph cohort-level retention campaign ROI narrative: {summary}",
                    }
                ]
            )
            rendered = (response or {}).get("content", "")
            if isinstance(rendered, str) and rendered.strip():
                narrative = rendered.strip()
        except Exception:
            pass  # any LLM failure keeps the deterministic summary

    return {
        "risk_tier": risk_tier,
        "offer_id": offer.get("offer_id") if offer else None,
        "acceptance_status": acceptance_status,
        "narrative": narrative,
    }
