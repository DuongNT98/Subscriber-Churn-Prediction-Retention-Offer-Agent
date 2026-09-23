# TEL-C2-016 - Unit tests: per-node success + error/edge paths.

import json

from framework.schemas.agent_status import AgentStatus

from src.nodes.acceptance_track_node import AcceptanceTrackNode
from src.nodes.campaign_report_node import CampaignReportNode
from src.nodes.channel_dispatch_node import ChannelDispatchNode
from src.nodes.churn_forecast_node import ChurnForecastNode
from src.nodes.offer_select_node import OfferSelectNode
from src.nodes.risk_segment_node import RiskSegmentNode
from src.nodes.usage_data_ingest_node import UsageDataIngestNode
from src.schemas.state import from_json, to_json

HIGH_RISK_SIGNALS = {"subscriber_id": "sub-001", "usage_volume_gb": 1.0, "call_frequency": 1.0, "plan_change_events": 4}
LOW_RISK_SIGNALS = {"subscriber_id": "sub-002", "usage_volume_gb": 40.0, "call_frequency": 40.0, "plan_change_events": 0}


class TestUsageDataIngestNode:
    def test_success(self):
        state = {"user_input": json.dumps(HIGH_RISK_SIGNALS)}
        r = UsageDataIngestNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        signals = from_json(r["validated_signals"], {})
        assert signals["subscriber_id"] == "sub-001"

    def test_empty_input_error(self):
        assert UsageDataIngestNode().execute({"user_input": ""})["status"] == AgentStatus.ERROR

    def test_invalid_json_error(self):
        assert UsageDataIngestNode().execute({"user_input": "not json"})["status"] == AgentStatus.ERROR

    def test_missing_subscriber_id_error(self):
        state = {"user_input": json.dumps({"usage_volume_gb": 10})}
        assert UsageDataIngestNode().execute(state)["status"] == AgentStatus.ERROR

    def test_tsushin_no_himitsu_boundary_rejects_browsing_url(self):
        # 通信の秘密 (電気通信事業法) hard boundary - the single most important
        # behavior in this template. Must hard-reject, never pass through.
        payload = dict(HIGH_RISK_SIGNALS, browsing_url="https://example.com/private")
        state = {"user_input": json.dumps(payload)}
        r = UsageDataIngestNode().execute(state)
        assert r["status"] == AgentStatus.ERROR
        assert any("通信の秘密" in e for e in r["error_log"])

    def test_tsushin_no_himitsu_boundary_rejects_dns_query(self):
        payload = dict(HIGH_RISK_SIGNALS, dns_query="example.com")
        state = {"user_input": json.dumps(payload)}
        assert UsageDataIngestNode().execute(state)["status"] == AgentStatus.ERROR


class TestChurnForecastNode:
    def test_success(self):
        state = {"validated_signals": to_json(HIGH_RISK_SIGNALS)}
        r = ChurnForecastNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        forecast = from_json(r["churn_forecast"], {})
        assert "90d" in forecast

    def test_missing_signals_error(self):
        state = {"validated_signals": None, "user_input": ""}
        assert ChurnForecastNode().execute(state)["status"] == AgentStatus.ERROR


class TestRiskSegmentNode:
    def test_high_risk(self):
        state = {"churn_forecast": to_json({"30d": 0.4, "60d": 0.6, "90d": 0.8})}
        r = RiskSegmentNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["risk_tier"] == "high"

    def test_low_risk(self):
        state = {"churn_forecast": to_json({"30d": 0.05, "60d": 0.08, "90d": 0.1})}
        r = RiskSegmentNode().execute(state)
        assert r["risk_tier"] == "low"

    def test_missing_forecast_error(self):
        assert RiskSegmentNode().execute({"churn_forecast": None})["status"] == AgentStatus.ERROR


class TestOfferSelectNode:
    def test_high_risk_selects_offer(self):
        state = {"risk_tier": "high"}
        r = OfferSelectNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        offer = from_json(r["selected_offer"], None)
        assert offer is not None
        assert offer["offer_id"]

    def test_medium_risk_no_offer(self):
        state = {"risk_tier": "medium"}
        r = OfferSelectNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert from_json(r["selected_offer"], "sentinel") is None

    def test_missing_risk_tier_error(self):
        assert OfferSelectNode().execute({})["status"] == AgentStatus.ERROR

    def test_llm_used_for_copy_not_offer_choice(self):
        class FakeLLM:
            def complete(self, messages: list) -> dict:
                return {"content": "Friendly rewritten offer copy"}

        state = {"risk_tier": "high"}
        r = OfferSelectNode(llm=FakeLLM()).execute(state)
        offer = from_json(r["selected_offer"], {})
        assert offer["copy"] == "Friendly rewritten offer copy"
        assert offer["offer_id"]  # offer_id still comes from the matrix, not the LLM

    def test_llm_malformed_response_falls_back_to_copy_template(self):
        class MalformedLLM:
            def complete(self, messages: list) -> dict:
                return {"content": ""}  # well-formed shape, empty text

        state = {"risk_tier": "high"}
        r = OfferSelectNode(llm=MalformedLLM()).execute(state)
        offer = from_json(r["selected_offer"], {})
        assert offer["copy"] == "You're eligible for 20% off your next device upgrade — a thank-you for being a loyal subscriber."

    def test_llm_raising_falls_back_to_copy_template(self):
        class ExplodingLLM:
            def complete(self, messages: list) -> dict:
                raise RuntimeError("simulated Azure OpenAI API error")

        state = {"risk_tier": "high"}
        r = OfferSelectNode(llm=ExplodingLLM()).execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        offer = from_json(r["selected_offer"], {})
        assert offer["copy"] == "You're eligible for 20% off your next device upgrade — a thank-you for being a loyal subscriber."

    def test_no_llm_injected_and_no_bound_secrets_falls_back_to_copy_template(self):
        # Production shape: register_nodes() never passes llm=, and no
        # bound_secrets() is active outside a real /invoke request, so
        # resolve_llm() must degrade to the deterministic template text.
        state = {"risk_tier": "high", "correlation_id": "c1", "session_id": "s1", "thread_id": "t1", "trace_id": "tr1"}
        r = OfferSelectNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        offer = from_json(r["selected_offer"], {})
        assert offer["copy"] == "You're eligible for 20% off your next device upgrade — a thank-you for being a loyal subscriber."


