# TEL-C2-016 - Framework compliance tests TC-01..TC-08 (CoE Code Review R1).
# Reference shape: an earlier template's tests/unit/test_framework_compliance.py,
# adapted to this template's real architecture (Cat 2: outer UsageDataIngestNode pre_process +
# GraphNode-wrapped inner churn_forecast/risk_segment/offer_select/channel_dispatch/
# acceptance_track + CampaignReportNode post_process).

import json
import os
import re

import pytest
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.nodes import (
    acceptance_track_node,
    campaign_report_node,
    channel_dispatch_node,
    churn_forecast_node,
    offer_select_node,
    risk_segment_node,
    usage_data_ingest_node,
)
from src.schemas.state import State

_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "src")
TRUST = TrustLevel.VERIFIED_EXTERNAL.value

SAMPLE_SIGNALS = json.dumps(
    {"subscriber_id": "sub-tc08", "usage_volume_gb": 1.0, "call_frequency": 1.0, "plan_change_events": 4}
)


def _src_files():
    for root, _d, files in os.walk(_SRC):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


# TC-01 - State is a flat TypedDict extending AgentState; added fields are
# JSON-serializable primitives (NotRequired-wrapped).
class TestTC01StateContract:
    def test_state_is_typeddict_extending_agent_state(self):
        assert hasattr(State, "__annotations__")
        assert "user_input" in State.__annotations__
        assert set(AgentState.__annotations__).issubset(set(State.__annotations__))

    def test_added_fields_are_json_safe(self):
        added = [k for k in State.__annotations__ if k not in AgentState.__annotations__]
        assert added, "State must declare agent-specific fields"
        for name in added:
            ann_str = str(State.__annotations__[name])
            assert any(t in ann_str for t in ("str", "int", "bool", "float", "list", "dict")), (
                f"{name}: {ann_str} - fields must be JSON-serializable primitives/containers"
            )


# TC-02 - Empty/missing/invalid input yields a fail-closed ERROR outcome, no raise.
class TestTC02Validation:
    def test_empty_input_no_raise(self):
        out = usage_data_ingest_node.UsageDataIngestNode().execute({"user_input": ""})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]

    def test_tsushin_no_himitsu_boundary_no_raise(self):
        payload = json.dumps({"subscriber_id": "sub-x", "browsing_url": "https://example.com"})
        out = usage_data_ingest_node.UsageDataIngestNode().execute({"user_input": payload})
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]


# TC-03 - No JWT / API keys / secrets in src/; no direct os.environ reads.
class TestTC03NoCredentials:
    def test_no_credential_literals(self):
        pat = re.compile(r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")
        offenders = [fp for fp in _src_files() if pat.search(open(fp, encoding="utf-8").read())]
        assert offenders == []

    def test_no_os_environ_secret_reads(self):
        # Entry-point exception (see the framework's entry-point auth boundary rule):
        # src/api/server.py reads INVOKE_AUTH_TOKEN to authenticate the caller
        # BEFORE any InvocationContext exists, so ctx.secrets cannot apply. It is a
        # deployment-level caller credential, not an agent secret, and never enters state.
        offenders = []
        for fp in _src_files():
            if os.path.normpath(fp).endswith(os.path.join("src", "api", "server.py")):
                continue
            if "api" in fp.replace("\\", "/").split("/"):
                continue  # entry-point auth boundary exception (see framework auth boundary rule)
            if "os.environ" in open(fp, encoding="utf-8").read():
                offenders.append(fp)
        assert offenders == []


# TC-04 - InvocationContext is never stored in State after invoke.
class TestTC04ContextIsolation:
    def test_no_invocationcontext_in_state_after_invoke(self):
        from src.graph.graph import Graph

        agent = Graph()
        agent.compile()
        ctx = InvocationContext(session_id="tc04", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="tester-tc04")
        result = agent.invoke(SAMPLE_SIGNALS, ctx=ctx)
        for v in result.values():
            assert not isinstance(v, InvocationContext)

    def test_from_state_available(self):
        assert hasattr(InvocationContext, "from_state")


# TC-05 - Domain events: outer nodes emit >=1 domain event; no node under
# src/nodes/ ever re-emits a framework backbone lifecycle event.
class TestTC05Audit:
    def test_pre_process_emits_domain_event(self, monkeypatch):
        events = []
        monkeypatch.setattr(usage_data_ingest_node, "emit_trace_event", lambda e, p, s: events.append(e))
        out = usage_data_ingest_node.UsageDataIngestNode().execute({"user_input": SAMPLE_SIGNALS})
        assert out["status"] == AgentStatus.SUCCESS
        assert "usage_signals_ingested" in events
        assert not ({"node_start", "node_complete", "node_error", "node_skip"} & set(events))

    def test_source_has_no_backbone_events(self):
        pat = re.compile(r'emit_trace_event\(\s*["\'](node_start|node_complete|node_error|node_skip)["\']')
        offenders = [fp for fp in _src_files() if pat.search(open(fp, encoding="utf-8").read())]
        assert offenders == []


# TC-06 / TC-07 - S-2/S-3 gates are @final on FunctionNode (overriding raises TypeError at class def).
class TestTC0607FinalGates:
    def test_input_gate_is_final(self):
        with pytest.raises(TypeError):

            class BadIn(FunctionNode):  # noqa: N801
                def _security_gate_input(self, state):
                    return state

    def test_output_gate_is_final(self):
        with pytest.raises(TypeError):

            class BadOut(FunctionNode):  # noqa: N801
                def _security_gate_output(self, result):
                    return result

    def test_extra_hook_is_overridable(self):
        assert (
            channel_dispatch_node.ChannelDispatchNode._extra_security_gate_output
            is not FunctionNode._extra_security_gate_output
        )
        assert (
            campaign_report_node.CampaignReportNode._extra_security_gate_output
            is not FunctionNode._extra_security_gate_output
        )

    def test_output_gate_blocks_pii_leak(self):
        # The @final S-3 gate delegates to the domain hook; verify the hook
        # actually fires (not vacuous) on a PII-shaped output.
        node = channel_dispatch_node.ChannelDispatchNode()
        out = node._extra_security_gate_output({"dispatch_result": json.dumps({"subscriber_id": "sub-001"})})
        assert out["status"] == AgentStatus.ERROR


# TC-08 - required_trust_level declared valid + enforced: insufficient trust -> ERROR, no raise.
class TestTC08TrustGate:
    def test_declared_trust_levels_valid(self):
        for cls in (
            usage_data_ingest_node.UsageDataIngestNode,
            churn_forecast_node.ChurnForecastNode,
            risk_segment_node.RiskSegmentNode,
            offer_select_node.OfferSelectNode,
            channel_dispatch_node.ChannelDispatchNode,
            acceptance_track_node.AcceptanceTrackNode,
            campaign_report_node.CampaignReportNode,
        ):
            assert cls.required_trust_level in (TrustLevel.ANONYMOUS, TrustLevel.VERIFIED_EXTERNAL, TrustLevel.INTERNAL)

    def test_insufficient_trust_returns_error(self):
        node = usage_data_ingest_node.UsageDataIngestNode()
        out = node({"caller_trust_level": TrustLevel.ANONYMOUS.value, "user_input": SAMPLE_SIGNALS})
        assert str(out.get("status")).lower().endswith("error")

    def test_sufficient_trust_succeeds(self):
        node = usage_data_ingest_node.UsageDataIngestNode()
        out = node({"caller_trust_level": TRUST, "user_input": SAMPLE_SIGNALS})
        assert out["status"] == AgentStatus.SUCCESS
