"""Property-based and unit tests for OpenAI_Adapter.

Covers spec tasks:
- 5.4 Property test: Message Format Translation (OpenAI) (Property 4)
- 5.5 Property test: Tool Definition Translation (OpenAI) (Property 5)
- 5.6 Unit tests for OpenAI_Adapter

No real network calls are made: a mock API_Key_Store stub is used and the
lazily-initialized client is monkeypatched with fakes returning canned objects.
"""

from __future__ import annotations

import string
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from hypothesis import given
from hypothesis import strategies as st

from friday.modules.providers.adapters.openai_adapter import OpenAI_Adapter
from friday.modules.providers.models import ProviderError


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class MockKeyStore:
    """Minimal stub of API_Key_Store used to avoid real key storage/network."""

    def __init__(self, keys: Optional[dict[str, str]] = None) -> None:
        self._keys = keys or {}

    def is_configured(self, provider: str) -> bool:
        return bool(self._keys.get(provider))

    def get_key(self, provider: str) -> Optional[str]:
        return self._keys.get(provider)


def make_adapter(configured: bool = True) -> OpenAI_Adapter:
    keys = {"openai": "sk-test-key"} if configured else {}
    return OpenAI_Adapter(MockKeyStore(keys))


# --------------------------------------------------------------------------- #
# Hypothesis strategies
# --------------------------------------------------------------------------- #
_IDENTIFIER = st.text(
    alphabet=string.ascii_letters + string.digits + "_",
    min_size=1,
    max_size=30,
)

_PROPERTIES = st.dictionaries(
    keys=_IDENTIFIER,
    values=st.fixed_dictionaries(
        {"type": st.sampled_from(["string", "integer", "number", "boolean"])}
    ),
    max_size=3,
)

_PARAMETERS = st.one_of(
    st.none(),
    st.just({}),
    st.builds(lambda p: {"type": "object", "properties": p}, _PROPERTIES),
    st.builds(lambda p: {"properties": p}, _PROPERTIES),  # missing 'type'
)


@st.composite
def friday_message(draw: Any) -> dict[str, Any]:
    """Generate a valid FRIDAY message (role/content/optional metadata)."""
    role = draw(st.sampled_from(["system", "user", "assistant", "tool", "function"]))
    content = draw(st.text(max_size=100))
    msg: dict[str, Any] = {"role": role, "content": content}

    if role == "tool":
        if draw(st.booleans()):
            msg["tool_call_id"] = draw(_IDENTIFIER)
        if draw(st.booleans()):
            msg["name"] = draw(_IDENTIFIER)
    elif role == "assistant" and draw(st.booleans()):
        msg["tool_calls"] = [
            {
                "id": draw(_IDENTIFIER),
                "function": {"name": "f", "arguments": {}},
            }
        ]
    elif role == "function":
        msg["name"] = draw(_IDENTIFIER)

    return msg


@st.composite
def friday_tool(draw: Any) -> dict[str, Any]:
    """Generate a valid FRIDAY (OpenAI-compatible) tool definition."""
    name = draw(_IDENTIFIER)
    description = draw(st.text(max_size=50))
    params = draw(_PARAMETERS)
    if draw(st.booleans()):
        # Full format
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": params,
            },
        }
    # Simplified format
    return {"name": name, "description": description, "parameters": params}


# --------------------------------------------------------------------------- #
# 5.4 Property 4: Message Format Translation (OpenAI)
# --------------------------------------------------------------------------- #
_VALID_OPENAI_ROLES = {"system", "user", "assistant", "tool", "function"}


@given(messages=st.lists(friday_message(), max_size=10))
def test_property_message_format_translation_openai(messages: list[dict[str, Any]]) -> None:
    """Any valid FRIDAY message translates to a valid OpenAI chat message.

    **Validates: Requirements 2.3**
    """
    adapter = make_adapter()
    result = adapter._translate_messages(messages)

    assert isinstance(result, list)
    assert len(result) == len(messages)

    for original, translated in zip(messages, result):
        # Structural validity: required keys with correct types
        assert "role" in translated
        assert "content" in translated
        assert translated["role"] == original["role"]
        assert translated["role"] in _VALID_OPENAI_ROLES
        assert isinstance(translated["content"], str)

        # Metadata preservation
        if original["role"] == "tool" and "tool_call_id" in original:
            assert translated["tool_call_id"] == original["tool_call_id"]
        if original["role"] == "assistant" and "tool_calls" in original:
            assert translated["tool_calls"] == original["tool_calls"]