class TestChannelDispatchNode:
    def test_dispatch_includes_opt_out(self):
        offer = {"offer_id": "device_discount_20", "kind": "device_discount", "copy": "..."}
        state = {"selected_offer": to_json(offer)}
        r = ChannelDispatchNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        result = from_json(r["dispatch_result"], {})
        assert result["opt_out_included"] is True

    def test_no_offer_skips_dispatch(self):
        state = {"selected_offer": to_json(None)}
        r = ChannelDispatchNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert from_json(r["dispatch_result"], "sentinel") is None

    def test_extra_gate_blocks_pii_leak(self):
        bad_state = {"dispatch_result": to_json({"subscriber_id": "sub-001", "channel": "sms"})}
        out = ChannelDispatchNode()._extra_security_gate_output(bad_state)
        assert out["status"] == AgentStatus.ERROR

    def test_extra_gate_passthrough_clean_result(self):
        good_state = {"dispatch_result": to_json({"channel": "sms", "opt_out_included": True})}
        assert ChannelDispatchNode()._extra_security_gate_output(good_state) is good_state


class TestAcceptanceTrackNode:
    def test_success(self):
        state = {"dispatch_result": to_json({"channel": "sms"})}
        r = AcceptanceTrackNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["acceptance_status"] == "no_response"

    def test_no_dispatch_still_succeeds(self):
        state = {"dispatch_result": to_json(None)}
        r = AcceptanceTrackNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS


class TestCampaignReportNode:
    def test_success(self):
        state = {
            "risk_tier": "high",
            "selected_offer": to_json({"offer_id": "device_discount_20"}),
            "acceptance_status": "no_response",
        }
        r = CampaignReportNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        report = from_json(r["campaign_report"], {})
        assert report["risk_tier"] == "high"

    def test_missing_risk_tier_error(self):
        assert CampaignReportNode().execute({})["status"] == AgentStatus.ERROR

    def test_llm_used_for_narrative(self):
        class FakeLLM:
            def complete(self, messages: list) -> dict:
                return {"content": "Narrative rendered by the LLM."}

        state = {"risk_tier": "high", "selected_offer": to_json(None), "acceptance_status": None}
        r = CampaignReportNode(llm=FakeLLM()).execute(state)
        report = from_json(r["campaign_report"], {})
        assert report["narrative"] == "Narrative rendered by the LLM."

    def test_llm_malformed_response_falls_back_to_summary(self):
        class MalformedLLM:
            def complete(self, messages: list) -> dict:
                return {}  # no "content" key at all

        state = {"risk_tier": "high", "selected_offer": to_json(None), "acceptance_status": None}
        r = CampaignReportNode(llm=MalformedLLM()).execute(state)
        report = from_json(r["campaign_report"], {})
        assert report["narrative"] == (
            "Cohort risk tier: high. Offer dispatched: none. Acceptance status: pending."
        )

    def test_llm_raising_falls_back_to_summary(self):
        class ExplodingLLM:
            def complete(self, messages: list) -> dict:
                raise RuntimeError("simulated Azure OpenAI API error")

        state = {"risk_tier": "high", "selected_offer": to_json(None), "acceptance_status": None}
        r = CampaignReportNode(llm=ExplodingLLM()).execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        report = from_json(r["campaign_report"], {})
        assert report["narrative"] == (
            "Cohort risk tier: high. Offer dispatched: none. Acceptance status: pending."
        )

    def test_no_llm_injected_and_no_bound_secrets_falls_back_to_summary(self):
        # Production shape: register_nodes() never passes llm=, and no
        # bound_secrets() is active outside a real /invoke request, so
        # resolve_llm() must degrade to the deterministic summary text.
        state = {
            "risk_tier": "high",
            "selected_offer": to_json(None),
            "acceptance_status": None,
            "correlation_id": "c1",
            "session_id": "s1",
            "thread_id": "t1",
            "trace_id": "tr1",
        }
        r = CampaignReportNode().execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        report = from_json(r["campaign_report"], {})
        assert report["narrative"] == (
            "Cohort risk tier: high. Offer dispatched: none. Acceptance status: pending."
        )

    def test_extra_gate_blocks_subscriber_pii(self):
        bad_state = {"campaign_report": to_json({"risk_tier": "high", "subscriber_id": "sub-001"})}
        out = CampaignReportNode()._extra_security_gate_output(bad_state)
        assert out["status"] == AgentStatus.ERROR

    def test_extra_gate_passthrough_clean_report(self):
        good_state = {"campaign_report": to_json({"risk_tier": "high", "narrative": "..."})}
        assert CampaignReportNode()._extra_security_gate_output(good_state) is good_state
