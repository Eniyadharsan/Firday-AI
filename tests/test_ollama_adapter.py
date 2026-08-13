"""Tests for the Ollama provider adapter.

Covers:
- Task 8.3: Property test - Ollama Tool Capability Check (Property 30)
- Task 8.4: Property test - Message Format Translation (Ollama) (Property 4)
- Task 8.5: Unit tests for Ollama_Adapter

All tests avoid real network calls by monkeypatching the module-level
`requests` used by the adapter.
"""

from __future__ import annotations

from unittest import mock

import requests
from hypothesis import given
from hypothesis import strategies as st

from friday.modules.providers.adapters import ollama_adapter as ollama_mod
from friday.modules.providers.adapters.ollama_adapter import (
    CONNECTION_TIMEOUT,
    Ollama_Adapter,
)
from friday.modules.providers.models import ProviderStatus
from tests._adapter_fakes import FakeKeyStore, FakeResponse


# Model families the adapter knows support tool calling.
_TOOL_CAPABLE_SUBSTRINGS = ["llama3", "llama-3", "mistral", "mixtral", "qwen", "command-r"]


def make_adapter() -> Ollama_Adapter:
    return Ollama_Adapter(FakeKeyStore({"ollama": "http://localhost:11434"}))


# --------------------------------------------------------------------------- #
# Task 8.3 - Property 30: Ollama Tool Capability Check
# --------------------------------------------------------------------------- #
class TestOllamaToolCapabilityCheckProperty:
    """Property 30: Ollama Tool Capability Check.

    The adapter checks model capabilities (via _model_supports_tools) before
    attempting tool calls. That check must be deterministic and must exactly
    reflect the known tool-capable model families.

    Validates: Requirements 12.5
    """

    @given(model_name=st.text(max_size=60))
    def test_capability_check_is_deterministic_and_correct(self, model_name):
        adapter = make_adapter()
        result = adapter._model_supports_tools(model_name)

        # Result is always a boolean and is stable across calls (deterministic).
        assert isinstance(result, bool)
        assert result == adapter._model_supports_tools(model_name)

        # It is True exactly when the name matches a known tool-capable family.
        expected = any(s in model_name.lower() for s in _TOOL_CAPABLE_SUBSTRINGS)
        assert result == expected

    @given(
        model_names=st.lists(
            st.sampled_from(
                [
                    "llama3.2",
                    "llama-3-8b",
                    "mistral",
                    "mixtral:8x7b",
                    "qwen2.5",
                    "command-r",
                    "phi3",
                    "gemma2",
                    "tinyllama",
                    "codellama",
                ]
            ),
            min_size=1,
            max_size=8,
            unique=True,
        )
    )
    def test_available_models_report_matches_capability_check(self, model_names):
        """get_available_models() reports supports_tool_calling consistent with
        the capability check that gates tool usage."""
        adapter = make_adapter()

        payload = {"models": [{"name": name, "details": {}} for name in model_names]}
        # Use a context-manager patch (not a function-scoped fixture) so the
        # stub is applied per generated example.
        with mock.patch.object(
            ollama_mod.requests, "get", lambda *a, **k: FakeResponse(200, payload)
        ):
            models = adapter.get_available_models()

        assert len(models) == len(model_names)
        for entry in models:
            assert entry["supports_tool_calling"] == adapter._model_supports_tools(
                entry["id"]
            )


# --------------------------------------------------------------------------- #
# Task 8.4 - Property 4: Message Format Translation (Ollama)
# --------------------------------------------------------------------------- #
_role = st.sampled_from(["system", "user", "assistant", "tool", "function"])
_message = st.fixed_dictionaries({"role": _role, "content": st.text(max_size=200)})
_messages = st.lists(_message, min_size=1, max_size=12)


class TestOllamaMessageTranslationProperty:
    """Property 4: Message Format Translation (Ollama).

    Validates: Requirements 5.3
    """

    @given(messages=_messages)
    def test_translation_produces_valid_ollama_messages(self, messages):
        adapter = make_adapter()
        translated = adapter._translate_messages(messages)

        assert len(translated) == len(messages)
        for produced, original in zip(translated, messages):
            # Every message has role + content and is a valid chat message.
            assert "role" in produced
            assert "content" in produced
            assert isinstance(produced["content"], str)

            # 'function' role is mapped to 'tool'; other roles are preserved.
            expected_role = "tool" if original["role"] == "function" else original["role"]
            assert produced["role"] == expected_role
            assert produced["content"] == original["content"]


