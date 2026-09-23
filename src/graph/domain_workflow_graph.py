"""AgentCore Platform v1.0 - TEL-C2-016 inner domain workflow graph.

Cat 2 inner graph: churn forecast -> risk segment -> offer select ->
channel dispatch -> acceptance track. Instantiated by
ChurnRetentionGraphNode.get_subgraph() in graph.py.

Pipeline:
    START -> churn_forecast -> risk_segment -> {route}
          -> [high risk]         offer_select -> channel_dispatch -> acceptance_track -> END
          -> [medium/low risk]   END (no offer needed - valid terminal state, not an error)

Risk-tier gate (Engineer Review §4 Step 3): only high-risk subscribers reach
offer_select/channel_dispatch/acceptance_track. Medium/low-risk subscribers
short-circuit immediately after risk_segment via route() - this is a normal,
successful terminal state, not an error path.
"""

from typing import Any, cast

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

from src.nodes.acceptance_track_node import AcceptanceTrackNode
from src.nodes.channel_dispatch_node import ChannelDispatchNode
from src.nodes.churn_forecast_node import ChurnForecastNode
from src.nodes.offer_select_node import OfferSelectNode
from src.nodes.risk_segment_node import RiskSegmentNode
from src.schemas.state import State


# BaseGraph resolves to Any (SDK ships no py.typed marker - see
# pyproject.toml [[tool.mypy.overrides]]); this is a real base class at
# runtime, just unverifiable by mypy until the SDK ships type stubs.
class ChurnRetentionWorkflowGraph(BaseGraph):  # type: ignore[misc]
    """Inner graph for the TEL-C2-016 churn-forecast-to-retention workflow."""

    @property
    def name(self) -> str:
        return "churn-retention-workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        # No mandatory config.
        pass

    def register_nodes(self) -> None:
        # No super() - BaseGraph.register_nodes() is abstract.
        # No llm= passed: OfferSelectNode resolves its own LLM client per
        # invocation from the caller's bound secrets (src/services/llm_provider.py).
        self._nodes["churn_forecast"] = ChurnForecastNode()
        self._nodes["risk_segment"] = RiskSegmentNode()
        self._nodes["offer_select"] = OfferSelectNode()
        self._nodes["channel_dispatch"] = ChannelDispatchNode()
        self._nodes["acceptance_track"] = AcceptanceTrackNode()

    def add_edges(self) -> None:
        self._sg.add_edge(START, "churn_forecast")
        self._sg.add_conditional_edges(
            "churn_forecast",
            lambda s: END if self._is_error(s) else "risk_segment",
            {"risk_segment": "risk_segment", END: END},
        )
        # Risk-tier gate: only high-risk subscribers proceed to offer
        # selection + dispatch + acceptance tracking. Medium/low risk ends
        # the inner workflow right here - a valid successful terminal state.
        self._sg.add_conditional_edges("risk_segment", self.route, {"offer_select": "offer_select", END: END})
        self._sg.add_edge("offer_select", "channel_dispatch")
        self._sg.add_edge("channel_dispatch", "acceptance_track")
        self._sg.add_edge("acceptance_track", END)

    @staticmethod
    def _is_error(state: AgentState) -> bool:
        return state.get("status") in (AgentStatus.ERROR.value, AgentStatus.ERROR.value)

    def route(self, state: AgentState) -> str:
        """Risk-tier gate: proceed to offer_select only for high-risk subscribers."""
        # cast(): END is langgraph's typed str sentinel at runtime, but resolves
        # to Any here (langgraph.* uses follow_imports = "skip" - see pyproject.toml).
        if self._is_error(state):
            return cast(str, END)
        return "offer_select" if state.get("risk_tier") == "high" else cast(str, END)

    def get_output(self, state: AgentState) -> dict[str, Any]:
        return {
            "churn_forecast": state.get("churn_forecast"),
            "risk_tier": state.get("risk_tier"),
            "selected_offer": state.get("selected_offer"),
            "dispatch_result": state.get("dispatch_result"),
            "acceptance_status": state.get("acceptance_status"),
            "output": state.get("acceptance_status"),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
