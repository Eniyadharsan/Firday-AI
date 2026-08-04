"""Integration and property tests for provider switching.

This module covers the behavior of switching between AI providers during an
active conversation and the failover path when an active provider errors.

Feature: multi-provider-ai

Tasks covered:
- Task 19.2: Integration tests for provider switching
    * Switching between providers mid-conversation
    * Conversation history preservation across switches
    * Failover scenario (active provider errors -> backup handles it)
    Validates: Requirements 13.3, 14.1, 14.2, 9.2
- Task 19.3: Property test - Provider Selection State Update (Property 26)
    For any set_active(provider[, model]) on a registered provider, the
    registry's active provider/model reflects the selection.
    Validates: Requirement 7.2

No real API calls are made. All provider behavior is simulated with in-memory
fake adapters that record what they receive.
"""

from __future__ import annotations

import json
from typing import Any, Generator, Optional

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from friday.modules.providers.base import Provider_Adapter
from friday.modules.providers.registry import Provider_Registry
from friday.modules.providers.engine import Unified_AI_Engine
from friday.modules.providers.failover import Failover_Controller
from friday.modules.providers.models import (
    GenerateResponse,
    ProviderCapabilities,
    ProviderError,
    ProviderHealth,
    ProviderStatus,
)


# ---------------------------------------------------------------------------
# Test doubles: fake provider adapters (NO real API calls)
# ---------------------------------------------------------------------------

class FakeAdapter(Provider_Adapter):
    """Deterministic fake provider adapter for switching/failover testing.

    Records the messages it receives on generate() so tests can assert on what
    the engine actually sent to the provider. Returns a deterministic
    GenerateResponse tagged with this adapter's provider/model.
    """

    def __init__(
        self,
        name: str = "fake",
        model: str = "fake-model",
        max_context_window: int = 8192,
        supports_tool_calling: bool = True,
        response_content: str = "response",
    ) -> None:
        self._name = name
        self._model = model
        self._max_context = max_context_window
        self._supports_tools = supports_tool_calling
        self._response_content = response_content
        # Captured state for assertions
        self.last_messages: Optional[list[dict]] = None
        self.generate_calls: int = 0

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_streaming=True,
            supports_tool_calling=self._supports_tools,
            supports_vision=False,
            max_context_window=self._max_context,
            supported_models=[self._model],
        )

    def is_configured(self) -> bool:
        return True

    def validate_config(self) -> tuple[bool, Optional[str]]:
        return (True, None)

    def generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> GenerateResponse:
        self.last_messages = messages
        self.generate_calls += 1
        return GenerateResponse(
            content=self._response_content,
            model=model or self._model,
            provider=self._name,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            tool_calls=None,
            finish_reason="stop",
        )

    def stream_generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Generator[Any, None, None]:
        yield self._response_content

    def translate_tools(self, friday_tools: list[dict]) -> list[dict]:
        return friday_tools

    def parse_tool_calls(self, response: Any) -> list[dict]:
        return []

    def get_available_models(self) -> list[dict[str, Any]]:
        return [
            {
                "id": self._model,
                "name": self._model,
                "context_window": self._max_context,
                "supports_streaming": True,
                "supports_tool_calling": self._supports_tools,
                "supports_vision": False,
            }
        ]

    def get_health(self) -> ProviderHealth:
        return ProviderHealth(
            status=ProviderStatus.OPERATIONAL,
            latency_ms=1.0,
            success_rate=1.0,
            error_rate=0.0,
        )


