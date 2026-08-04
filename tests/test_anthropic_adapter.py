"""Property-based and unit tests for Anthropic_Adapter.

Covers spec tasks:
- 6.4 Property test: Message Format Translation (Anthropic) (Property 4)
- 6.5 Unit tests for Anthropic_Adapter

No real network calls are made: a mock API_Key_Store stub is used and the
lazily-initialized client is monkeypatched with fakes returning canned objects.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import pytest
from hypothesis import given
from hypothesis import strategies as st

from friday.modules.providers.adapters.anthropic_adapter import Anthropic_Adapter
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


def make_adapter(configured: bool = True) -> Anthropic_Adapter:
    keys = {"anthropic": "sk-ant-test-key"} if configured else {}
    return Anthropic_Adapter(MockKeyStore(keys))


# --------------------------------------------------------------------------- #
# Hypothesis strategies
# --------------------------------------------------------------------------- #
@st.composite
def friday_message(draw: Any) -> dict[str, Any]:
    """Generate a valid FRIDAY message with a system/user/assistant role."""
    role = draw(st.sampled_from(["system", "user", "assistant"]))
    content = draw(st.text(max_size=100))
    return {"role": role, "content": content}


# --------------------------------------------------------------------------- #
# 6.4 Property 4: Message Format Translation (Anthropic)
# --------------------------------------------------------------------------- #
@given(messages=st.lists(friday_message(), max_size=10))
def test_property_message_format_translation_anthropic(
    messages: list[dict[str, Any]]
) -> None:
    """System messages are extracted separately; user/assistant mapped correctly.

    **Validates: Requirements 3.3**
    """
    adapter = make_adapter()
    system_message, anthropic_messages = adapter._translate_messages(messages)

    # System extraction: last system message wins, or None when absent.
    system_inputs = [m["content"] for m in messages if m["role"] == "system"]
    if system_inputs:
        assert system_message == system_inputs[-1]
    else:
        assert system_message is None

    # No system messages leak into the messages array.
    non_system = [m for m in messages if m["role"] in ("user", "assistant")]
    assert len(anthropic_messages) == len(non_system)

    for translated, original in zip(anthropic_messages, non_system):
        assert translated["role"] in ("user", "assistant")
        assert translated["role"] == original["role"]
        assert "content" in translated
        assert isinstance(translated["content"], str)
        assert translated["content"] == original["content"]


# --------------------------------------------------------------------------- #
# 6.5 Unit tests for Anthropic_Adapter
# --------------------------------------------------------------------------- #
def test_validate_config_not_configured() -> None:
    """validate_config reports failure when no key is configured."""
    adapter = make_adapter(configured=False)
    is_valid, error = adapter.validate_config()
    assert is_valid is False
    assert error == "Anthropic API key is not configured"


def test_validate_config_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """validate_config succeeds when the (faked) client accepts a message."""
    adapter = make_adapter(configured=True)

    fake_client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kwargs: SimpleNamespace())
    )
    monkeypatch.setattr(adapter, "_get_client", lambda: fake_client)

    is_valid, error = adapter.validate_config()
    assert is_valid is True
    assert error is None


def test_overloaded_error_mapping() -> None:
    """Anthropic overloaded errors map to a retryable 'overloaded' ProviderError."""
    adapter = make_adapter(configured=True)

    class OverloadedError(Exception):
        pass

    provider_error = adapter._create_provider_error(
        OverloadedError("The API is temporarily overloaded, please try again")
    )

    assert isinstance(provider_error, ProviderError)
    assert isinstance(provider_error, Exception)
    assert provider_error.provider == "anthropic"
    assert provider_error.error_type == "overloaded"
    assert provider_error.is_retryable is True

    # ProviderError is an Exception subclass and can be raised.
    with pytest.raises(ProviderError):
        raise provider_error


def test_auth_error_mapping_not_retryable() -> None:
    """Authentication errors are classified as non-retryable auth errors."""
    adapter = make_adapter(configured=True)

    class AuthenticationError(Exception):
        pass

    provider_error = adapter._create_provider_error(
        AuthenticationError("invalid api key")
    )
    assert provider_error.error_type == "auth"
    assert provider_error.is_retryable is False


def test_parse_tool_calls_tool_use_dict() -> None:
    """parse_tool_calls extracts tool_use blocks from a dict response."""
    adapter = make_adapter(configured=True)

    response = {
        "content": [
            {"type": "text", "text": "Let me look that up"},
            {
                "type": "tool_use",
                "id": "toolu_01",
                "name": "search",
                "input": {"query": "weather"},
            },
        ]
    }

    result = adapter.parse_tool_calls(response)

    assert len(result) == 1
    assert result[0]["id"] == "toolu_01"
    assert result[0]["function"]["name"] == "search"
    assert result[0]["function"]["arguments"] == {"query": "weather"}


def test_parse_tool_calls_tool_use_object() -> None:
    """parse_tool_calls extracts tool_use blocks from SDK-like objects."""
    adapter = make_adapter(configured=True)

    block = SimpleNamespace(
        type="tool_use",
        id="toolu_02",
        name="calculator",
        input={"a": 1, "b": 2},
    )
    message = SimpleNamespace(content=[block])

    result = adapter.parse_tool_calls(message)

    assert len(result) == 1
    assert result[0]["id"] == "toolu_02"
    assert result[0]["function"]["name"] == "calculator"
    assert result[0]["function"]["arguments"] == {"a": 1, "b": 2}


def test_parse_tool_calls_empty_for_none() -> None:
    """parse_tool_calls returns an empty list for None input."""
    adapter = make_adapter(configured=True)
    assert adapter.parse_tool_calls(None) == []
