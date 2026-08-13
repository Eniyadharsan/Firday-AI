"""Shared fakes/stubs for provider adapter tests.

These helpers avoid real network/API calls by providing lightweight stand-ins
for the API key store, OpenAI-compatible clients, requests sessions, and the
Google generativeai module.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional


class FakeKeyStore:
    """Minimal stand-in for API_Key_Store used by adapters.

    Only the methods adapters actually call are implemented:
    get_key(), is_configured(), and set_key().
    """

    def __init__(self, keys: Optional[dict[str, str]] = None) -> None:
        self._keys: dict[str, str] = {}
        for k, v in (keys or {}).items():
            self._keys[k.lower()] = v

    @staticmethod
    def _norm(provider: Any) -> str:
        if hasattr(provider, "value"):
            provider = provider.value
        return str(provider).lower()

    def get_key(self, provider: Any) -> Optional[str]:
        return self._keys.get(self._norm(provider))

    def is_configured(self, provider: Any) -> bool:
        return bool(self._keys.get(self._norm(provider)))

    def set_key(self, provider: Any, key: str) -> bool:
        self._keys[self._norm(provider)] = key
        return True


# --------------------------------------------------------------------------- #
# OpenAI-compatible client fakes (DeepSeek / Grok / OpenRouter)
# --------------------------------------------------------------------------- #
def make_openai_response(
    content: str = "Hello there",
    tool_calls: Optional[list] = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 3,
    completion_tokens: int = 5,
) -> SimpleNamespace:
    """Build a fake OpenAI SDK ChatCompletion-like response object."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


class _FakeCompletions:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


class _FakeChat:
    def __init__(self, response: Any) -> None:
        self.completions = _FakeCompletions(response)


class _FakeModels:
    def __init__(self, models: Optional[list] = None) -> None:
        self._models = models or []

    def list(self) -> Any:
        return self._models


class FakeOpenAIClient:
    """Fake OpenAI-compatible client (used by DeepSeek/Grok/OpenRouter)."""

    def __init__(self, response: Any = None, models: Optional[list] = None) -> None:
        self.chat = _FakeChat(response if response is not None else make_openai_response())
        self.models = _FakeModels(models)


# --------------------------------------------------------------------------- #
# requests fakes (Ollama / Cerebras / OpenRouter model catalog)
# --------------------------------------------------------------------------- #
class FakeResponse:
    """Fake requests.Response."""

    def __init__(
        self,
        status_code: int = 200,
        json_data: Optional[dict] = None,
        headers: Optional[dict] = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}
        self.text = text

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Fake requests.Session for Cerebras adapter."""

    def __init__(
        self,
        post_response: Optional[FakeResponse] = None,
        get_response: Optional[FakeResponse] = None,
    ) -> None:
        self._post_response = post_response
        self._get_response = get_response
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[tuple[str, dict]] = []
        self.headers: dict[str, str] = {}

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.posts.append((url, kwargs))
        return self._post_response

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.gets.append((url, kwargs))
        return self._get_response


# --------------------------------------------------------------------------- #
# Google generativeai fakes (Gemini)
# --------------------------------------------------------------------------- #
class FakeGenerationConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class FakePart:
    def __init__(self, text: Optional[str] = None, function_call: Any = None) -> None:
        self.text = text
        self.function_call = function_call


class FakeContent:
    def __init__(self, parts: list) -> None:
        self.parts = parts


class FakeCandidate:
    def __init__(self, parts: list, finish_reason: str = "STOP") -> None:
        self.content = FakeContent(parts)
        self.finish_reason = finish_reason


def make_gemini_response(
    text: str = "Hi from Gemini",
    function_calls: Optional[list] = None,
    prompt_tokens: int = 4,
    completion_tokens: int = 6,
    finish_reason: str = "STOP",
) -> SimpleNamespace:
    parts: list = []
    if text:
        parts.append(FakePart(text=text))
    for fc in function_calls or []:
        parts.append(FakePart(function_call=fc))
    candidate = FakeCandidate(parts, finish_reason=finish_reason)
    usage = SimpleNamespace(
        prompt_token_count=prompt_tokens,
        candidates_token_count=completion_tokens,
        total_token_count=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(candidates=[candidate], usage_metadata=usage)


class _FakeGenerativeModel:
    def __init__(self, response: Any, **kwargs: Any) -> None:
        self._response = response
        self.kwargs = kwargs

    def generate_content(self, contents: Any, stream: bool = False) -> Any:
        return self._response


class FakeGenai:
    """Fake google.generativeai module."""

    def __init__(self, response: Any = None, models: Optional[list] = None) -> None:
        self._response = response if response is not None else make_gemini_response()
        self._models = models if models is not None else ["models/gemini-flash-latest"]
        self.GenerationConfig = FakeGenerationConfig

    def GenerativeModel(self, **kwargs: Any) -> _FakeGenerativeModel:  # noqa: N802
        return _FakeGenerativeModel(self._response, **kwargs)

    def list_models(self) -> Any:
        return iter(self._models)