class FailingAdapter(FakeAdapter):
    """Fake adapter whose generate() always raises a ProviderError.

    Used to simulate an active provider failing so the Failover_Controller
    routes the request to a backup provider.
    """

    def generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> GenerateResponse:
        self.generate_calls += 1
        raise ProviderError(
            provider=self._name,
            error_type="server",
            message="simulated provider failure",
            is_retryable=True,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_engine(
    adapters: list[FakeAdapter],
    active: Optional[str] = None,
    failover_controller: Optional[Failover_Controller] = None,
) -> tuple[Unified_AI_Engine, Provider_Registry]:
    """Build a fresh engine backed by a fresh (non-singleton) registry."""
    registry = Provider_Registry()
    for adapter in adapters:
        error = registry.register(adapter)
        assert error is None, f"adapter registration failed: {error}"
    if active is not None:
        assert registry.set_active(active)
    engine = Unified_AI_Engine(registry, failover_controller=failover_controller)
    return engine, registry


# ===========================================================================
# Task 19.2: Integration tests for provider switching
# ===========================================================================

class TestProviderSwitchingMidConversation:
    """Switching providers mid-conversation with history preservation.

    Validates: Requirements 13.3, 14.1, 14.2
    """

    def test_switch_between_providers_mid_conversation(self):
        """Two providers can alternate across turns of one conversation.

        Each turn is served by whichever provider is active, and the assistant
        message stored in history is tagged with the provider that produced it.
        (Requirements 14.1)
        """
        adapter_a = FakeAdapter(name="prov_a", model="a-model", response_content="reply-a")
        adapter_b = FakeAdapter(name="prov_b", model="b-model", response_content="reply-b")
        engine, registry = build_engine([adapter_a, adapter_b], active="prov_a")
        session = "conv-1"

        # Turn 1 on provider A
        r1 = engine.generate(
            messages=[{"role": "user", "content": "turn one"}],
            user_id="u1",
            session_id=session,
        )
        assert r1.provider == "prov_a"

        # Switch to provider B for turn 2
        registry.set_active("prov_b")
        r2 = engine.generate(
            messages=[{"role": "user", "content": "turn two"}],
            user_id="u1",
            session_id=session,
        )
        assert r2.provider == "prov_b"

        # Switch back to provider A for turn 3
        registry.set_active("prov_a")
        r3 = engine.generate(
            messages=[{"role": "user", "content": "turn three"}],
            user_id="u1",
            session_id=session,
        )
        assert r3.provider == "prov_a"

        # Assistant messages are tagged with the producing provider (Req 14.1)
        history = engine.conversation_history.get_history(session)
        assistant_msgs = [m for m in history if m.role == "assistant"]
        assert [m.provider for m in assistant_msgs] == ["prov_a", "prov_b", "prov_a"]

    def test_conversation_history_preserved_and_continuous_across_switches(self):
        """History stays intact and ordered across provider switches. (Req 13.3)"""
        adapter_a = FakeAdapter(name="prov_a", model="a-model", response_content="ans-a")
        adapter_b = FakeAdapter(name="prov_b", model="b-model", response_content="ans-b")
        engine, registry = build_engine([adapter_a, adapter_b], active="prov_a")
        session = "conv-2"

        user_turns = ["first", "second", "third", "fourth"]
        for i, turn in enumerate(user_turns):
            # Alternate providers on each turn
            registry.set_active("prov_b" if i % 2 == 1 else "prov_a")
            engine.generate(
                messages=[{"role": "user", "content": turn}],
                user_id="u1",
                session_id=session,
            )

        history = engine.conversation_history.get_history(session)

        # All user messages preserved in original order (continuity)
        recorded_user = [m.content for m in history if m.role == "user"]
        assert recorded_user == user_turns

        # One assistant reply per user turn
        recorded_assistant = [m for m in history if m.role == "assistant"]
        assert len(recorded_assistant) == len(user_turns)

        # The conversation interleaves user/assistant in order (continuous)
        roles = [m.role for m in history]
        expected_roles = ["user", "assistant"] * len(user_turns)
        assert roles == expected_roles

    def test_new_provider_receives_prior_history(self):
        """After a switch, the new provider's messages include prior history.

        Validates: Requirements 14.2
        """
        adapter_a = FakeAdapter(name="prov_a", model="a-model", response_content="reply-a")
        adapter_b = FakeAdapter(name="prov_b", model="b-model", response_content="reply-b")
        engine, registry = build_engine([adapter_a, adapter_b], active="prov_a")
        session = "conv-3"

        # Turn 1 on provider A
        engine.generate(
            messages=[{"role": "user", "content": "hello from turn one"}],
            user_id="u1",
            session_id=session,
        )

        # Switch to provider B and take turn 2
        registry.set_active("prov_b")
        engine.generate(
            messages=[{"role": "user", "content": "now on provider b"}],
            user_id="u1",
            session_id=session,
        )

        # Provider B received the prior user message, prior assistant reply,
        # and the new user message.
        contents = [m.get("content", "") for m in adapter_b.last_messages]
        assert "hello from turn one" in contents
        assert "reply-a" in contents
        assert "now on provider b" in contents


class TestFailoverIntegration:
    """Failover: active provider errors and a backup handles the request.

    Validates: Requirements 9.2, 13.3
    """

    def test_backup_handles_request_when_active_provider_fails(self):
        """When the active provider errors, the backup serves the request.

        Validates: Requirements 9.2
        """
        failing = FailingAdapter(name="primary", model="primary-model")
        backup = FakeAdapter(name="backup", model="backup-model", response_content="backup-reply")

        # Build registry/engine with the failover controller wired to the registry.
        registry = Provider_Registry()
        assert registry.register(failing) is None
        assert registry.register(backup) is None
        assert registry.set_active("primary")

        failover = Failover_Controller(registry)
        failover.set_backup_order(["backup"])
        engine = Unified_AI_Engine(registry, failover_controller=failover)

        try:
            response = engine.generate(
                messages=[{"role": "user", "content": "please answer"}],
                user_id="u1",
                session_id="conv-failover",
            )

            # The backup produced the response
            assert response.provider == "backup"
            assert response.content == "backup-reply"
            # The failing provider was actually attempted
            assert failing.generate_calls == 1
            assert backup.generate_calls == 1
            # Registry now reflects the backup as active (Property 11 / Req 9.2)
            assert registry.get_active_provider_name() == "backup"
            assert failover.is_in_failover() is True
        finally:
            failover.shutdown()

    def test_history_intact_after_failover(self):
        """Conversation history stays intact when a failover occurs mid-turn.

        Validates: Requirements 13.3, 9.2
        """
        adapter_a = FakeAdapter(name="prov_a", model="a-model", response_content="reply-a")
        failing = FailingAdapter(name="prov_b", model="b-model")
        backup = FakeAdapter(name="prov_c", model="c-model", response_content="reply-c")

        registry = Provider_Registry()
        assert registry.register(adapter_a) is None
        assert registry.register(failing) is None
        assert registry.register(backup) is None
        assert registry.set_active("prov_a")

        failover = Failover_Controller(registry)
        failover.set_backup_order(["prov_c"])
        engine = Unified_AI_Engine(registry, failover_controller=failover)
        session = "conv-failover-history"

        try:
            # Turn 1 succeeds on provider A
            engine.generate(
                messages=[{"role": "user", "content": "turn one"}],
                user_id="u1",
                session_id=session,
            )

            # Switch to the failing provider; its failure triggers failover to backup
            registry.set_active("prov_b")
            r2 = engine.generate(
                messages=[{"role": "user", "content": "turn two"}],
                user_id="u1",
                session_id=session,
            )
            assert r2.provider == "prov_c"  # backup handled it

            history = engine.conversation_history.get_history(session)

            # Both user turns preserved in order
            recorded_user = [m.content for m in history if m.role == "user"]
            assert recorded_user == ["turn one", "turn two"]

            # Two assistant replies: from prov_a then the failover backup prov_c
            assistant_msgs = [m for m in history if m.role == "assistant"]
            assert [m.provider for m in assistant_msgs] == ["prov_a", "prov_c"]

            # The backup received the prior history (Req 14.2 continuity through failover)
            contents = [m.get("content", "") for m in backup.last_messages]
            assert "turn one" in contents
            assert "reply-a" in contents
            assert "turn two" in contents
        finally:
            failover.shutdown()


# ===========================================================================
# Task 19.3: Property 26 - Provider Selection State Update
# ===========================================================================

# Provider names: identifier-like, unique, valid non-empty strings.
provider_name_strategy = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),  # a-z
    min_size=1,
    max_size=12,
)

