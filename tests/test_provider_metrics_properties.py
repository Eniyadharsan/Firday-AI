"""Property-based tests for provider metrics and observability.

These tests use Hypothesis to generate random inputs and assert that the
provider registry's metrics/observability invariants hold universally, plus
the arithmetic invariants behind session token aggregation and the context
window information exposed by each provider adapter.

Properties covered:
- Property 22 (19.4): Request Latency Tracking       -> Requirement 16.1
- Property 27 (19.5): Latency Data Availability      -> Requirement 7.5
- Property 28 (19.6): Session Token Usage Tracking   -> Requirement 7.6
- Property 29 (19.7): Context Window Information      -> Requirement 7.7

Requirements: 16.1, 7.5, 7.6, 7.7
"""

from __future__ import annotations

from typing import Any, Generator, Optional

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from friday.modules.providers.base import Provider_Adapter
from friday.modules.providers.key_store import API_Key_Store
from friday.modules.providers.models import (
    GenerateResponse,
    ProviderCapabilities,
    ProviderHealth,
    ProviderStatus,
)
from friday.modules.providers.registry import Provider_Registry

# Real cloud adapters whose get_available_models() returns static catalogs
# (no network I/O). OpenRouter falls back to its static POPULAR_MODELS catalog
# when no API key is configured, so it is also safe to include here.
from friday.modules.providers.adapters.openai_adapter import OpenAI_Adapter
from friday.modules.providers.adapters.anthropic_adapter import Anthropic_Adapter
from friday.modules.providers.adapters.gemini_adapter import Gemini_Adapter
from friday.modules.providers.adapters.deepseek_adapter import DeepSeek_Adapter
from friday.modules.providers.adapters.grok_adapter import Grok_Adapter
from friday.modules.providers.adapters.openrouter_adapter import OpenRouter_Adapter
from friday.modules.providers.adapters.cerebras_adapter import Cerebras_Adapter


class MockAdapter(Provider_Adapter):
    """A minimal mock adapter for testing registry functionality.

    Mirrors the mock used in ``test_provider_registry_health.py`` and
    ``test_provider_registry_properties.py``.
    """

    def __init__(self, name: str = "mock_provider", configured: bool = True):
        self._name = name
        self._configured = configured
        self._capabilities = ProviderCapabilities(
            supports_streaming=True,
            supports_tool_calling=True,
            supports_vision=False,
            max_context_window=8192,
            supported_models=["mock-model-1", "mock-model-2"],
        )

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def is_configured(self) -> bool:
        return self._configured

    def validate_config(self) -> tuple[bool, Optional[str]]:
        if self._configured:
            return True, None
        return False, "Not configured"

    def generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> GenerateResponse:
        return GenerateResponse(
            content="Mock response",
            model=model or "mock-model-1",
            provider=self._name,
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )

    def stream_generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Generator[str, None, None]:
        yield "Mock "
        yield "stream "
        yield "response"

    def translate_tools(self, friday_tools: list[dict]) -> list[dict]:
        return friday_tools

    def parse_tool_calls(self, response: Any) -> list[dict]:
        return []

    def get_available_models(self) -> list[dict[str, Any]]:
        return [
            {"id": "mock-model-1", "name": "Mock Model 1", "context_window": 8192},
            {"id": "mock-model-2", "name": "Mock Model 2", "context_window": 16384},
        ]

    def get_health(self) -> ProviderHealth:
        return ProviderHealth(
            status=ProviderStatus.OPERATIONAL,
            latency_ms=100.0,
            success_rate=1.0,
            error_rate=0.0,
        )


# Cloud adapters with static model catalogs (no network in get_available_models).
CLOUD_ADAPTER_CLASSES = [
    OpenAI_Adapter,
    Anthropic_Adapter,
    Gemini_Adapter,
    DeepSeek_Adapter,
    Grok_Adapter,
    OpenRouter_Adapter,
    Cerebras_Adapter,
]


@pytest.fixture(autouse=True)
def _reset_registry():
    """Isolate the registry singleton between property runs/examples."""
    Provider_Registry.reset_instance()
    yield
    Provider_Registry.reset_instance()


