"""Property test for provider selection state update (task 19.3).

Property 26: Provider Selection State Update
For any valid provider/model selection via set_active(), the active provider
and model SHALL be updated and subsequent get_active_adapter() calls SHALL
return the newly selected adapter.

**Validates: Requirements 7.2**

Uses hypothesis to generate random sets of registered providers and random
selections among them (with explicit models), then asserts the registry's
state getters reflect the selection. FAKE adapters are used - NO real API
calls. A fresh Provider_Registry() instance is used per example (no singleton).
"""

from __future__ import annotations

from typing import Any, Generator, Optional

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


class FakeAdapter(Provider_Adapter):
    """Minimal fully-featured fake Provider_Adapter for registry testing."""

    def __init__(self, name: str, models: list[str]) -> None:
        self._name = name
        self._capabilities = ProviderCapabilities(supported_models=list(models))

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def is_configured(self) -> bool:
        return True

    def validate_config(self) -> tuple[bool, Optional[str]]:
        return True, None

    def generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> GenerateResponse:
        return GenerateResponse(
            content="ok",
            model=model or f"{self._name}-model-1",
            provider=self._name,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )

    def stream_generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Generator[str, None, None]:
        yield "ok"

    def translate_tools(self, friday_tools: list[dict]) -> list[dict]:
        return friday_tools

    def parse_tool_calls(self, response: Any) -> list[dict]:
        return []

    def get_available_models(self) -> list[dict[str, Any]]:
        return [{"id": m, "name": m} for m in self._capabilities.supported_models]

    def get_health(self) -> ProviderHealth:
        return ProviderHealth(
            status=ProviderStatus.OPERATIONAL,
            latency_ms=10.0,
            success_rate=1.0,
            error_rate=0.0,
        )


# Strategy for provider-name tokens (lowercase identifiers).
_name_token = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
    min_size=1,
    max_size=12,
)

# Strategy for model-name tokens.
_model_token = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-._",
    min_size=1,
    max_size=20,
)


class TestProviderSelectionStateUpdateProperty:
    """Property 26: Provider Selection State Update.

    **Validates: Requirements 7.2**
    """

    @settings(max_examples=200, deadline=None)
    @given(
        provider_names=st.lists(_name_token, min_size=1, max_size=6, unique=True),
        model=_model_token,
        data=st.data(),
    )
    def test_set_active_updates_selection_state(
        self,
        provider_names: list[str],
        model: str,
        data: st.DataObject,
    ) -> None:
        # Fresh registry per example (avoids singleton state leakage).
        registry = Provider_Registry()

        # Register a fake adapter for each generated provider name.
        for name in provider_names:
            error = registry.register(FakeAdapter(name, models=[f"{name}-default"]))
            assert error is None

        # Choose one registered provider to make active, plus an explicit model.
        chosen = data.draw(st.sampled_from(provider_names))

        assert registry.set_active(chosen, model) is True

        # Property 26: state getters reflect the selection exactly.
        assert registry.get_active_provider_name() == chosen
        assert registry.get_active_model() == model

        active_adapter = registry.get_active_adapter()
        assert active_adapter is not None
        assert active_adapter.provider_name == chosen
        # The active adapter is the exact instance registered under that name.
        assert active_adapter is registry.get_adapter(chosen)

    @settings(max_examples=200, deadline=None)
    @given(
        provider_names=st.lists(_name_token, min_size=2, max_size=6, unique=True),
        model_a=_model_token,
        model_b=_model_token,
        data=st.data(),
    )
    def test_reselecting_updates_to_latest_selection(
        self,
        provider_names: list[str],
        model_a: str,
        model_b: str,
        data: st.DataObject,
    ) -> None:
        # Successive selections always reflect the most recent set_active call.
        registry = Provider_Registry()
        for name in provider_names:
            assert registry.register(FakeAdapter(name, models=[f"{name}-default"])) is None

        first = data.draw(st.sampled_from(provider_names))
        second = data.draw(st.sampled_from([n for n in provider_names if n != first]))

        registry.set_active(first, model_a)
        registry.set_active(second, model_b)

        assert registry.get_active_provider_name() == second
        assert registry.get_active_model() == model_b
        active = registry.get_active_adapter()
        assert active is not None
        assert active.provider_name == second

    @settings(max_examples=100, deadline=None)
    @given(
        provider_names=st.lists(_name_token, min_size=1, max_size=6, unique=True),
        unregistered=_name_token,
        data=st.data(),
    )
    def test_set_active_unregistered_provider_leaves_state_unchanged(
        self,
        provider_names: list[str],
        unregistered: str,
        data: st.DataObject,
    ) -> None:
        # Selecting a provider that is not registered must fail and not alter
        # the previously established valid selection.
        registry = Provider_Registry()
        for name in provider_names:
            assert registry.register(FakeAdapter(name, models=[f"{name}-default"])) is None

        chosen = data.draw(st.sampled_from(provider_names))
        registry.set_active(chosen, "chosen-model")

        # Ensure the unregistered name is genuinely not registered.
        if unregistered not in provider_names:
            assert registry.set_active(unregistered, "x") is False
            # State remains the last valid selection.
            assert registry.get_active_provider_name() == chosen
            assert registry.get_active_model() == "chosen-model"
