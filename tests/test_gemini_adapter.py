"""Tests for the Google Gemini provider adapter.

Covers:
- Task 7.3: Property test - Message Format Translation (Gemini) (Property 4)
- Task 7.4: Unit tests for Gemini_Adapter

All tests avoid real network/API calls by injecting a fake genai module.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from friday.modules.providers.adapters.gemini_adapter import (
    DEFAULT_MODEL,
    GEMINI_MODELS,
    Gemini_Adapter,
)
from tests._adapter_fakes import (
    FakeGenai,
    FakeKeyStore,
    FakePart,
    make_gemini_response,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def make_adapter(configured: bool = True, genai=None) -> Gemini_Adapter:
    keys = {"gemini": "test-google-key"} if configured else {}
    adapter = Gemini_Adapter(FakeKeyStore(keys))
    if genai is not None:
        # Inject fake genai so _get_genai() returns it without importing/config.
        adapter._genai = genai
    return adapter


# Message strategy for Property 4: roles that map directly (no tool_calls path).
_simple_role = st.sampled_from(["user", "assistant", "system"])
_message = st.fixed_dictionaries(
    {"role": _simple_role, "content": st.text(max_size=200)}
)
_messages = st.lists(_message, min_size=1, max_size=12)


# --------------------------------------------------------------------------- #
# Task 7.3 - Property 4: Message Format Translation (Gemini)
# --------------------------------------------------------------------------- #
class TestGeminiMessageTranslationProperty:
    """Property 4: Message Format Translation (Gemini).

    Validates: Requirements 4.3
    """

    @given(messages=_messages)
    def test_roles_mapped_and_system_extracted(self, messages):
        adapter = make_adapter()
        contents, system_instruction = adapter._translate_messages(messages)

        non_system = [m for m in messages if m["role"] != "system"]
        system_msgs = [m for m in messages if m["role"] == "system"]

        # Every non-system message produces exactly one content entry, in order.
        assert len(contents) == len(non_system)

        for produced, original in zip(contents, non_system):
            # Roles mapped: user -> user, assistant -> model
            expected_role = "model" if original["role"] == "assistant" else "user"
            assert produced["role"] == expected_role
            assert produced["role"] in ("user", "model")

            # Content becomes parts with a text field.
            assert "parts" in produced
            assert isinstance(produced["parts"], list)
            assert produced["parts"] == [{"text": original["content"]}]

        # System messages are extracted as system_instruction (last one wins),
        # never emitted as content entries.
        if system_msgs:
            assert system_instruction == system_msgs[-1]["content"]
        else:
            assert system_instruction is None

    @given(messages=_messages)
    def test_output_is_structurally_valid_gemini_format(self, messages):
        """Every produced content is a valid Gemini content dict."""
        adapter = make_adapter()
        contents, _ = adapter._translate_messages(messages)

        for content in contents:
            assert set(content.keys()) == {"role", "parts"}
            assert content["role"] in ("user", "model")
            assert isinstance(content["parts"], list)
            assert len(content["parts"]) >= 1
            for part in content["parts"]:
                assert isinstance(part, dict)


# --------------------------------------------------------------------------- #
# Task 7.4 - Unit tests for Gemini_Adapter
# --------------------------------------------------------------------------- #
class TestGeminiConfigValidation:
    def test_provider_name(self):
        assert make_adapter().provider_name == "gemini"

    def test_is_configured_true_when_key_present(self):
        assert make_adapter(configured=True).is_configured() is True

    def test_is_configured_false_when_no_key(self):
        assert make_adapter(configured=False).is_configured() is False

    def test_validate_config_without_key_returns_error(self):
        adapter = make_adapter(configured=False)
        ok, err = adapter.validate_config()
        assert ok is False
        assert err and "not configured" in err.lower()

    def test_validate_config_success_with_fake_genai(self):
        genai = FakeGenai(models=["models/gemini-flash-latest", "models/gemini-2.5-pro"])
        adapter = make_adapter(configured=True, genai=genai)
        ok, err = adapter.validate_config()
        assert ok is True
        assert err is None

    def test_validate_config_reports_api_error(self):
        class BoomGenai(FakeGenai):
            def list_models(self):
                raise RuntimeError("invalid api key")

        adapter = make_adapter(configured=True, genai=BoomGenai())
        ok, err = adapter.validate_config()
        assert ok is False
        assert err

    def test_capabilities_expose_current_models(self):
        caps = make_adapter().capabilities
        assert caps.supports_tool_calling is True
        assert DEFAULT_MODEL == "gemini-flash-latest"
        assert DEFAULT_MODEL in caps.supported_models
        # Current (non-1.5) model names are advertised.
        for expected in [
            "gemini-flash-latest",
            "gemini-pro-latest",
            "gemini-2.0-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ]:
            assert expected in GEMINI_MODELS


class TestGeminiFunctionDeclarationTranslation:
    def test_full_openai_format(self):
        adapter = make_adapter()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                    },
                },
            }
        ]
        decls = adapter.translate_tools(tools)
        assert len(decls) == 1
        decl = decls[0]
        assert decl["name"] == "get_weather"
        assert decl["description"] == "Get the weather"
        assert decl["parameters"]["type"] == "object"
        assert "city" in decl["parameters"]["properties"]

    def test_simplified_format(self):
        adapter = make_adapter()
        tools = [{"name": "ping", "description": "ping tool"}]
        decls = adapter.translate_tools(tools)
        assert len(decls) == 1
        assert decls[0]["name"] == "ping"
        # Parameters defaulted to a valid object schema.
        assert decls[0]["parameters"]["type"] == "object"
        assert decls[0]["parameters"]["properties"] == {}

    def test_invalid_and_empty_inputs(self):
        adapter = make_adapter()
        assert adapter.translate_tools([]) == []
        assert adapter.translate_tools(None) == []
        # None entries and non-dict entries are skipped, missing-name dropped.
        assert adapter.translate_tools([None, 42, {"description": "no name"}]) == []


class TestGeminiParseToolCalls:
    def test_parse_from_response_object(self):
        adapter = make_adapter()
        fc = SimpleNamespace(name="get_weather", args={"city": "NYC"})
        response = make_gemini_response(text="", function_calls=[fc])
        calls = adapter.parse_tool_calls(response)
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "get_weather"
        assert calls[0]["function"]["arguments"] == {"city": "NYC"}
        assert "id" in calls[0]

    def test_parse_none_returns_empty(self):
        assert make_adapter().parse_tool_calls(None) == []

    def test_parse_response_without_function_calls(self):
        adapter = make_adapter()
        response = make_gemini_response(text="just text", function_calls=[])
        assert adapter.parse_tool_calls(response) == []


class TestGeminiGenerate:
    def test_generate_returns_unified_response(self):
        genai = FakeGenai(response=make_gemini_response(text="Hello world"))
        adapter = make_adapter(configured=True, genai=genai)
        response = adapter.generate([{"role": "user", "content": "hi"}])
        assert response.content == "Hello world"
        assert response.provider == "gemini"
        assert response.model == DEFAULT_MODEL
        assert set(["prompt_tokens", "completion_tokens", "total_tokens"]).issubset(
            response.usage.keys()
        )
        assert response.usage["total_tokens"] == 10

    def test_generate_parses_function_calls(self):
        fc = SimpleNamespace(name="lookup", args={"q": "term"})
        genai = FakeGenai(
            response=make_gemini_response(
                text="", function_calls=[fc], finish_reason="TOOL_USE"
            )
        )
        adapter = make_adapter(configured=True, genai=genai)
        response = adapter.generate([{"role": "user", "content": "call tool"}])
        assert response.tool_calls is not None
        assert response.tool_calls[0]["function"]["name"] == "lookup"
        assert response.finish_reason == "tool_calls"
