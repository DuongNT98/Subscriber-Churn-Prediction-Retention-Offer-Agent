"""AgentCore Platform v1.0 - TEL-C2-016 CampaignReportNode (outer post_process slot, LLM-assisted).

Assembles the cohort-level campaign ROI report from the inner subgraph's
merged output. S-3: the report is always cohort/aggregate-level - never
per-subscriber PII (no subscriber_id, no raw signal values).
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.llm_provider import resolve_llm
from src.services.service import build_campaign_report


# FunctionNode resolves to Any (SDK ships no py.typed marker - see
# pyproject.toml [[tool.mypy.overrides]]); this is a real base class at
# runtime, just unverifiable by mypy until the SDK ships type stubs.
class CampaignReportNode(FunctionNode):  # type: ignore[misc]
    """Assemble the cohort-level campaign ROI report (S-3 anonymized)."""

    # S-1: outer boundary node - matches agent.yaml required_trust_level.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: Any = None) -> None:
        # Test-double seam only - production wiring (register_nodes()) never
        # passes one; resolve_llm() builds a fresh client per invocation from
        # the caller's own bound secrets instead (see src/services/llm_provider.py).
        self._llm = llm

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        risk_tier = state.get("risk_tier")
        if not risk_tier:
            emit_trace_event("campaign_report_rejected", {"reason": "risk_tier missing"}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["CampaignReportNode: risk_tier missing - upstream not trusted blindly"],
            }

        offer = from_json(state.get("selected_offer"), None)
        acceptance_status = state.get("acceptance_status")

        report = build_campaign_report(risk_tier, offer, acceptance_status, llm=resolve_llm(self._llm, state))

        emit_trace_event(
            "campaign_report_generated",
            {"correlation_id": state.get("correlation_id"), "risk_tier": risk_tier},
            state,
        )

        return {
            "campaign_report": to_json(report),
            "formatted_output": report.get("narrative", ""),
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """Non-suppressible re-check: campaign_report must never carry subscriber-level PII."""
        report = from_json(state.get("campaign_report"), {})
        if any(k in report for k in ("subscriber_id", "phone_number", "email", "usage_volume_gb")):
            emit_trace_event("campaign_report_pii_recheck_blocked", {}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["CampaignReportNode: S-3 re-check found subscriber-level data in campaign_report"],
            }
        return state
