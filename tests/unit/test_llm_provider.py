# src/services/llm_provider.py::resolve_llm() - graceful-degrade LLM resolution.
# No real Azure OpenAI network call anywhere in this suite: bound secrets are
# fake (InMemoryProvider) and either construction fails locally (bad
# endpoint) or nothing ever reaches the network because construction itself
# is what's under test.

from framework.secrets.context import bound_secrets
from shared.secrets.inmemory_provider import InMemoryProvider

from src.services.llm_provider import resolve_llm

VALID_STATE = {"correlation_id": "c1", "session_id": "s1", "thread_id": "t1", "trace_id": "tr1"}

VALID_SECRETS = {
    "AZURE_OPENAI_API_KEY": "sk-fake",
    "AZURE_OPENAI_ENDPOINT": "https://fake-resource.services.ai.azure.com",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-fake",
}


class TestResolveLlm:
    def test_constructor_llm_takes_precedence(self):
        sentinel = object()
        assert resolve_llm(sentinel, VALID_STATE) is sentinel

    def test_no_bound_secrets_degrades_to_none(self):
        # Outside a bound_secrets() scope, current_secrets() is the
        # NullProvider default - every require() raises MissingSecret.
        assert resolve_llm(None, VALID_STATE) is None

    def test_missing_secret_degrades_to_none(self):
        with bound_secrets(InMemoryProvider({"AZURE_OPENAI_API_KEY": "sk-fake"})):
            assert resolve_llm(None, VALID_STATE) is None

    def test_malformed_endpoint_degrades_to_none(self):
        bad_secrets = dict(VALID_SECRETS, AZURE_OPENAI_ENDPOINT="https://fake-resource.services.ai.azure.com/openai/v1")
        with bound_secrets(InMemoryProvider(bad_secrets)):
            assert resolve_llm(None, VALID_STATE) is None

    def test_bare_state_missing_lifecycle_fields_degrades_to_none(self):
        # PB-6's generic node-discovery fixture calls node_cls() with a
        # minimal state (no session_id/thread_id/trace_id) - from_state()
        # indexes those with state[...], not .get(...), so this must not
        # raise KeyError out of resolve_llm().
        with bound_secrets(InMemoryProvider(VALID_SECRETS)):
            assert resolve_llm(None, {"correlation_id": "c1"}) is None

    def test_valid_secrets_and_state_returns_a_real_client(self):
        with bound_secrets(InMemoryProvider(VALID_SECRETS)):
            llm = resolve_llm(None, VALID_STATE)
        assert llm is not None
        assert hasattr(llm, "complete")
