"""Tests for Unified_AI_Engine context injection functionality.

This module tests the memory and RAG context injection in the Unified_AI_Engine,
validating Requirements 13.1, 13.2, and 13.4.

Requirements:
- 13.1: THE Unified_AI_Engine SHALL inject long-term memory context into prompts
- 13.2: THE Unified_AI_Engine SHALL inject RAG document context into prompts
- 13.4: THE Unified_AI_Engine SHALL respect each provider's context window limit
"""

import pytest
from typing import Any, Optional
from unittest.mock import MagicMock, PropertyMock

from friday.modules.providers.engine import Unified_AI_Engine
from friday.modules.providers.models import ProviderCapabilities


class MockMemoryModule:
    """Mock memory module for testing."""
    
    def __init__(self, memory_content: Optional[str] = None):
        self.memory_content = memory_content
        self.call_count = 0
        self.last_call_args = {}
    
    def get_relevant_memories(
        self,
        user_id: str,
        session_id: str,
        query: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """Return mock memory content."""
        self.call_count += 1
        self.last_call_args = {
            "user_id": user_id,
            "session_id": session_id,
            "query": query,
            "max_tokens": max_tokens,
        }
        return self.memory_content


class MockRAGModule:
    """Mock RAG module for testing."""
    
    def __init__(self, rag_content: Optional[str] = None):
        self.rag_content = rag_content
        self.call_count = 0
        self.last_call_args = {}
    
    def get_relevant_documents(
        self,
        user_id: str,
        session_id: str,
        query: str,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """Return mock RAG content."""
        self.call_count += 1
        self.last_call_args = {
            "user_id": user_id,
            "session_id": session_id,
            "query": query,
            "max_tokens": max_tokens,
        }
        return self.rag_content


class MockProvider:
    """Mock provider adapter for testing."""
    
    def __init__(self, max_context_window: int = 8192):
        self._capabilities = ProviderCapabilities(
            supports_streaming=True,
            supports_tool_calling=True,
            supports_vision=False,
            max_context_window=max_context_window,
            supported_models=["mock-model"],
        )
    
    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities


class MockRegistry:
    """Mock provider registry for testing."""
    
    def __init__(self, max_context_window: int = 8192):
        self._active_adapter = MockProvider(max_context_window)
    
    def get_active_adapter(self):
        return self._active_adapter


class TestContextInjection:
    """Tests for memory and RAG context injection."""
    
    def test_no_context_without_modules(self):
        """Test that messages are unchanged when no modules are set."""
        registry = MockRegistry()
        engine = Unified_AI_Engine(registry)
        
        messages = [{"role": "user", "content": "Hello world"}]
        enriched = engine._enrich_context(messages, "user1", "session1")
        
        assert enriched == messages
    
    def test_memory_context_injection(self):
        """Test that memory context is injected into messages.
        
        Validates: Requirement 13.1
        """
        registry = MockRegistry()
        memory = MockMemoryModule("User prefers Python programming.")
        
        engine = Unified_AI_Engine(registry, memory_module=memory)
        
        messages = [{"role": "user", "content": "Help me with code"}]
        enriched = engine._enrich_context(messages, "user1", "session1")
        
        # Memory module should be called
        assert memory.call_count == 1
        assert memory.last_call_args["user_id"] == "user1"
        assert memory.last_call_args["session_id"] == "session1"
        assert memory.last_call_args["query"] == "Help me with code"
        
        # Context should be injected
        assert len(enriched) == 2  # System message + user message
        assert enriched[0]["role"] == "system"
        assert "[Long-term Memory Context]" in enriched[0]["content"]
        assert "User prefers Python programming." in enriched[0]["content"]
    
    def test_rag_context_injection(self):
        """Test that RAG context is injected into messages.
        
        Validates: Requirement 13.2
        """
        registry = MockRegistry()
        rag = MockRAGModule("Document: Python best practices guide.")
        
        engine = Unified_AI_Engine(registry, rag_module=rag)
        
        messages = [{"role": "user", "content": "What are Python best practices?"}]
        enriched = engine._enrich_context(messages, "user1", "session1")
        
        # RAG module should be called
        assert rag.call_count == 1
        assert rag.last_call_args["user_id"] == "user1"
        assert rag.last_call_args["session_id"] == "session1"
        assert rag.last_call_args["query"] == "What are Python best practices?"
        
        # Context should be injected
        assert len(enriched) == 2  # System message + user message
        assert enriched[0]["role"] == "system"
        assert "[Retrieved Document Context]" in enriched[0]["content"]
        assert "Python best practices guide." in enriched[0]["content"]
    
    def test_both_memory_and_rag_injection(self):
        """Test that both memory and RAG context are injected."""
        registry = MockRegistry()
        memory = MockMemoryModule("User is a senior developer.")
        rag = MockRAGModule("API Documentation: REST endpoints.")
        
        engine = Unified_AI_Engine(registry, memory_module=memory, rag_module=rag)
        
        messages = [{"role": "user", "content": "How do I use the API?"}]
        enriched = engine._enrich_context(messages, "user1", "session1")
        
        # Both modules should be called
        assert memory.call_count == 1
        assert rag.call_count == 1
        
        # Both contexts should be in system message
        system_content = enriched[0]["content"]
        assert "[Long-term Memory Context]" in system_content
        assert "User is a senior developer." in system_content
        assert "[Retrieved Document Context]" in system_content
        assert "API Documentation: REST endpoints." in system_content
    
    def test_context_appended_to_existing_system_message(self):
        """Test that context is appended to existing system message."""
        registry = MockRegistry()
        memory = MockMemoryModule("User memory content.")
        
        engine = Unified_AI_Engine(registry, memory_module=memory)
        
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        enriched = engine._enrich_context(messages, "user1", "session1")
        
        # Should still have 2 messages (system + user)
        assert len(enriched) == 2
        assert enriched[0]["role"] == "system"
        
        # System message should contain both original content and memory
        assert "You are a helpful assistant." in enriched[0]["content"]
        assert "[Long-term Memory Context]" in enriched[0]["content"]
        assert "User memory content." in enriched[0]["content"]
    
    def test_null_memory_context_not_injected(self):
        """Test that null memory context doesn't inject anything."""
        registry = MockRegistry()
        memory = MockMemoryModule(None)  # Returns None
        
        engine = Unified_AI_Engine(registry, memory_module=memory)
        
        messages = [{"role": "user", "content": "Hello"}]
        enriched = engine._enrich_context(messages, "user1", "session1")
        
        # Memory module was called but returned None
        assert memory.call_count == 1
        
        # No system message should be added
        assert len(enriched) == 1
        assert enriched[0]["role"] == "user"
    
    def test_null_rag_context_not_injected(self):
        """Test that null RAG context doesn't inject anything."""
        registry = MockRegistry()
        rag = MockRAGModule(None)  # Returns None
        
        engine = Unified_AI_Engine(registry, rag_module=rag)
        
        messages = [{"role": "user", "content": "Hello"}]
        enriched = engine._enrich_context(messages, "user1", "session1")
        
        # RAG module was called but returned None
        assert rag.call_count == 1
        
        # No system message should be added
        assert len(enriched) == 1


class TestTokenEstimation:
    """Tests for token estimation functionality."""
    
    def test_estimate_token_count(self):
        """Test token estimation uses 4 chars per token heuristic."""
        registry = MockRegistry()
        engine = Unified_AI_Engine(registry)
        
        # 40 characters should be ~10 tokens
        text = "a" * 40
        tokens = engine._estimate_token_count(text)
        assert tokens == 10
    
    def test_estimate_empty_string(self):
        """Test token estimation for empty string."""
        registry = MockRegistry()
        engine = Unified_AI_Engine(registry)
        
        tokens = engine._estimate_token_count("")
        assert tokens == 0
    
    def test_estimate_messages_tokens(self):
        """Test token estimation for message list."""
        registry = MockRegistry()
        engine = Unified_AI_Engine(registry)
        
        messages = [
            {"role": "system", "content": "a" * 40},  # ~10 tokens + 4 overhead
            {"role": "user", "content": "b" * 80},     # ~20 tokens + 4 overhead
        ]
        
        tokens = engine._estimate_messages_tokens(messages)
        # (10 + 4) + (20 + 4) = 38
        assert tokens == 38


class TestContextWindowLimits:
    """Tests for context window limit enforcement.
    
    Validates: Requirement 13.4
    """
    
    def test_respects_provider_context_window(self):
        """Test that context injection respects provider's context window limit."""
        # Use a reasonable context window that allows for context injection
        # 4000 tokens - enough for messages + response reserve + some context
        registry = MockRegistry(max_context_window=4000)
        
        # Create memory with moderate content
        large_memory = "User information about preferences. " * 20  # ~720 chars
        memory = MockMemoryModule(large_memory)
        
        engine = Unified_AI_Engine(registry, memory_module=memory)
        
        messages = [{"role": "user", "content": "Hello"}]
        enriched = engine._enrich_context(messages, "user1", "session1")
        
        # Memory module should be called with token limit
        assert memory.call_count == 1
        assert memory.last_call_args["max_tokens"] is not None
        # Token limit should be calculated from context window
        # Available = 4000 - ~5 (message tokens) - 1024 (response reserve) = ~2971
        # Memory budget = 40% of ~2971 = ~1188
        assert memory.last_call_args["max_tokens"] > 0
        assert memory.last_call_args["max_tokens"] < 4000
    
    def test_get_provider_context_limit(self):
        """Test that provider context limit is correctly retrieved."""
        registry = MockRegistry(max_context_window=16384)
        engine = Unified_AI_Engine(registry)
        
        limit = engine._get_provider_context_limit()
        assert limit == 16384
    
    def test_default_context_limit_without_provider(self):
        """Test default context limit when no provider is available."""
        registry = MagicMock()
        registry.get_active_adapter.return_value = None
        
        engine = Unified_AI_Engine(registry)
        
        limit = engine._get_provider_context_limit()
        assert limit == 8192  # Default fallback
    
    def test_truncates_large_context(self):
        """Test that large context is truncated to fit window."""
        registry = MockRegistry()
        engine = Unified_AI_Engine(registry)
        
        # Create a large context (more than 100 tokens worth)
        large_context = "This is a very long context. " * 50
        
        # Truncate to 100 tokens (400 chars)
        truncated = engine._truncate_context(large_context, 100)
        
        # Should be truncated with note
        assert len(truncated) <= 400 + 100  # Some slack for truncation note
        assert "[... content truncated" in truncated or len(truncated) <= 400


class TestQueryExtraction:
    """Tests for query extraction from messages."""
    
    def test_extracts_last_user_message(self):
        """Test that query is extracted from last user message."""
        registry = MockRegistry()
        engine = Unified_AI_Engine(registry)
        
        messages = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Second question"},
        ]
        
        query = engine._extract_query_from_messages(messages)
        assert query == "Second question"
    
    def test_returns_none_without_user_message(self):
        """Test that None is returned when no user message exists."""
        registry = MockRegistry()
        engine = Unified_AI_Engine(registry)
        
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "assistant", "content": "Hello"},
        ]
        
        query = engine._extract_query_from_messages(messages)
        assert query is None
    
    def test_skips_empty_user_messages(self):
        """Test that empty user messages are skipped."""
        registry = MockRegistry()
        engine = Unified_AI_Engine(registry)
        
        messages = [
            {"role": "user", "content": "Valid question"},
            {"role": "user", "content": ""},
        ]
        
        query = engine._extract_query_from_messages(messages)
        assert query == "Valid question"


class TestSetModules:
    """Tests for setting memory and RAG modules after construction."""
    
    def test_set_memory_module(self):
        """Test that memory module can be set after construction."""
        registry = MockRegistry()
        engine = Unified_AI_Engine(registry)
        
        memory = MockMemoryModule("Test memory")
        engine.set_memory_module(memory)
        
        messages = [{"role": "user", "content": "Hello"}]
        enriched = engine._enrich_context(messages, "user1", "session1")
        
        assert memory.call_count == 1
        assert "[Long-term Memory Context]" in enriched[0]["content"]
    
    def test_set_rag_module(self):
        """Test that RAG module can be set after construction."""
        registry = MockRegistry()
        engine = Unified_AI_Engine(registry)
        
        rag = MockRAGModule("Test documents")
        engine.set_rag_module(rag)
        
        messages = [{"role": "user", "content": "Hello"}]
        enriched = engine._enrich_context(messages, "user1", "session1")
        
        assert rag.call_count == 1
        assert "[Retrieved Document Context]" in enriched[0]["content"]
