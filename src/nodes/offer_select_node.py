"""AgentCore Platform v1.0 - TEL-C2-016 OfferSelectNode (inner node, LLM-assisted).

Selects a retention offer strictly from config/retention_offers.yaml (S-5) -
the offer itself is never LLM-generated, only its copy text is. Only
high-risk subscribers receive an offer (returns None otherwise, which the
inner graph's routing treats as a valid terminal outcome).
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import to_json
from src.services.llm_provider import resolve_llm
from src.services.service import load_offer_matrix, select_offer


# FunctionNode resolves to Any (SDK ships no py.typed marker - see
# pyproject.toml [[tool.mypy.overrides]]); this is a real base class at
# runtime, just unverifiable by mypy until the SDK ships type stubs.
class OfferSelectNode(FunctionNode):  # type: ignore[misc]
    """Select an offer from the pre-approved matrix for high-risk subscribers."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(self, llm: Any = None) -> None:
        # Test-double seam only - production wiring (register_nodes()) never
        # passes one; resolve_llm() builds a fresh client per invocation from
        # the caller's own bound secrets instead (see src/services/llm_provider.py).
        self._llm = llm

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        risk_tier = state.get("risk_tier")
        if not risk_tier:
            emit_trace_event("offer_select_rejected", {"reason": "risk_tier missing"}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["OfferSelectNode: risk_tier missing - upstream not trusted blindly"],
            }

        matrix = load_offer_matrix()
        offer = select_offer(risk_tier, matrix, llm=resolve_llm(self._llm, state))

        emit_trace_event(
            "offer_selected",
            {"correlation_id": state.get("correlation_id"), "offer_id": offer.get("offer_id") if offer else None},
            state,
        )

        return {
            "selected_offer": to_json(offer),
            "status": AgentStatus.SUCCESS.value,
        }