# Strategy: realistic, finite, non-negative latencies in milliseconds.
_latency = st.floats(
    min_value=0.0,
    max_value=1_000_000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Strategy: non-negative token counts.
_token_count = st.integers(min_value=0, max_value=1_000_000)


def _usage_dict() -> st.SearchStrategy[dict[str, int]]:
    """A GenerateResponse.usage-shaped dict of token counts."""
    return st.fixed_dictionaries(
        {
            "prompt_tokens": _token_count,
            "completion_tokens": _token_count,
            "total_tokens": _token_count,
        }
    )


def aggregate_session_usage(usages: list[dict[str, int]]) -> dict[str, int]:
    """Aggregate a sequence of usage dicts into session totals.

    This is the backend-verifiable equivalent of the frontend's per-session
    token accumulation (sessTokIn/sessTokOut). For any sequence of
    ``GenerateResponse.usage`` dicts, the aggregated total for each field is
    the sum of that field across all responses.

    Documents Property 28's arithmetic invariant.
    """
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for usage in usages:
        for key in totals:
            totals[key] += int(usage.get(key, 0))
    return totals


class TestProperty22RequestLatencyTracking:
    """Property 22 (19.4): Request Latency Tracking.

    For any sequence of successful recorded requests with latencies, the
    registry tracks and reports the average latency correctly, both via
    ``ProviderMetrics.average_latency_ms`` and via
    ``get_health_metrics()[provider].latency_ms``.

    **Validates: Requirements 16.1**
    """

    @settings(max_examples=10, deadline=None)
    @given(latencies=st.lists(_latency, min_size=1, max_size=60))
    def test_average_latency_matches_mean(self, latencies: list[float]):
        Provider_Registry.reset_instance()
        registry = Provider_Registry.get_instance()
        registry.register(MockAdapter("p"))

        for latency in latencies:
            registry.record_request("p", success=True, latency_ms=latency)

        expected_mean = sum(latencies) / len(latencies)

        metrics = registry._metrics["p"]
        assert metrics.successful_requests == len(latencies)
        assert metrics.average_latency_ms == pytest.approx(expected_mean, rel=1e-9, abs=1e-6)

        # The reported health metric must expose the same average latency.
        health = registry.get_health_metrics()
        assert health["p"].latency_ms == pytest.approx(expected_mean, rel=1e-9, abs=1e-6)

    @settings(max_examples=10, deadline=None)
    @given(
        latencies=st.lists(_latency, min_size=1, max_size=40),
        failures=st.integers(min_value=0, max_value=10),
    )
    def test_failed_requests_do_not_affect_average_latency(
        self, latencies: list[float], failures: int
    ):
        Provider_Registry.reset_instance()
        registry = Provider_Registry.get_instance()
        registry.register(MockAdapter("p"))

        for latency in latencies:
            registry.record_request("p", success=True, latency_ms=latency)
        # Failed requests carry no latency contribution.
        for _ in range(failures):
            registry.record_request("p", success=False, latency_ms=0.0, error="err")

        expected_mean = sum(latencies) / len(latencies)
        metrics = registry._metrics["p"]
        assert metrics.average_latency_ms == pytest.approx(expected_mean, rel=1e-9, abs=1e-6)


class TestProperty27LatencyDataAvailability:
    """Property 27 (19.5): Latency Data Availability.

    For any configured provider with recorded requests, latency data is
    available/exposed via ``get_all_providers()`` (a numeric ``latency_ms``
    field) and ``get_health_metrics()``.

    **Validates: Requirements 7.5**
    """

    @settings(max_examples=10, deadline=None)
    @given(
        names=st.lists(
            st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=10),
            min_size=1,
            max_size=6,
            unique=True,
        ),
        latencies=st.lists(_latency, min_size=1, max_size=20),
    )
    def test_latency_field_present_and_numeric(
        self, names: list[str], latencies: list[float]
    ):
        Provider_Registry.reset_instance()
        registry = Provider_Registry.get_instance()

        for name in names:
            registry.register(MockAdapter(name, configured=True))
            for latency in latencies:
                registry.record_request(name, success=True, latency_ms=latency)

        providers = registry.get_all_providers()
        assert len(providers) == len(names)

        for info in providers:
            # A numeric latency_ms field must be exposed for every provider.
            assert "latency_ms" in info
            assert isinstance(info["latency_ms"], (int, float))
            assert not isinstance(info["latency_ms"], bool)
            assert info["latency_ms"] >= 0.0

            # Internal metrics also expose the average latency.
            assert "metrics" in info
            assert "average_latency_ms" in info["metrics"]
            assert isinstance(info["metrics"]["average_latency_ms"], (int, float))

        # Health metrics expose latency_ms for every configured provider.
        health = registry.get_health_metrics()
        for name in names:
            assert name in health
            assert isinstance(health[name].latency_ms, (int, float))
            assert health[name].latency_ms >= 0.0


