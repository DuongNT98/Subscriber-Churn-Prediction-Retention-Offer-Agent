"""AgentCore Platform v1.0 - TEL-C2-016 LLM provider (Azure OpenAI, graceful degrade).

Separate from service.py (which stays framework/agenticstar-import-free by
design) because this module touches framework.schemas.invocation_context and
shared.services.llm.* directly.

Builds a fresh AzureOpenAIClient per invocation from the invocation-scoped
SecretProvider - never cached on a node instance. Node instances are
constructed once and reused across every invocation via the registry's LRU
cache, so caching a client built from one caller's secrets would leave it
visible to the next caller (violates the framework's secret-isolation timing rule).

OfferSelectNode's/CampaignReportNode's LLM usage here is additive (renders
copy/narrative text on top of an already-valid deterministic result), never a
hard requirement - any failure degrades to None so the caller keeps its
existing deterministic/heuristic value.
"""

from typing import Any

from framework.schemas.invocation_context import InvocationContext


def resolve_llm(constructor_llm: Any, state: dict[str, Any]) -> Any:
    """Return an LLM client for this invocation, or None to fall back to the
    deterministic/heuristic baseline.

    constructor_llm is a test-double seam only - production node construction
    (register_nodes()) never passes one, so real requests always build fresh
    here from the invocation's own bound secrets.
    """
    if constructor_llm is not None:
        return constructor_llm
    try:
        from shared.services.llm.azure_openai_client import AzureOpenAIClient

        ctx = InvocationContext.from_state(state)
        return AzureOpenAIClient(
            {
                "api_key": ctx.secrets.require("AZURE_OPENAI_API_KEY"),
                "azure_endpoint": ctx.secrets.require("AZURE_OPENAI_ENDPOINT"),
                "azure_deployment": ctx.secrets.require("AZURE_OPENAI_DEPLOYMENT"),
            }
        )
    except Exception:
        # Missing secret, malformed endpoint, import/construction error, or a
        # bare-state test harness missing session_id/thread_id/trace_id -
        # all degrade to "no LLM this invocation", never a hard failure.
        return None
