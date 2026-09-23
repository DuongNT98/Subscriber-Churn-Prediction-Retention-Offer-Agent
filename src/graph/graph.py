"""AgentCore Platform v1.0 - TEL-C2-016 outer graph (Cat 2).

Cat 2: outer AgentBaseGraph with the fixed 5-node backbone. Domain complexity
(churn forecast -> risk segment -> offer select -> channel dispatch ->
acceptance track) is encapsulated in ChurnRetentionGraphNode (the `main`
slot), which wraps the inner ChurnRetentionWorkflowGraph. Do NOT override
add_edges().

Backbone: initialize -> pre_process(UsageDataIngest) -> main(GraphNode)
          -> post_process(CampaignReport) -> finalize

ChurnRetentionGraphNode lives here (not under src/nodes/) - the PB-6
invoke-order test only discovers BaseNode subclasses under src/nodes/, and a
GraphNode's __call__ intentionally skips the standard S-2/S-4/S-3 lifecycle
(gating is delegated to the inner subgraph). This does NOT exempt it from S-1
(required_trust_level) - see tests/proof_of_boundary/test_pb_graphnode_boundary.py
for the compensating boundary test.
"""

from typing import Any, ClassVar, cast

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.campaign_report_node import CampaignReportNode
from src.nodes.usage_data_ingest_node import UsageDataIngestNode
from src.schemas.state import State


# GraphNode resolves to Any (SDK ships no py.typed marker - see
# pyproject.toml [[tool.mypy.overrides]]); this is a real base class at
# runtime, just unverifiable by mypy until the SDK ships type stubs.
class ChurnRetentionGraphNode(GraphNode):  # type: ignore[misc]
    """Wraps the inner churn-forecast-to-retention workflow (Cat 2 composition)."""

    # S-1: outer boundary node (main slot) - matches agent.yaml required_trust_level.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL
    # "propagate": re-raise inner errors as SubgraphError (fail fast - default).
    error_strategy: ClassVar[str] = "propagate"
    # No HITL in this template.
    propagate_hitl: ClassVar[bool] = False

    def get_subgraph(self) -> Any:
        from src.graph.domain_workflow_graph import ChurnRetentionWorkflowGraph

        # No config to thread through: OfferSelectNode resolves its own LLM
        # client per invocation from the caller's bound secrets (see
        # src/services/llm_provider.py) rather than from Graph(config=...).
        sg = ChurnRetentionWorkflowGraph(config={})
        sg.compile()
        return sg

    def extract_input(self, state: AgentState) -> str:
        # extract_input() can only forward a single string across the
        # GraphNode subgraph boundary (a known constraint learned on an
        # earlier template's GraphNode subgraph boundary). validated_signals
        # is already the JSON payload UsageDataIngestNode produced.
        emit_trace_event(
            "churn_retention_workflow_dispatched", {"correlation_id": state.get("correlation_id", "")}, state
        )
        # cast(): AgentState.get() resolves to Any (see class docstring), but
        # validated_signals/user_input are always strings by this template's
        # own state contract (src/schemas/state.py).
        return cast(str, state.get("validated_signals", state.get("user_input", "")))

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        emit_trace_event(
            "churn_retention_workflow_completed",
            {"correlation_id": state.get("correlation_id", ""), "status": str(sub_result.get("status"))},
            state,
        )
        return {
            "churn_forecast": sub_result.get("churn_forecast"),
            "risk_tier": sub_result.get("risk_tier"),
            "selected_offer": sub_result.get("selected_offer"),
            "dispatch_result": sub_result.get("dispatch_result"),
            "acceptance_status": sub_result.get("acceptance_status"),
            "result": sub_result.get("output"),
            "status": sub_result.get("status"),
        }


# AgentBaseGraph resolves to Any (SDK ships no py.typed marker - see
# pyproject.toml [[tool.mypy.overrides]]); this is a real base class at
# runtime, just unverifiable by mypy until the SDK ships type stubs.
class TELChurnRetentionAgent(AgentBaseGraph):  # type: ignore[misc]
    """TEL-C2-016 - Subscriber Churn Prediction & Retention Offer Agent (Cat 2)."""

    @property
    def name(self) -> str:
        return "tel-c2-016"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects initialize + finalize

        # No llm= passed: OfferSelectNode/CampaignReportNode each resolve
        # their own LLM client per invocation from the caller's bound secrets
        # (see src/services/llm_provider.py) rather than from Graph(config=...).
        self._nodes["pre_process"] = UsageDataIngestNode()
        self._nodes["main"] = ChurnRetentionGraphNode()
        self._nodes["post_process"] = CampaignReportNode()

    # add_edges() is NOT overridden - backbone wiring belongs to the framework.


# Alias for agent.yaml module:"src.graph" resolution (AgentRegistry / api/server.py).
Graph = TELChurnRetentionAgent
