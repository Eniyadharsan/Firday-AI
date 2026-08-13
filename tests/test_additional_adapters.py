"""Unit tests for the additional provider adapters.

Covers Task 10.5: DeepSeek, Grok, OpenRouter, and Cerebras adapters.
Tests configuration validation and basic generation response shape.

All tests avoid real network/API calls by injecting fake OpenAI-compatible
clients / requests sessions, or monkeypatching module-level `requests`.
"""

from __future__ import annotations

import requests
import pytest

from friday.modules.providers.adapters.cerebras_adapter import Cerebras_Adapter
from friday.modules.providers.adapters.deepseek_adapter import DeepSeek_Adapter
from friday.modules.providers.adapters.grok_adapter import Grok_Adapter
from friday.modules.providers.adapters.openrouter_adapter import OpenRouter_Adapter
from tests._adapter_fakes import (
    FakeKeyStore,
    FakeOpenAIClient,
    FakeResponse,
    FakeSession,
    make_openai_response,
)


# --------------------------------------------------------------------------- #
# OpenAI-compatible adapters: DeepSeek, Grok, OpenRouter
# --------------------------------------------------------------------------- #
# (adapter_cls, provider_name, key_name, default_model_prefix)
OPENAI_COMPATIBLE = [
    (DeepSeek_Adapter, "deepseek", "deepseek", "deepseek-chat"),
    (Grok_Adapter, "grok", "grok", "grok-beta"),
    (OpenRouter_Adapter, "openrouter", "openrouter", "openai/gpt-4o-mini"),
]


@pytest.mark.parametrize(
    "adapter_cls,provider_name,key_name,default_model", OPENAI_COMPATIBLE
)
class TestOpenAICompatibleAdapters:
    def test_provider_name(self, adapter_cls, provider_name, key_name, default_model):
        adapter = adapter_cls(FakeKeyStore({key_name: "test-key"}))
        assert adapter.provider_name == provider_name

    def test_is_configured_reflects_key_presence(
        self, adapter_cls, provider_name, key_name, default_model
    ):
        assert adapter_cls(FakeKeyStore({key_name: "k"})).is_configured() is True
        assert adapter_cls(FakeKeyStore({})).is_configured() is False

    def test_validate_config_without_key(
        self, adapter_cls, provider_name, key_name, default_model
    ):
        ok, err = adapter_cls(FakeKeyStore({})).validate_config()
        assert ok is False
        assert err and "not configured" in err.lower()

    def test_validate_config_success_with_fake_client(
        self, adapter_cls, provider_name, key_name, default_model
    ):
        adapter = adapter_cls(FakeKeyStore({key_name: "test-key"}))
        adapter._client = FakeOpenAIClient(models=[{"id": "m1"}])
        ok, err = adapter.validate_config()
        assert ok is True
        assert err is None

    def test_generate_returns_unified_response(
        self, adapter_cls, provider_name, key_name, default_model
    ):
        adapter = adapter_cls(FakeKeyStore({key_name: "test-key"}))
        adapter._client = FakeOpenAIClient(
            response=make_openai_response(content="Answer", finish_reason="stop")
        )
        response = adapter.generate([{"role": "user", "content": "hi"}])

        assert response.content == "Answer"
        assert response.provider == provider_name
        assert response.model == default_model
        assert response.finish_reason == "stop"
        assert set(["prompt_tokens", "completion_tokens", "total_tokens"]).issubset(
            response.usage.keys()
        )
        assert response.usage["total_tokens"] == 8

    def test_generate_respects_explicit_model(
        self, adapter_cls, provider_name, key_name, default_model
    ):
        adapter = adapter_cls(FakeKeyStore({key_name: "test-key"}))
        fake_client = FakeOpenAIClient(response=make_openai_response())
        adapter._client = fake_client
        adapter.generate([{"role": "user", "content": "hi"}], model="custom-model")
        # The requested model is forwarded to the API call.
        assert fake_client.chat.completions.calls[0]["model"] == "custom-model"

    def test_translate_tools_pass_through(
        self, adapter_cls, provider_name, key_name, default_model
    ):
        adapter = adapter_cls(FakeKeyStore({key_name: "test-key"}))
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "do_it",
                    "description": "does it",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        translated = adapter.translate_tools(tools)
        assert len(translated) == 1
        assert translated[0]["type"] == "function"
        assert translated[0]["function"]["name"] == "do_it"


