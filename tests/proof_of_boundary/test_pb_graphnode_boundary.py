# PB-6-bis: GraphNode boundary verification (Cat 2 outer `main` slot).
#
# PB-6 (test_pb_invoke_order.py) only discovers concrete BaseNode subclasses under
# src/nodes/. ChurnRetentionGraphNode lives in src/graph/graph.py (correct per scaffold
# canonical - it is the outer main-slot wrapper around the inner subgraph, not an
# inner node), which means the S-1 trust gate on this boundary is otherwise never
# probed by any test. This file closes that gap.

import json

import pytest
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import ChurnRetentionGraphNode

SAMPLE_SIGNALS = json.dumps(
    {"subscriber_id": "sub-pb6bis", "usage_volume_gb": 1.0, "call_frequency": 1.0, "plan_change_events": 4}
)


class TestGraphNodeBoundary:
    """PB-6-bis: ChurnRetentionGraphNode (outer main slot) security + mapping boundary."""

    def test_s1_trust_gate_denies_below_required_level(self):
        """S-1: caller below required_trust_level must be denied before execute()."""
        node = ChurnRetentionGraphNode()
        assert node.required_trust_level == TrustLevel.VERIFIED_EXTERNAL

        called = {"extract_input": False}
        node.extract_input = lambda state: called.__setitem__("extract_input", True) or state.get("validated_signals", "")

        state: AgentState = {
            "user_input": SAMPLE_SIGNALS,
            "validated_signals": SAMPLE_SIGNALS,
            "correlation_id": "pb6bis-s1",
            "caller_trust_level": TrustLevel.ANONYMOUS.value,
        }
        result = node(state)

        assert result.get("status") == "error"
        assert any("trust" in e.lower() for e in result.get("error_log", []))
        assert called["extract_input"] is False, "execute path must not run when S-1 denies the caller"

    def test_extract_input_maps_only_the_contracted_field(self):
        """Boundary mapping: extract_input() forwards only validated_signals, no extra state leakage."""
        node = ChurnRetentionGraphNode()
        state: AgentState = {
            "user_input": "raw-caller-supplied-should-not-leak",
            "validated_signals": SAMPLE_SIGNALS,
            "correlation_id": "pb6bis-extract",
        }
        forwarded = node.extract_input(state)

        assert forwarded == SAMPLE_SIGNALS
        assert "raw-caller-supplied-should-not-leak" not in forwarded

    def test_merge_output_maps_fields_explicitly_no_raw_passthrough(self):
        """Boundary mapping: merge_output() maps named fields, does not pass the raw
        subgraph result dict straight into parent state (criterion #9)."""
        node = ChurnRetentionGraphNode()
        state: AgentState = {"correlation_id": "pb6bis-merge"}
        sub_result = {
            "churn_forecast": '{"90d": 0.4}',
            "risk_tier": "high",
            "selected_offer": '{"offer_id": "o-1"}',
            "dispatch_result": '{"channel": "sms"}',
            "acceptance_status": "no_response",
            "output": {"narrative": "n/a"},
            "status": "success",
            "unmapped_internal_field": "must-not-leak-through",
        }
        merged = node.merge_output(state, sub_result)

        assert merged["churn_forecast"] == sub_result["churn_forecast"]
        assert merged["risk_tier"] == sub_result["risk_tier"]
        assert merged["selected_offer"] == sub_result["selected_offer"]
        assert merged["dispatch_result"] == sub_result["dispatch_result"]
        assert merged["acceptance_status"] == sub_result["acceptance_status"]
        assert merged["result"] == sub_result["output"]
        assert merged["status"] == sub_result["status"]
        # explicit field mapping only - no pass-through of the raw sub_result dict
        assert "unmapped_internal_field" not in merged

    def test_delegated_gating_is_by_design(self):
        """Delegation: GraphNode.__call__ intentionally skips the standard S-2/S-4/S-3
        lifecycle at this boundary - gating is delegated to the inner subgraph's own
        entry node (framework/nodes/graph_node.py), not bypassed."""
        from framework.nodes.graph_node import GraphNode

        assert issubclass(ChurnRetentionGraphNode, GraphNode)
        # The inner subgraph's own boundary node re-runs S-2 (see
        # [[cat2-pre-process-error-still-dispatches-main]]) - covered by
        # tests/unit/test_churn_forecast_node.py's defense-in-depth re-validation test.

    def test_error_strategy_declared(self):
        """Composition consistency (criterion #9): error_strategy is explicitly declared."""
        assert ChurnRetentionGraphNode.error_strategy == "propagate"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