# --------------------------------------------------------------------------- #
# 5.5 Property 5: Tool Definition Translation (OpenAI)
# --------------------------------------------------------------------------- #
@given(tool=friday_tool())
def test_property_tool_definition_translation_openai(tool: dict[str, Any]) -> None:
    """Any valid FRIDAY tool def translates to a valid OpenAI tools entry.

    **Validates: Requirements 2.5, 12.1**
    """
    adapter = make_adapter()

    # Determine the expected (normalized) name for comparison
    if tool.get("type") == "function":
        expected_name = tool["function"]["name"].strip()
    else:
        expected_name = tool["name"].strip()

    result = adapter.translate_tools([tool])

    assert isinstance(result, list)
    assert len(result) == 1

    entry = result[0]
    assert entry["type"] == "function"

    fn = entry["function"]
    assert isinstance(fn, dict)
    assert fn["name"] == expected_name
    assert isinstance(fn["name"], str) and fn["name"]
    assert isinstance(fn["description"], str)

    params = fn["parameters"]
    assert isinstance(params, dict)
    assert params["type"] == "object"
    assert "properties" in params
    assert isinstance(params["properties"], dict)


# --------------------------------------------------------------------------- #
# 5.6 Unit tests for OpenAI_Adapter
# --------------------------------------------------------------------------- #
def test_validate_config_not_configured() -> None:
    """validate_config reports failure when no key is configured."""
    adapter = make_adapter(configured=False)
    is_valid, error = adapter.validate_config()
    assert is_valid is False
    assert error == "OpenAI API key is not configured"


def test_validate_config_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """validate_config succeeds when the (faked) client lists models."""
    adapter = make_adapter(configured=True)

    fake_client = SimpleNamespace(models=SimpleNamespace(list=lambda: ["gpt-4o"]))
    monkeypatch.setattr(adapter, "_get_client", lambda: fake_client)

    is_valid, error = adapter.validate_config()
    assert is_valid is True
    assert error is None


def test_validate_config_failure_maps_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """validate_config returns an error message when the API call raises."""
    adapter = make_adapter(configured=True)

    def _raise() -> Any:
        raise RuntimeError("boom: invalid api key")

    fake_client = SimpleNamespace(models=SimpleNamespace(list=_raise))
    monkeypatch.setattr(adapter, "_get_client", lambda: fake_client)

    is_valid, error = adapter.validate_config()
    assert is_valid is False
    assert error and "boom" in error


def test_stream_generate_yields_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """stream_generate yields the content tokens produced by the client."""
    adapter = make_adapter(configured=True)

    def make_chunk(text: str) -> Any:
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
        )

    chunks = [make_chunk("Hello"), make_chunk(", "), make_chunk("world")]

    class FakeCompletions:
        def create(self, **kwargs: Any) -> Any:
            assert kwargs.get("stream") is True
            return iter(chunks)

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr(adapter, "_get_client", lambda: fake_client)

    tokens = list(adapter.stream_generate([{"role": "user", "content": "hi"}]))
    assert tokens == ["Hello", ", ", "world"]


def test_rate_limit_error_mapping() -> None:
    """A rate-limit error maps to a retryable ProviderError with retry_after."""
    adapter = make_adapter(configured=True)

    class RateLimitError(Exception):
        pass

    err = RateLimitError("Rate limit reached. Please retry after 30 seconds")
    provider_error = adapter._create_provider_error(err)

    assert isinstance(provider_error, ProviderError)
    assert isinstance(provider_error, Exception)
    assert provider_error.provider == "openai"
    assert provider_error.error_type == "rate_limit"
    assert provider_error.is_retryable is True
    assert provider_error.retry_after == 30

    # ProviderError is an Exception subclass and can be raised.
    with pytest.raises(ProviderError):
        raise provider_error


def test_auth_error_mapping_not_retryable() -> None:
    """Authentication errors are classified as non-retryable auth errors."""
    adapter = make_adapter(configured=True)

    class AuthenticationError(Exception):
        pass

    provider_error = adapter._create_provider_error(
        AuthenticationError("Invalid API key provided")
    )
    assert provider_error.error_type == "auth"
    assert provider_error.is_retryable is False


def test_parse_tool_calls_from_message_object() -> None:
    """parse_tool_calls extracts id/name/arguments from an SDK-like message."""
    adapter = make_adapter(configured=True)

    tool_call = SimpleNamespace(
        id="call_123",
        function=SimpleNamespace(name="get_weather", arguments='{"city": "NYC"}'),
    )
    message = SimpleNamespace(tool_calls=[tool_call])

    result = adapter.parse_tool_calls(message)

    assert len(result) == 1
    assert result[0]["id"] == "call_123"
    assert result[0]["function"]["name"] == "get_weather"
    assert result[0]["function"]["arguments"] == {"city": "NYC"}


def test_parse_tool_calls_empty_for_none() -> None:
    """parse_tool_calls returns an empty list for None input."""
    adapter = make_adapter(configured=True)
    assert adapter.parse_tool_calls(None) == []