# --------------------------------------------------------------------------- #
# Task 8.5 - Unit tests for Ollama_Adapter
# --------------------------------------------------------------------------- #
class TestOllamaServerReachability:
    def test_is_configured_true_when_server_responds(self, monkeypatch):
        adapter = make_adapter()
        monkeypatch.setattr(
            ollama_mod.requests, "get", lambda *a, **k: FakeResponse(200, {"models": []})
        )
        assert adapter.is_configured() is True

    def test_is_configured_uses_three_second_timeout(self, monkeypatch):
        adapter = make_adapter()
        captured = {}

        def fake_get(url, timeout=None, **kwargs):
            captured["timeout"] = timeout
            return FakeResponse(200, {"models": []})

        monkeypatch.setattr(ollama_mod.requests, "get", fake_get)
        adapter.is_configured()
        # Requirement 5.5: 3-second timeout for unreachable server detection.
        assert captured["timeout"] == CONNECTION_TIMEOUT == 3.0

    def test_is_configured_false_on_connection_error(self, monkeypatch):
        adapter = make_adapter()

        def raise_conn(*a, **k):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(ollama_mod.requests, "get", raise_conn)
        assert adapter.is_configured() is False

    def test_is_configured_false_on_timeout(self, monkeypatch):
        adapter = make_adapter()

        def raise_timeout(*a, **k):
            raise requests.Timeout("slow")

        monkeypatch.setattr(ollama_mod.requests, "get", raise_timeout)
        assert adapter.is_configured() is False


class TestOllamaValidateConfig:
    def test_validate_config_timeout(self, monkeypatch):
        adapter = make_adapter()

        def raise_timeout(*a, **k):
            raise requests.Timeout("slow")

        monkeypatch.setattr(ollama_mod.requests, "get", raise_timeout)
        ok, err = adapter.validate_config()
        assert ok is False
        assert err and "timed out" in err.lower()

    def test_validate_config_connection_error(self, monkeypatch):
        adapter = make_adapter()

        def raise_conn(*a, **k):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(ollama_mod.requests, "get", raise_conn)
        ok, err = adapter.validate_config()
        assert ok is False
        assert err and "connect" in err.lower()

    def test_validate_config_ok_but_no_models(self, monkeypatch):
        adapter = make_adapter()
        monkeypatch.setattr(
            ollama_mod.requests, "get", lambda *a, **k: FakeResponse(200, {"models": []})
        )
        ok, err = adapter.validate_config()
        assert ok is True
        assert err and "no models" in err.lower()


class TestOllamaModelListing:
    def test_get_available_models_parses_server_response(self, monkeypatch):
        adapter = make_adapter()
        payload = {
            "models": [
                {"name": "llama3.2", "details": {}},
                {"name": "phi3", "details": {}},
            ]
        }
        monkeypatch.setattr(
            ollama_mod.requests, "get", lambda *a, **k: FakeResponse(200, payload)
        )
        models = adapter.get_available_models()
        ids = [m["id"] for m in models]
        assert ids == ["llama3.2", "phi3"]
        for m in models:
            assert m["provider"] == "ollama"
            assert "context_window" in m
            assert m["input_cost_per_1k"] is None  # local, no cost

    def test_get_available_models_empty_on_connection_error(self, monkeypatch):
        adapter = make_adapter()

        def raise_conn(*a, **k):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(ollama_mod.requests, "get", raise_conn)
        assert adapter.get_available_models() == []


class TestOllamaHealthStatus:
    def test_unavailable_when_server_unreachable(self, monkeypatch):
        adapter = make_adapter()

        def raise_conn(*a, **k):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(ollama_mod.requests, "get", raise_conn)
        health = adapter.get_health()
        assert health.status == ProviderStatus.UNAVAILABLE

    def test_operational_when_server_reachable(self, monkeypatch):
        adapter = make_adapter()
        monkeypatch.setattr(
            ollama_mod.requests, "get", lambda *a, **k: FakeResponse(200, {"models": []})
        )
        health = adapter.get_health()
        assert health.status == ProviderStatus.OPERATIONAL