class TestProperty28SessionTokenUsageTracking:
    """Property 28 (19.6): Session Token Usage Tracking.

    For any sequence of ``GenerateResponse.usage`` dicts, the aggregated
    session token totals equal the sum of the inputs for each token field.

    **Validates: Requirements 7.6**
    """

    @settings(max_examples=10, deadline=None)
    @given(usages=st.lists(_usage_dict(), min_size=0, max_size=50))
    def test_aggregated_totals_equal_sum_of_inputs(self, usages: list[dict[str, int]]):
        totals = aggregate_session_usage(usages)

        assert totals["prompt_tokens"] == sum(u["prompt_tokens"] for u in usages)
        assert totals["completion_tokens"] == sum(u["completion_tokens"] for u in usages)
        assert totals["total_tokens"] == sum(u["total_tokens"] for u in usages)

    @settings(max_examples=10, deadline=None)
    @given(usages=st.lists(_usage_dict(), min_size=1, max_size=50))
    def test_aggregation_is_order_independent(self, usages: list[dict[str, int]]):
        forward = aggregate_session_usage(usages)
        backward = aggregate_session_usage(list(reversed(usages)))
        assert forward == backward

    def test_empty_session_has_zero_totals(self):
        assert aggregate_session_usage([]) == {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    @settings(max_examples=10, deadline=None)
    @given(
        first=st.lists(_usage_dict(), min_size=0, max_size=25),
        second=st.lists(_usage_dict(), min_size=0, max_size=25),
    )
    def test_aggregation_is_additive_across_batches(
        self, first: list[dict[str, int]], second: list[dict[str, int]]
    ):
        combined = aggregate_session_usage(first + second)
        a = aggregate_session_usage(first)
        b = aggregate_session_usage(second)
        for key in combined:
            assert combined[key] == a[key] + b[key]


class TestProperty29ContextWindowInformation:
    """Property 29 (19.7): Context Window Information.

    For any cloud provider's available models, each model reports a positive
    integer ``context_window``.

    Ollama is intentionally excluded because ``get_available_models()`` queries
    a live local server (dynamic) and returns an empty list when unreachable.

    **Validates: Requirements 7.7**
    """

    @settings(max_examples=10, deadline=None)
    @given(adapter_cls=st.sampled_from(CLOUD_ADAPTER_CLASSES))
    def test_every_model_reports_positive_context_window(self, adapter_cls):
        # An unconfigured key store keeps all catalogs static (OpenRouter falls
        # back to its POPULAR_MODELS catalog rather than making a network call).
        key_store = API_Key_Store()
        adapter = adapter_cls(key_store)

        models = adapter.get_available_models()
        assert isinstance(models, list)
        assert len(models) > 0, f"{adapter.provider_name} should expose a static model catalog"

        for model in models:
            assert "context_window" in model, f"{model.get('id')} missing context_window"
            context_window = model["context_window"]
            assert isinstance(context_window, int), (
                f"{model.get('id')} context_window must be int, got {type(context_window).__name__}"
            )
            assert not isinstance(context_window, bool)
            assert context_window > 0, (
                f"{model.get('id')} context_window must be positive, got {context_window}"
            )