# --------------------------------------------------------------------------- #
# OpenRouter model catalog (Task 10.5: "Test OpenRouter model catalog")
# --------------------------------------------------------------------------- #
class TestOpenRouterModelCatalog:
    def test_fetches_and_maps_models_from_api(self, monkeypatch):
        adapter = OpenRouter_Adapter(FakeKeyStore({"openrouter": "test-key"}))
        payload = {
            "data": [
                {
                    "id": "openai/gpt-4o",
                    "name": "GPT-4o",
                    "context_length": 128000,
                    "pricing": {"prompt": "0.000005", "completion": "0.000015"},
                },
                {
                    "id": "anthropic/claude-3-haiku",
                    "name": "Claude 3 Haiku",
                    "context_length": 200000,
                    "pricing": {"prompt": "0.0000003", "completion": "0.0000012"},
                },
            ]
        }
        # OpenRouter imports `requests` locally inside _fetch_models_from_api,
        # so patch the requests module directly.
        monkeypatch.setattr(
            requests, "get", lambda *a, **k: FakeResponse(200, payload)
        )
        models = adapter.get_available_models()
        ids = [m["id"] for m in models]
        assert "openai/gpt-4o" in ids
        assert "anthropic/claude-3-haiku" in ids
        for m in models:
            assert m["provider"] == "openrouter"
            assert "context_window" in m

    def test_falls_back_to_popular_models_on_api_failure(self, monkeypatch):
        adapter = OpenRouter_Adapter(FakeKeyStore({"openrouter": "test-key"}))

        def raise_conn(*a, **k):
            raise requests.ConnectionError("down")

        monkeypatch.setattr(requests, "get", raise_conn)
        models = adapter.get_available_models()
        # Falls back to the built-in popular model catalog.
        assert len(models) > 0


# --------------------------------------------------------------------------- #
# Cerebras adapter (requests.Session based)
# --------------------------------------------------------------------------- #
class TestCerebrasAdapter:
    def test_provider_name(self):
        adapter = Cerebras_Adapter(FakeKeyStore({"cerebras": "test-key"}))
        assert adapter.provider_name == "cerebras"

    def test_is_configured_reflects_key_presence(self):
        assert Cerebras_Adapter(FakeKeyStore({"cerebras": "k"})).is_configured() is True
        assert Cerebras_Adapter(FakeKeyStore({})).is_configured() is False

    def test_validate_config_without_key(self):
        ok, err = Cerebras_Adapter(FakeKeyStore({})).validate_config()
        assert ok is False
        assert err and "not configured" in err.lower()

    def test_validate_config_success(self):
        adapter = Cerebras_Adapter(FakeKeyStore({"cerebras": "test-key"}))
        adapter._session = FakeSession(get_response=FakeResponse(200, {"data": []}))
        ok, err = adapter.validate_config()
        assert ok is True
        assert err is None

    def test_validate_config_invalid_key(self):
        adapter = Cerebras_Adapter(FakeKeyStore({"cerebras": "bad-key"}))
        adapter._session = FakeSession(get_response=FakeResponse(401))
        ok, err = adapter.validate_config()
        assert ok is False
        assert err and "invalid" in err.lower()

    def test_generate_returns_unified_response(self):
        adapter = Cerebras_Adapter(FakeKeyStore({"cerebras": "test-key"}))
        response_json = {
            "choices": [
                {"message": {"content": "Cerebras reply"}, "finish_reason": "stop"}
            ],
            "usage": {
                "prompt_tokens": 2,
                "completion_tokens": 3,
                "total_tokens": 5,
            },
        }
        adapter._session = FakeSession(
            post_response=FakeResponse(200, response_json)
        )
        response = adapter.generate([{"role": "user", "content": "hi"}])
        assert response.content == "Cerebras reply"
        assert response.provider == "cerebras"
        assert response.finish_reason == "stop"
        assert response.usage["total_tokens"] == 5

    def test_default_model_used(self):
        adapter = Cerebras_Adapter(FakeKeyStore({"cerebras": "test-key"}))
        response_json = {
            "choices": [{"message": {"content": "x"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        adapter._session = FakeSession(post_response=FakeResponse(200, response_json))
        response = adapter.generate([{"role": "user", "content": "hi"}])
        assert response.model == "llama-4-scout-17b-16e-instruct"
