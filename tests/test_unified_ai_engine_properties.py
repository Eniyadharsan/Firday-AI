"""Property-based and unit tests for the Unified_AI_Engine.

This module validates the correctness properties of the Unified_AI_Engine that
govern its provider-agnostic behavior: unified response format, streaming
normalization, context injection, context-window enforcement, conversation
history preservation across provider switches, provider metadata tagging, and
tool call parsing.

Feature: multi-provider-ai

Properties covered:
- Property 1:  Unified Response Format Consistency        (Requirements 1.1)
- Property 6:  Tool Call Parsing                          (Requirements 12.2)
- Property 15: Streaming Format Normalization             (Requirements 11.1)
- Property 16: Markdown Preservation in Streaming         (Requirements 11.4)
- Property 17: Context Injection                          (Requirements 13.1, 13.2)
- Property 18: Context Window Limit Enforcement           (Requirements 13.4)
- Property 19: Conversation History Preservation          (Requirements 13.3)
- Property 20: History Inclusion on Provider Switch       (Requirements 14.2)
- Property 21: Message Provider Metadata                  (Requirements 14.3, 14.4)

Plus unit tests for Task 12.15 covering memory injection, RAG injection,
context window enforcement, history preservation, and streaming normalization.
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
from friday.modules.providers.models import (
    GenerateResponse,
    ProviderCapabilities,
    ProviderHealth,
    ProviderStatus,
    StreamChunk,
)


# ---------------------------------------------------------------------------
# Test doubles: fake provider adapters (NO real API calls)
# ---------------------------------------------------------------------------

class FakeAdapter(Provider_Adapter):
    """Deterministic fake provider adapter for engine testing.

    Records the messages it receives so tests can assert on what the engine
    actually sent to the provider. Returns a deterministic GenerateResponse
    and yields plain string tokens for streaming.
    """

    def __init__(
        self,
        name: str = "fake",
        model: str = "fake-model",
        max_context_window: int = 8192,
        supports_tool_calling: bool = True,
        response_content: str = "response",
        stream_tokens: Optional[list[Any]] = None,
    ) -> None:
        self._name = name
        self._model = model
        self._max_context = max_context_window
        self._supports_tools = supports_tool_calling
        self._response_content = response_content
        self._stream_tokens = stream_tokens if stream_tokens is not None else ["Hello", " ", "world"]
        # Captured state for assertions
        self.last_messages: Optional[list[dict]] = None
        self.last_stream_messages: Optional[list[dict]] = None

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
        self.last_stream_messages = messages
        for token in self._stream_tokens:
            yield token

    def translate_tools(self, friday_tools: list[dict]) -> list[dict]:
        return friday_tools

    def parse_tool_calls(self, response: Any) -> list[dict]:
        """Parse a provider-native tool call response into FRIDAY format.

        Mimics an OpenAI-style response where arguments are JSON strings, and
        normalizes to FRIDAY's standard {id, function: {name, arguments}} shape.
        """
        raw: list[dict] = []
        if isinstance(response, dict):
            raw = response.get("tool_calls", []) or []
        elif hasattr(response, "tool_calls"):
            raw = getattr(response, "tool_calls") or []

        result: list[dict] = []
        for tc in raw:
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (ValueError, TypeError):
                    args = {}
            result.append(
                {
                    "id": tc.get("id", ""),
                    "function": {
                        "name": fn.get("name", ""),
                        "arguments": args,
                    },
                }
            )
        return result

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


class ChunkStreamAdapter(FakeAdapter):
    """Fake adapter whose stream yields non-string wrapper objects.

    Used to verify that the engine normalizes provider-specific streaming
    formats (StreamChunk objects) into plain string tokens (Property 15).
    """

    def stream_generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Generator[Any, None, None]:
        self.last_stream_messages = messages
        # Yield a mix of StreamChunk wrapper objects and plain strings
        for token in self._stream_tokens:
            yield StreamChunk(content=str(token))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_engine(
    adapters: list[FakeAdapter],
    active: Optional[str] = None,
    memory_module: Any = None,
    rag_module: Any = None,
) -> tuple[Unified_AI_Engine, Provider_Registry]:
    """Build a fresh engine backed by a fresh (non-singleton) registry."""
    registry = Provider_Registry()
    for adapter in adapters:
        error = registry.register(adapter)
        assert error is None, f"adapter registration failed: {error}"
    if active is not None:
        registry.set_active(active)
    engine = Unified_AI_Engine(
        registry,
        memory_module=memory_module,
        rag_module=rag_module,
    )
    return engine, registry


class StubMemory:
    """Stub memory module that returns fixed content."""

    def __init__(self, content: Optional[str]):
        self.content = content

    def get_relevant_memories(
        self, user_id, session_id, query=None, max_tokens=None
    ) -> Optional[str]:
        return self.content


class StubRAG:
    """Stub RAG module that returns fixed content."""

    def __init__(self, content: Optional[str]):
        self.content = content

    def get_relevant_documents(
        self, user_id, session_id, query, max_tokens=None
    ) -> Optional[str]:
        return self.content


# Safe text: printable, no control characters that break markdown assertions
safe_text = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    min_size=1,
    max_size=200,
)


# ===========================================================================
# Property 1: Unified Response Format Consistency
# ===========================================================================

class TestUnifiedResponseFormat:
    """Property 1: Unified Response Format Consistency.

    Validates: Requirements 1.1
    """

    @settings(max_examples=10, deadline=None)
    @given(
        content=safe_text,
        provider=st.sampled_from(["openai", "anthropic", "gemini"]),
    )
    def test_response_always_has_required_fields(self, content, provider):
        """Feature: multi-provider-ai, Property 1: Unified Response Format.

        For any content and any configured provider, generate() returns a
        GenerateResponse containing content, model, provider, and usage.
        """
        adapter = FakeAdapter(name=provider, model=f"{provider}-model", response_content=content)
        engine, _ = build_engine([adapter], active=provider)

        response = engine.generate(
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            session_id="s1",
        )

        assert isinstance(response, GenerateResponse)
        # content, model, provider present and strings
        assert isinstance(response.content, str)
        assert isinstance(response.model, str) and response.model
        assert isinstance(response.provider, str) and response.provider
        # usage present with the required token keys
        assert isinstance(response.usage, dict)
        assert "prompt_tokens" in response.usage
        assert "completion_tokens" in response.usage
        assert "total_tokens" in response.usage


# ===========================================================================
# Property 15: Streaming Format Normalization
# ===========================================================================

class TestStreamingNormalization:
    """Property 15: Streaming Format Normalization.

    Validates: Requirements 11.1
    """

    @settings(max_examples=10, deadline=None)
    @given(tokens=st.lists(safe_text, min_size=1, max_size=10))
    def test_string_stream_yields_plain_strings(self, tokens):
        """Feature: multi-provider-ai, Property 15: Streaming Format Normalization.

        A provider streaming plain strings yields only plain string tokens.
        """
        adapter = FakeAdapter(name="fake", stream_tokens=list(tokens))
        engine, _ = build_engine([adapter], active="fake")

        emitted = list(
            engine.stream_generate(
                messages=[{"role": "user", "content": "hi"}],
                user_id="u1",
                session_id="s1",
            )
        )

        assert all(isinstance(tok, str) for tok in emitted)

    @settings(max_examples=10, deadline=None)
    @given(tokens=st.lists(safe_text, min_size=1, max_size=10))
    def test_wrapper_object_stream_normalized_to_strings(self, tokens):
        """Feature: multi-provider-ai, Property 15: Streaming Format Normalization.

        A provider streaming StreamChunk wrapper objects is normalized so the
        engine yields plain string tokens with no provider wrapper objects.
        """
        adapter = ChunkStreamAdapter(name="fake", stream_tokens=list(tokens))
        engine, _ = build_engine([adapter], active="fake")

        emitted = list(
            engine.stream_generate(
                messages=[{"role": "user", "content": "hi"}],
                user_id="u1",
                session_id="s1",
            )
        )

        assert all(isinstance(tok, str) for tok in emitted)
        assert all(not isinstance(tok, StreamChunk) for tok in emitted)


# ===========================================================================
# Property 16: Markdown Preservation in Streaming
# ===========================================================================

class TestMarkdownPreservation:
    """Property 16: Markdown Preservation in Streaming.

    Validates: Requirements 11.4
    """

    @settings(max_examples=10, deadline=None)
    @given(
        markdown=st.sampled_from(
            [
                "# Header\n\nSome **bold** text.",
                "- item 1\n- item 2\n- item 3",
                "```python\nprint('hi')\n```",
                "Normal *emphasis* and `inline code` here.",
                "## Sub\n\n1. one\n2. two\n\n> quote",
                "Mix **bold** and\n```\ncode block\n```\nand more.",
            ]
        ),
        chunk_size=st.integers(min_value=1, max_value=8),
    )
    def test_concatenated_tokens_preserve_markdown(self, markdown, chunk_size):
        """Feature: multi-provider-ai, Property 16: Markdown Preservation in Streaming.

        The concatenation of all streamed tokens equals the original markdown,
        preserving headers, lists, code blocks, and emphasis exactly.
        """
        chunks = [markdown[i : i + chunk_size] for i in range(0, len(markdown), chunk_size)]
        adapter = FakeAdapter(name="fake", stream_tokens=chunks)
        engine, _ = build_engine([adapter], active="fake")

        emitted = list(
            engine.stream_generate(
                messages=[{"role": "user", "content": "give me markdown"}],
                user_id="u1",
                session_id="s1",
            )
        )

        assert "".join(emitted) == markdown


# ===========================================================================
# Property 17: Context Injection
# ===========================================================================

class TestContextInjection:
    """Property 17: Context Injection.

    Validates: Requirements 13.1, 13.2
    """

    @settings(max_examples=10, deadline=None)
    @given(memory_content=safe_text)
    def test_memory_context_present_in_provider_messages(self, memory_content):
        """Feature: multi-provider-ai, Property 17: Context Injection (memory).

        Available memory context appears in the messages sent to the provider.
        """
        adapter = FakeAdapter(name="fake", max_context_window=100000)
        engine, _ = build_engine(
            [adapter], active="fake", memory_module=StubMemory(memory_content)
        )

        engine.generate(
            messages=[{"role": "user", "content": "hello"}],
            user_id="u1",
            session_id="s1",
        )

        combined = "\n".join(m.get("content", "") for m in adapter.last_messages)
        assert memory_content in combined

    @settings(max_examples=10, deadline=None)
    @given(rag_content=safe_text)
    def test_rag_context_present_in_provider_messages(self, rag_content):
        """Feature: multi-provider-ai, Property 17: Context Injection (RAG).

        Available RAG document context appears in messages sent to the provider.
        """
        adapter = FakeAdapter(name="fake", max_context_window=100000)
        engine, _ = build_engine(
            [adapter], active="fake", rag_module=StubRAG(rag_content)
        )

        engine.generate(
            messages=[{"role": "user", "content": "question"}],
            user_id="u1",
            session_id="s1",
        )

        combined = "\n".join(m.get("content", "") for m in adapter.last_messages)
        assert rag_content in combined


# ===========================================================================
# Property 18: Context Window Limit Enforcement
# ===========================================================================

class TestContextWindowEnforcement:
    """Property 18: Context Window Limit Enforcement.

    Validates: Requirements 13.4
    """

    @settings(max_examples=10, deadline=None)
    @given(
        max_context=st.integers(min_value=2000, max_value=8000),
        memory_len=st.integers(min_value=0, max_value=20000),
        rag_len=st.integers(min_value=0, max_value=20000),
    )
    def test_injected_context_never_exceeds_context_window(
        self, max_context, memory_len, rag_len
    ):
        """Feature: multi-provider-ai, Property 18: Context Window Limit Enforcement.

        For any combination of messages, memory, and RAG context, the total
        estimated token count of the enriched messages never exceeds the
        provider's context_window.
        """
        adapter = FakeAdapter(name="fake", max_context_window=max_context)
        memory = StubMemory("M" * memory_len) if memory_len else None
        rag = StubRAG("R" * rag_len) if rag_len else None
        engine, _ = build_engine(
            [adapter], active="fake", memory_module=memory, rag_module=rag
        )

        messages = [{"role": "user", "content": "please answer this question"}]
        enriched = engine._enrich_context(messages, "u1", "s1")

        total_tokens = engine._estimate_messages_tokens(enriched)
        assert total_tokens <= max_context


# ===========================================================================
# Property 19: Conversation History Preservation Across Provider Switches
# ===========================================================================

class TestHistoryPreservation:
    """Property 19: Conversation History Preservation Across Provider Switches.

    Validates: Requirements 13.3
    """

    @settings(max_examples=10, deadline=None)
    @given(
        user_msgs=st.lists(safe_text, min_size=1, max_size=6, unique=True),
        switches=st.lists(st.booleans(), min_size=6, max_size=6),
    )
    def test_history_intact_across_provider_switches(self, user_msgs, switches):
        """Feature: multi-provider-ai, Property 19: Conversation History Preservation.

        After a sequence of provider switches, the complete conversation history
        (all user messages, in order) remains intact and accessible.
        """
        adapter_a = FakeAdapter(name="fake_a", model="a-model")
        adapter_b = FakeAdapter(name="fake_b", model="b-model")
        engine, registry = build_engine([adapter_a, adapter_b], active="fake_a")

        session = "s1"
        for i, msg in enumerate(user_msgs):
            # Switch provider based on the (deterministic) switch flag
            registry.set_active("fake_b" if switches[i % len(switches)] else "fake_a")
            engine.generate(
                messages=[{"role": "user", "content": msg}],
                user_id="u1",
                session_id=session,
            )

        history = engine.conversation_history.get_history(session)
        # All user messages preserved, in order
        recorded_user = [m.content for m in history if m.role == "user"]
        assert recorded_user == list(user_msgs)
        # One assistant message per user message
        recorded_assistant = [m for m in history if m.role == "assistant"]
        assert len(recorded_assistant) == len(user_msgs)


# ===========================================================================
# Property 20: History Inclusion on Provider Switch
# ===========================================================================

class TestHistoryInclusionOnSwitch:
    """Property 20: History Inclusion on Provider Switch.

    Validates: Requirements 14.2
    """

    @settings(max_examples=10, deadline=None)
    @given(
        first_msg=safe_text,
        second_msg=safe_text,
    )
    def test_switch_includes_prior_history_in_new_provider_context(
        self, first_msg, second_msg
    ):
        """Feature: multi-provider-ai, Property 20: History Inclusion on Provider Switch.

        After a provider switch, the next generate() call to the new provider
        includes the prior conversation history in its messages array.
        """
        adapter_a = FakeAdapter(name="fake_a", model="a-model", response_content="reply-a")
        adapter_b = FakeAdapter(name="fake_b", model="b-model", response_content="reply-b")
        engine, registry = build_engine([adapter_a, adapter_b], active="fake_a")

        session = "s1"
        # Turn 1 on provider A
        engine.generate(
            messages=[{"role": "user", "content": first_msg}],
            user_id="u1",
            session_id=session,
        )

        # Switch to provider B and take turn 2
        registry.set_active("fake_b")
        engine.generate(
            messages=[{"role": "user", "content": second_msg}],
            user_id="u1",
            session_id=session,
        )

        # Provider B should have received the prior history
        contents = [m.get("content", "") for m in adapter_b.last_messages]
        assert first_msg in contents
        assert "reply-a" in contents
        assert second_msg in contents


# ===========================================================================
# Property 21: Message Provider Metadata
# ===========================================================================

class TestMessageProviderMetadata:
    """Property 21: Message Provider Metadata.

    Validates: Requirements 14.3, 14.4
    """

    @settings(max_examples=10, deadline=None)
    @given(
        provider=st.sampled_from(["openai", "anthropic", "gemini"]),
        msg=safe_text,
    )
    def test_assistant_messages_tagged_with_provider_and_model(self, provider, msg):
        """Feature: multi-provider-ai, Property 21: Message Provider Metadata.

        Every assistant message stored in history has non-null provider and
        model fields indicating which provider/model generated it.
        """
        adapter = FakeAdapter(name=provider, model=f"{provider}-model")
        engine, _ = build_engine([adapter], active=provider)

        session = "s1"
        engine.generate(
            messages=[{"role": "user", "content": msg}],
            user_id="u1",
            session_id=session,
        )

        history = engine.conversation_history.get_history(session)
        assistant_msgs = [m for m in history if m.role == "assistant"]
        assert assistant_msgs, "expected at least one assistant message"
        for m in assistant_msgs:
            assert m.provider == provider
            assert m.model == f"{provider}-model"


# ===========================================================================
# Property 6: Tool Call Parsing
# ===========================================================================

class TestToolCallParsing:
    """Property 6: Tool Call Parsing.

    Validates: Requirements 12.2
    """

    @settings(max_examples=10, deadline=None)
    @given(
        call_id=st.text(
            alphabet=st.characters(min_codepoint=48, max_codepoint=122),
            min_size=1,
            max_size=20,
        ),
        func_name=st.text(
            alphabet=st.characters(min_codepoint=97, max_codepoint=122),
            min_size=1,
            max_size=20,
        ),
        arguments=st.dictionaries(
            keys=st.text(
                alphabet=st.characters(min_codepoint=97, max_codepoint=122),
                min_size=1,
                max_size=8,
            ),
            values=st.one_of(
                st.text(
                    alphabet=st.characters(min_codepoint=97, max_codepoint=122),
                    max_size=10,
                ),
                st.integers(min_value=-1000, max_value=1000),
                st.booleans(),
            ),
            max_size=5,
        ),
    )
    def test_provider_tool_call_parses_to_friday_format(
        self, call_id, func_name, arguments
    ):
        """Feature: multi-provider-ai, Property 6: Tool Call Parsing.

        A provider tool call response parses to FRIDAY's ToolCall format with
        correctly extracted id, function name, and arguments.
        """
        adapter = FakeAdapter(name="fake")
        engine, _ = build_engine([adapter], active="fake")

        # Provider-native response: arguments encoded as a JSON string
        native_response = {
            "tool_calls": [
                {
                    "id": call_id,
                    "function": {
                        "name": func_name,
                        "arguments": json.dumps(arguments),
                    },
                }
            ]
        }

        parsed = engine.parse_tool_calls_from_response(native_response, provider_name="fake")

        assert isinstance(parsed, list)
        assert len(parsed) == 1
        tc = parsed[0]
        assert tc["id"] == call_id
        assert tc["function"]["name"] == func_name
        assert tc["function"]["arguments"] == arguments

    @settings(max_examples=10, deadline=None)
    @given(content=safe_text)
    def test_generate_response_tool_calls_pass_through(self, content):
        """Feature: multi-provider-ai, Property 6: Tool Call Parsing.

        A GenerateResponse carrying tool_calls returns them unchanged in FRIDAY
        format via parse_tool_calls_from_response().
        """
        adapter = FakeAdapter(name="fake")
        engine, _ = build_engine([adapter], active="fake")

        tool_calls = [
            {"id": "call_1", "function": {"name": "do_thing", "arguments": {"x": content}}}
        ]
        response = GenerateResponse(
            content="",
            model="fake-model",
            provider="fake",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            tool_calls=tool_calls,
        )

        parsed = engine.parse_tool_calls_from_response(response)
        assert parsed == tool_calls


# ===========================================================================
# Task 12.15: Unit tests for Unified_AI_Engine
# ===========================================================================

class TestEngineUnit:
    """Unit tests for Unified_AI_Engine core behaviors.

    Validates: Requirements 1.1, 11.1, 13.1, 13.2, 13.4, 14.1
    """

    def test_memory_injection_adds_context(self):
        """Memory context is injected into the system message. (Req 13.1)"""
        adapter = FakeAdapter(name="fake")
        engine, _ = build_engine(
            [adapter], active="fake", memory_module=StubMemory("User likes tea.")
        )

        enriched = engine._enrich_context(
            [{"role": "user", "content": "hi"}], "u1", "s1"
        )

        assert enriched[0]["role"] == "system"
        assert "User likes tea." in enriched[0]["content"]
        assert "[Long-term Memory Context]" in enriched[0]["content"]

    def test_rag_injection_adds_context(self):
        """RAG context is injected into the system message. (Req 13.2)"""
        adapter = FakeAdapter(name="fake")
        engine, _ = build_engine(
            [adapter], active="fake", rag_module=StubRAG("Doc: pytest guide.")
        )

        enriched = engine._enrich_context(
            [{"role": "user", "content": "how to test?"}], "u1", "s1"
        )

        assert enriched[0]["role"] == "system"
        assert "Doc: pytest guide." in enriched[0]["content"]
        assert "[Retrieved Document Context]" in enriched[0]["content"]

    def test_no_injection_without_modules(self):
        """Without memory/RAG modules, messages are unchanged."""
        adapter = FakeAdapter(name="fake")
        engine, _ = build_engine([adapter], active="fake")

        messages = [{"role": "user", "content": "hi"}]
        enriched = engine._enrich_context(messages, "u1", "s1")
        assert enriched == messages

    def test_context_window_enforced_with_large_memory(self):
        """Large memory content is truncated to fit the context window. (Req 13.4)"""
        adapter = FakeAdapter(name="fake", max_context_window=3000)
        huge = "word " * 10000  # ~50k chars, far larger than the window
        engine, _ = build_engine(
            [adapter], active="fake", memory_module=StubMemory(huge)
        )

        enriched = engine._enrich_context(
            [{"role": "user", "content": "answer please"}], "u1", "s1"
        )

        total = engine._estimate_messages_tokens(enriched)
        assert total <= 3000

    def test_memory_module_receives_token_budget(self):
        """Memory module is called with a positive max_tokens budget. (Req 13.4)"""
        adapter = FakeAdapter(name="fake", max_context_window=4000)

        class RecordingMemory:
            def __init__(self):
                self.max_tokens = None

            def get_relevant_memories(self, user_id, session_id, query=None, max_tokens=None):
                self.max_tokens = max_tokens
                return "some memory"

        mem = RecordingMemory()
        engine, _ = build_engine([adapter], active="fake", memory_module=mem)
        engine._enrich_context([{"role": "user", "content": "hi"}], "u1", "s1")

        assert mem.max_tokens is not None
        assert 0 < mem.max_tokens < 4000

    def test_history_preserved_across_switch(self):
        """A single unified history is maintained across a provider switch. (Req 14.1)"""
        adapter_a = FakeAdapter(name="fake_a", model="a-model", response_content="A")
        adapter_b = FakeAdapter(name="fake_b", model="b-model", response_content="B")
        engine, registry = build_engine([adapter_a, adapter_b], active="fake_a")

        engine.generate(
            messages=[{"role": "user", "content": "first"}],
            user_id="u1",
            session_id="s1",
        )
        registry.set_active("fake_b")
        engine.generate(
            messages=[{"role": "user", "content": "second"}],
            user_id="u1",
            session_id="s1",
        )

        history = engine.conversation_history.get_history("s1")
        roles_contents = [(m.role, m.content) for m in history]
        assert ("user", "first") in roles_contents
        assert ("user", "second") in roles_contents
        assert ("assistant", "A") in roles_contents
        assert ("assistant", "B") in roles_contents
        # Providers recorded per assistant message
        providers = {m.provider for m in history if m.role == "assistant"}
        assert providers == {"fake_a", "fake_b"}

    def test_streaming_yields_only_strings(self):
        """stream_generate yields plain string tokens. (Req 11.1)"""
        adapter = FakeAdapter(name="fake", stream_tokens=["Hel", "lo", "!"])
        engine, _ = build_engine([adapter], active="fake")

        emitted = list(
            engine.stream_generate(
                messages=[{"role": "user", "content": "hi"}],
                user_id="u1",
                session_id="s1",
            )
        )
        assert emitted == ["Hel", "lo", "!"]
        assert all(isinstance(t, str) for t in emitted)

    def test_streaming_normalizes_wrapper_objects(self):
        """StreamChunk wrapper objects are normalized to strings. (Req 11.1)"""
        adapter = ChunkStreamAdapter(name="fake", stream_tokens=["a", "b", "c"])
        engine, _ = build_engine([adapter], active="fake")

        emitted = list(
            engine.stream_generate(
                messages=[{"role": "user", "content": "hi"}],
                user_id="u1",
                session_id="s1",
            )
        )
        assert emitted == ["a", "b", "c"]
        assert all(isinstance(t, str) for t in emitted)

    def test_generate_without_active_provider_raises(self):
        """generate() raises ValueError when no provider is active."""
        registry = Provider_Registry()
        engine = Unified_AI_Engine(registry)
        with pytest.raises(ValueError):
            engine.generate(
                messages=[{"role": "user", "content": "hi"}],
                user_id="u1",
                session_id="s1",
            )

    def test_response_format_normalized_end_to_end(self):
        """generate() returns a fully-populated GenerateResponse. (Req 1.1)"""
        adapter = FakeAdapter(name="fake", response_content="hello there")
        engine, _ = build_engine([adapter], active="fake")

        response = engine.generate(
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            session_id="s1",
        )
        assert response.content == "hello there"
        assert response.provider == "fake"
        assert response.model == "fake-model"
        assert set(["prompt_tokens", "completion_tokens", "total_tokens"]).issubset(
            response.usage.keys()
        )
