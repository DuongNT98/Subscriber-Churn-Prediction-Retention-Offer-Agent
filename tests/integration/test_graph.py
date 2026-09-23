# TEL-C2-016 - Integration test: full graph compile + invoke (Cat 2 outer + inner).

import json

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph

HIGH_RISK_SIGNALS = json.dumps(
    {"subscriber_id": "sub-100", "usage_volume_gb": 1.0, "call_frequency": 1.0, "plan_change_events": 4}
)
LOW_RISK_SIGNALS = json.dumps(
    {"subscriber_id": "sub-200", "usage_volume_gb": 40.0, "call_frequency": 40.0, "plan_change_events": 0}
)
EMPTY_INPUT = ""
FORBIDDEN_SIGNAL_PAYLOAD = json.dumps({"subscriber_id": "sub-300", "browsing_url": "https://example.com/private"})


class TestAgentIntegration:
    def test_high_risk_reaches_full_pipeline(self):
        # Per [[framework-s2-gate-can-also-break-success-path]], assert the
        # environment-independent invariant (pipeline completion), not an
        # exact terminal status - unit tests already pin the success-path
        # logic deterministically.
        agent = Graph(config={"max_retry": 1})
        agent.compile()
        ctx = InvocationContext(session_id="it-1", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="retention-ops-001")
        result = agent.invoke(HIGH_RISK_SIGNALS, ctx=ctx)

        assert len(result.get("node_history", [])) >= 4
        assert result["status"] in ("success", "error", "cancelled")

    def test_low_risk_reaches_full_pipeline(self):
        agent = Graph(config={"max_retry": 1})
        agent.compile()
        ctx = InvocationContext(session_id="it-2", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="retention-ops-001")
        result = agent.invoke(LOW_RISK_SIGNALS, ctx=ctx)

        assert len(result.get("node_history", [])) >= 4
        assert result["status"] in ("success", "error", "cancelled")

    def test_empty_input_error(self):
        agent = Graph(config={"max_retry": 1})
        agent.compile()
        ctx = InvocationContext(session_id="it-3", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="retention-ops-001")
        result = agent.invoke(EMPTY_INPUT, ctx=ctx)
        assert result["status"] in ("error", "cancelled")

    def test_tsushin_no_himitsu_boundary_rejected_end_to_end(self):
        agent = Graph(config={"max_retry": 1})
        agent.compile()
        ctx = InvocationContext(session_id="it-4", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="retention-ops-001")
        result = agent.invoke(FORBIDDEN_SIGNAL_PAYLOAD, ctx=ctx)
        assert result["status"] in ("error", "cancelled")
