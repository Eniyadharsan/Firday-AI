"""Property-based tests for Provider_Registry.

These tests use Hypothesis to generate random inputs (varying numbers of
provider registrations, random success/failure request sequences) and assert
that the registry's invariants hold universally, complementing the
example-based tests in ``test_provider_registry_health.py``.

Properties covered:
- Property 2  (3.2): Provider Registration Tracking
- Property 23 (3.4): Success and Error Rate Calculation
- Property 24 (3.5): Degraded Status Threshold
- Property 25 (3.6): Unavailable Status Threshold

Requirements: 1.3, 1.4, 16.1, 16.2, 16.4, 16.5
"""

from __future__ import annotations

from typing import Any, Generator, Optional

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from friday.modules.providers.base import Provider_Adapter
from friday.modules.providers.models import (
    GenerateResponse,
    ProviderCapabilities,
    ProviderHealth,
    ProviderStatus,
)
from friday.modules.providers.registry import Provider_Registry


class MockAdapter(Provider_Adapter):
    """A minimal mock adapter for testing registry functionality.

    Mirrors the mock used in ``test_provider_registry_health.py``. By default
    ``is_configured()`` returns True, so the first registered adapter becomes
    the active provider under the registry's configured-provider preference.
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


# ---------------------------------------------------------------------------
# Reference helpers - independent re-implementations of the invariants used to
# cross-check the registry's own calculations.
# ---------------------------------------------------------------------------

def _consecutive_failures(sequence: list[bool]) -> int:
    """Count trailing consecutive failures (False values) in a sequence."""
    consec = 0
    for success in sequence:
        consec = 0 if success else consec + 1
    return consec


def _apply_sequence(registry: Provider_Registry, provider: str, sequence: list[bool]) -> None:
    """Record a request for each entry in the success/failure sequence."""
    for success in sequence:
        registry.record_request(
            provider,
            success=success,
            latency_ms=100.0 if success else 0.0,
            error=None if success else "err",
        )


# Strategy for valid, unique provider names (non-empty printable identifiers).
_provider_name = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),  # a-z
    min_size=1,
    max_size=12,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    """Isolate the singleton between property runs."""
    Provider_Registry.reset_instance()
    yield
    Provider_Registry.reset_instance()


class TestProperty2ProviderRegistrationTracking:
    """Property 2 (3.2): Provider Registration Tracking.

    For any valid Provider_Adapter registration, the registry SHALL contain
    that adapter with correct config/status accessible via get_adapter().

    **Validates: Requirements 1.3, 1.4**
    """

    @settings(max_examples=100, deadline=None)
    @given(names=st.lists(_provider_name, min_size=1, max_size=8, unique=True))
    def test_all_registered_adapters_are_retrievable(self, names: list[str]):
        Provider_Registry.reset_instance()
        registry = Provider_Registry.get_instance()

        adapters = {name: MockAdapter(name) for name in names}
        for name, adapter in adapters.items():
            error = registry.register(adapter)
            assert error is None, f"registration should succeed, got: {error}"

        # Every registered adapter is retrievable and is the exact instance.
        for name, adapter in adapters.items():
            assert registry.has_provider(name)
            assert registry.get_adapter(name) is adapter

        # Registry count reflects exactly the registered providers.
        assert registry.get_provider_count() == len(names)
        assert set(registry.get_all_provider_names()) == set(names)

    @settings(max_examples=100, deadline=None)
    @given(names=st.lists(_provider_name, min_size=1, max_size=8, unique=True))
    def test_registered_config_and_status_accessible(self, names: list[str]):
        Provider_Registry.reset_instance()
        registry = Provider_Registry.get_instance()

        for name in names:
            registry.register(MockAdapter(name, configured=True))

        health = registry.get_health_metrics()
        for name in names:
            # Config is accessible via the adapter.
            assert registry.get_adapter(name).is_configured() is True
            # Status is accessible and, with no requests, OPERATIONAL for a
            # configured provider.
            assert name in health
            assert health[name].status == ProviderStatus.OPERATIONAL

    @settings(max_examples=100, deadline=None)
    @given(names=st.lists(_provider_name, min_size=1, max_size=8, unique=True))
    def test_first_configured_adapter_becomes_active(self, names: list[str]):
        Provider_Registry.reset_instance()
        registry = Provider_Registry.get_instance()

        for name in names:
            registry.register(MockAdapter(name, configured=True))

        # MockAdapter.is_configured() is True, so the first registered adapter
        # becomes the active provider.
        assert registry.get_active_provider_name() == names[0]


class TestProperty23SuccessErrorRate:
    """Property 23 (3.4): Success and Error Rate Calculation.

    success_rate = successful/total and error_rate = failed/total for any
    sequence of recorded requests.

    **Validates: Requirements 16.1, 16.2**
    """

    @settings(max_examples=200, deadline=None)
    @given(sequence=st.lists(st.booleans(), min_size=1, max_size=60))
    def test_rates_match_counts(self, sequence: list[bool]):
        Provider_Registry.reset_instance()
        registry = Provider_Registry.get_instance()
        registry.register(MockAdapter("p"))

        _apply_sequence(registry, "p", sequence)

        total = len(sequence)
        successful = sum(1 for s in sequence if s)
        failed = total - successful

        metrics = registry._metrics["p"]
        assert metrics.total_requests == total
        assert metrics.successful_requests == successful
        assert metrics.failed_requests == failed
        assert metrics.success_rate == pytest.approx(successful / total)
        assert metrics.error_rate == pytest.approx(failed / total)
        # Rates always partition to 1.0.
        assert metrics.success_rate + metrics.error_rate == pytest.approx(1.0)


class TestProperty24DegradedThreshold:
    """Property 24 (3.5): Degraded Status Threshold.

    A configured provider is DEGRADED iff error rate > 50% over at least 10
    requests, provided it is not already UNAVAILABLE (>=5 consecutive
    failures, which takes priority).

    **Validates: Requirements 16.4**
    """

    @settings(max_examples=300, deadline=None)
    @given(sequence=st.lists(st.booleans(), min_size=1, max_size=60))
    def test_degraded_matches_reference(self, sequence: list[bool]):
        Provider_Registry.reset_instance()
        registry = Provider_Registry.get_instance()
        registry.register(MockAdapter("p"))

        _apply_sequence(registry, "p", sequence)

        total = len(sequence)
        failed = sum(1 for s in sequence if not s)
        error_rate = failed / total
        consec = _consecutive_failures(sequence)

        # DEGRADED only when NOT unavailable, >=10 requests, and >50% errors.
        expected_degraded = (
            consec < 5 and total >= 10 and error_rate > 0.5
        )

        degraded = registry.get_degraded_providers()
        assert ("p" in degraded) == expected_degraded


class TestProperty25UnavailableThreshold:
    """Property 25 (3.6): Unavailable Status Threshold.

    A configured provider is UNAVAILABLE iff it has 5 or more consecutive
    failures. A success resets the consecutive-failure count.

    **Validates: Requirements 16.5**
    """

    @settings(max_examples=300, deadline=None)
    @given(sequence=st.lists(st.booleans(), min_size=1, max_size=60))
    def test_unavailable_matches_reference(self, sequence: list[bool]):
        Provider_Registry.reset_instance()
        registry = Provider_Registry.get_instance()
        registry.register(MockAdapter("p"))

        _apply_sequence(registry, "p", sequence)

        expected_unavailable = _consecutive_failures(sequence) >= 5

        unavailable = registry.get_unavailable_providers()
        assert ("p" in unavailable) == expected_unavailable

    @settings(max_examples=200, deadline=None)
    @given(
        prefix=st.lists(st.booleans(), min_size=0, max_size=20),
        trailing_failures=st.integers(min_value=5, max_value=15),
    )
    def test_five_consecutive_trailing_failures_always_unavailable(
        self, prefix: list[bool], trailing_failures: int
    ):
        Provider_Registry.reset_instance()
        registry = Provider_Registry.get_instance()
        registry.register(MockAdapter("p"))

        # A success right before the trailing failures ensures the trailing
        # block is exactly the consecutive-failure streak.
        sequence = prefix + [True] + [False] * trailing_failures
        _apply_sequence(registry, "p", sequence)

        assert "p" in registry.get_unavailable_providers()

    @settings(max_examples=200, deadline=None)
    @given(sequence=st.lists(st.booleans(), min_size=1, max_size=40))
    def test_success_resets_consecutive_failures(self, sequence: list[bool]):
        Provider_Registry.reset_instance()
        registry = Provider_Registry.get_instance()
        registry.register(MockAdapter("p"))

        # Append a success: consecutive failures must reset, so never UNAVAILABLE.
        _apply_sequence(registry, "p", sequence + [True])

        assert "p" not in registry.get_unavailable_providers()