# Model names: any non-empty printable string.
model_name_strategy = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=30,
)


class TestProviderSelectionStateUpdate:
    """Property 26: Provider Selection State Update.

    Validates: Requirements 7.2
    """

    @settings(max_examples=100, deadline=None)
    @given(
        provider_names=st.lists(
            provider_name_strategy, min_size=1, max_size=5, unique=True
        ),
        selection_index=st.integers(min_value=0, max_value=10_000),
        use_explicit_model=st.booleans(),
        explicit_model=model_name_strategy,
    )
    def test_set_active_reflects_selection(
        self, provider_names, selection_index, use_explicit_model, explicit_model
    ):
        """Feature: multi-provider-ai, Property 26: Provider Selection State Update.

        For any set_active() call on a registered provider (with or without an
        explicit model), the registry's active provider and model reflect the
        selection exactly.
        """
        # Fresh registry per example (reset selection state each time).
        registry = Provider_Registry()
        for name in provider_names:
            adapter = FakeAdapter(name=name, model=f"{name}-model")
            assert registry.register(adapter) is None

        chosen = provider_names[selection_index % len(provider_names)]

        if use_explicit_model:
            ok = registry.set_active(chosen, explicit_model)
            assert ok is True
            assert registry.get_active_provider_name() == chosen
            assert registry.get_active_model() == explicit_model
        else:
            ok = registry.set_active(chosen)
            assert ok is True
            assert registry.get_active_provider_name() == chosen
            # With no explicit model, the provider's first supported model is used.
            assert registry.get_active_model() == f"{chosen}-model"

        # The active adapter resolves to the selected provider.
        active_adapter = registry.get_active_adapter()
        assert active_adapter is not None
        assert active_adapter.provider_name == chosen

    @settings(max_examples=50, deadline=None)
    @given(provider_name=provider_name_strategy)
    def test_set_active_unregistered_provider_returns_false(self, provider_name):
        """Feature: multi-provider-ai, Property 26: Provider Selection State Update.

        set_active() on an unregistered provider returns False and does not
        change the active selection.
        """
        registry = Provider_Registry()
        registry.register(FakeAdapter(name="only", model="only-model"))
        registry.set_active("only")

        # Any name that is not registered must be rejected.
        target = provider_name if provider_name != "only" else "only_missing"
        ok = registry.set_active(target)

        assert ok is False
        assert registry.get_active_provider_name() == "only"
