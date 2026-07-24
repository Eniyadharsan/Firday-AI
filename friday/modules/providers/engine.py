"""Unified AI Engine for FRIDAY.

This module implements the central Unified_AI_Engine that provides a consistent
interface for sending prompts and receiving responses regardless of the underlying
AI provider. It handles provider routing, context enrichment, streaming normalization,
and coordinates with the Failover_Controller for resilient operation.

Features:
- Unified generate() method with context enrichment and provider routing
- Unified stream_generate() with normalized streaming format across providers
- Tool selection with select_tools() method
- Integration with memory and RAG modules for context injection
- Failover coordination on provider errors
- Streaming interruption handling with partial content recovery (Requirement 11.3)
- Markdown preservation in streamed content (Requirement 11.4)

Requirements: 1.1, 1.5, 11.1, 11.2, 11.3, 11.4

Property 1: Unified Response Format Consistency
For any valid message sent through the Unified_AI_Engine and for any configured
provider, the response SHALL contain all required fields (content, model, provider,
usage) in the unified GenerateResponse format.

Property 15: Streaming Format Normalization
For any provider's native streaming response format, stream_generate() SHALL yield
plain string tokens without provider-specific metadata or wrapper objects.

Property 16: Markdown Preservation in Streaming
For any markdown-formatted content yielded through streaming, the concatenation of
all yielded tokens SHALL preserve the original markdown structure (headers, lists,
code blocks, emphasis).
"""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generator, Iterator, Optional, Protocol

from friday.modules.providers.models import (
    ConversationContext,
    FridayMessage,
    GenerateResponse,
    ProviderError,
    ProviderStatus,
    StreamChunk,
)
from friday.modules.providers.conversation import ConversationHistoryManager

if TYPE_CHECKING:
    from friday.modules.providers.base import Provider_Adapter
    from friday.modules.providers.registry import Provider_Registry

logger = logging.getLogger(__name__)


class StreamingInterruptedError(Exception):
    """Exception raised when a streaming connection is interrupted.
    
    Attributes:
        partial_content: Content accumulated before the interruption.
        original_error: The original exception that caused the interruption.
    """
    
    def __init__(
        self, 
        partial_content: str, 
        original_error: Optional[Exception] = None,
        message: str = "Streaming connection interrupted"
    ):
        super().__init__(message)
        self.partial_content = partial_content
        self.original_error = original_error


@dataclass
class MarkdownState:
    """Tracks the state of open markdown constructs during streaming.
    
    This class helps ensure markdown formatting is preserved when a stream
    is interrupted by tracking which constructs are currently open.
    
    Attributes:
        in_code_block: Whether currently inside a fenced code block (```)
        code_block_lang: Language specifier for current code block
        in_inline_code: Whether currently inside inline code (`)
        list_indent_level: Current list indentation level
        open_emphasis: Stack of open emphasis markers (*, **, _, __)
    """
    in_code_block: bool = False
    code_block_lang: str = ""
    in_inline_code: bool = False
    list_indent_level: int = 0
    open_emphasis: list[str] = field(default_factory=list)
    
    def close_open_constructs(self) -> str:
        """Generate closing sequences for any open markdown constructs.
        
        Property 16: Markdown Preservation in Streaming
        When streaming is interrupted, close open markdown constructs
        gracefully to maintain document validity.
        
        Returns:
            String containing closing sequences for open constructs.
        """
        closings = []
        
        # Close open emphasis markers in reverse order
        for marker in reversed(self.open_emphasis):
            closings.append(marker)
        
        # Close inline code
        if self.in_inline_code:
            closings.append("`")
        
        # Close code block
        if self.in_code_block:
            closings.append("\n```")
        
        return "".join(closings)


class MarkdownPreserver:
    """Preserves markdown formatting during streaming.
    
    Tracks markdown construct state as tokens are yielded and can
    gracefully close open constructs on interruption.
    
    Property 16: Markdown Preservation in Streaming
    For any markdown-formatted content yielded through streaming, the
    concatenation of all yielded tokens SHALL preserve the original
    markdown structure (headers, lists, code blocks, emphasis).
    
    Requirements: 11.4
    """
    
    # Patterns for detecting markdown constructs
    CODE_BLOCK_START = re.compile(r'^```(\w*)$', re.MULTILINE)
    CODE_BLOCK_END = re.compile(r'^```$', re.MULTILINE)
    INLINE_CODE = re.compile(r'`')
    EMPHASIS_PATTERNS = [
        (re.compile(r'\*\*(?!\*)'), '**'),  # Bold
        (re.compile(r'(?<!\*)\*(?!\*)'), '*'),  # Italic single
        (re.compile(r'__(?!_)'), '__'),  # Bold underscore
        (re.compile(r'(?<!_)_(?!_)'), '_'),  # Italic underscore
    ]
    
    def __init__(self):
        """Initialize the markdown preserver."""
        self._state = MarkdownState()
        self._accumulated_content = ""
    
    @property
    def state(self) -> MarkdownState:
        """Get current markdown state."""
        return self._state
    
    @property
    def accumulated_content(self) -> str:
        """Get all accumulated content."""
        return self._accumulated_content
    
    def process_token(self, token: str) -> str:
        """Process a token and update markdown state.
        
        Args:
            token: The incoming token to process.
            
        Returns:
            The token (unmodified).
        """
        self._accumulated_content += token
        self._update_state(token)
        return token
    
    def _update_state(self, token: str) -> None:
        """Update markdown state based on the incoming token.
        
        Args:
            token: The token to analyze.
        """
        # Check for code block boundaries
        if not self._state.in_code_block:
            # Look for code block start
            match = self.CODE_BLOCK_START.search(token)
            if match:
                self._state.in_code_block = True
                self._state.code_block_lang = match.group(1) or ""
        else:
            # Look for code block end
            if self.CODE_BLOCK_END.search(token):
                self._state.in_code_block = False
                self._state.code_block_lang = ""
        
        # Only track other constructs if not in code block
        if not self._state.in_code_block:
            # Track inline code (count backticks)
            backtick_count = token.count('`')
            if backtick_count % 2 == 1:
                self._state.in_inline_code = not self._state.in_inline_code
            
            # Track emphasis only when not in inline code
            if not self._state.in_inline_code:
                self._track_emphasis(token)
    
    def _track_emphasis(self, token: str) -> None:
        """Track opening/closing emphasis markers.
        
        Args:
            token: The token to analyze for emphasis.
        """
        # Simple approach: count emphasis markers
        # More sophisticated tracking could be added if needed
        for pattern, marker in self.EMPHASIS_PATTERNS:
            matches = pattern.findall(token)
            for _ in matches:
                if marker in self._state.open_emphasis:
                    self._state.open_emphasis.remove(marker)
                else:
                    self._state.open_emphasis.append(marker)
    
    def get_graceful_close(self) -> str:
        """Get content to gracefully close open markdown constructs.
        
        Returns:
            String with closing sequences, or empty string if nothing to close.
        """
        return self._state.close_open_constructs()
    
    def get_partial_content_with_graceful_close(self) -> str:
        """Get accumulated content with gracefully closed markdown.
        
        Returns:
            Accumulated content with any open constructs closed.
        """
        closing = self.get_graceful_close()
        return self._accumulated_content + closing


@dataclass
class StreamingSession:
    """Manages a streaming session with interruption handling.
    
    Tracks accumulated content during streaming and provides graceful
    recovery when the connection is interrupted.
    
    Requirement 11.3: IF a streaming connection is interrupted, THEN THE
    Unified_AI_Engine SHALL attempt to resume or fail gracefully with
    partial content.
    
    Requirement 11.4: THE Unified_AI_Engine SHALL preserve markdown
    formatting in streamed content across all providers.
    
    Attributes:
        provider_name: Name of the provider being streamed from
        model: Model being used for generation
        started_at: Timestamp when streaming started
        markdown_preserver: Tracks and preserves markdown state
        is_interrupted: Whether the session was interrupted
        error: Error that caused interruption, if any
    """
    provider_name: Optional[str] = None
    model: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    markdown_preserver: MarkdownPreserver = field(default_factory=MarkdownPreserver)
    is_interrupted: bool = False
    error: Optional[Exception] = None
    
    @property
    def partial_content(self) -> str:
        """Get all content accumulated so far."""
        return self.markdown_preserver.accumulated_content
    
    @property
    def elapsed_time(self) -> float:
        """Get elapsed time since streaming started."""
        return time.time() - self.started_at
    
    def accumulate(self, token: str) -> str:
        """Accumulate a token and track markdown state.
        
        Args:
            token: The token to accumulate.
            
        Returns:
            The token (unmodified).
        """
        return self.markdown_preserver.process_token(token)
    
    def mark_interrupted(self, error: Optional[Exception] = None) -> None:
        """Mark this session as interrupted.
        
        Args:
            error: The exception that caused the interruption.
        """
        self.is_interrupted = True
        self.error = error
    
    def get_partial_result(self) -> str:
        """Get partial content with gracefully closed markdown.
        
        Returns:
            Content accumulated before interruption with markdown properly closed.
        """
        return self.markdown_preserver.get_partial_content_with_graceful_close()


@contextmanager
def streaming_session(
    provider_name: Optional[str] = None, 
    model: Optional[str] = None
) -> Iterator[StreamingSession]:
    """Context manager for streaming sessions with automatic interruption handling.
    
    Creates a StreamingSession that tracks accumulated content and markdown state.
    On interruption, raises StreamingInterruptedError with partial content.
    
    Args:
        provider_name: Name of the provider being used.
        model: Model being used for generation.
        
    Yields:
        StreamingSession instance for tracking the stream.
        
    Raises:
        StreamingInterruptedError: When the stream is interrupted, contains
            partial content accumulated before the interruption.
    
    Example:
        with streaming_session("openai", "gpt-4") as session:
            for token in provider_stream:
                yield session.accumulate(token)
    """
    session = StreamingSession(provider_name=provider_name, model=model)
    try:
        yield session
    except (GeneratorExit, KeyboardInterrupt) as e:
        # Client disconnected or user interrupted
        session.mark_interrupted(e)
        logger.info(
            f"Stream interrupted after {session.elapsed_time:.2f}s, "
            f"partial content length: {len(session.partial_content)}"
        )
        # For GeneratorExit, we can't raise a different exception
        # Just let it propagate
        raise
    except Exception as e:
        # Other errors (connection issues, provider errors, etc.)
        session.mark_interrupted(e)
        logger.warning(
            f"Stream error after {session.elapsed_time:.2f}s: {e}, "
            f"partial content length: {len(session.partial_content)}"
        )
        raise StreamingInterruptedError(
            partial_content=session.get_partial_result(),
            original_error=e,
            message=f"Streaming interrupted: {e}"
        )


class Failover_Controller_Protocol(Protocol):
    """Protocol for Failover_Controller dependency injection.
    
    This allows the engine to work with the actual Failover_Controller
    or a mock implementation for testing.
    """
    
    def handle_failure(
        self, failed_provider: str, error: str
    ) -> Optional["Provider_Adapter"]:
        """Handle provider failure and return next available backup."""
        ...
    
    def get_failover_status(self) -> dict[str, Any]:
        """Get current failover status for UI display."""
        ...


class MemoryModule_Protocol(Protocol):
    """Protocol for Memory module dependency injection.
    
    This defines the interface that memory modules must implement
    for long-term memory context injection. Memory modules retrieve
    relevant memories for a user/session to provide context to AI prompts.
    
    Requirements: 13.1
    """
    
    def get_relevant_memories(
        self, 
        user_id: str, 
        session_id: str, 
        query: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """Retrieve relevant long-term memories for context injection.
        
        Args:
            user_id: User identifier for memory retrieval.
            session_id: Session identifier for context.
            query: Optional query to filter relevant memories.
            max_tokens: Optional maximum token budget for memory context.
            
        Returns:
            Formatted memory context string, or None if no relevant memories.
        """
        ...


class RAGModule_Protocol(Protocol):
    """Protocol for RAG module dependency injection.
    
    This defines the interface that RAG (Retrieval-Augmented Generation)
    modules must implement for document context injection. RAG modules
    retrieve relevant document chunks to augment AI prompts with knowledge.
    
    Requirements: 13.2
    """
    
    def get_relevant_documents(
        self, 
        user_id: str, 
        session_id: str, 
        query: str,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """Retrieve relevant document context for RAG injection.
        
        Args:
            user_id: User identifier for document access control.
            session_id: Session identifier for context.
            query: Query to search for relevant documents.
            max_tokens: Optional maximum token budget for document context.
            
        Returns:
            Formatted document context string with references, or None if no relevant documents.
        """
        ...


@dataclass
class ToolSelectionResult:
    """Result from tool selection.
    
    Attributes:
        selected_tools: List of tools that were selected for the message
        confidence: Confidence score of the selection (0.0 to 1.0)
        reasoning: Optional explanation of why these tools were selected
        timed_out: Whether the selection timed out
    """
    selected_tools: list[dict] = field(default_factory=list)
    confidence: float = 1.0
    reasoning: Optional[str] = None
    timed_out: bool = False


class Unified_AI_Engine:
    """Central engine for AI provider communication.
    
    Provides a consistent interface for sending prompts and receiving responses
    regardless of the underlying provider. Handles:
    - Provider routing via Provider_Registry
    - Memory and RAG context injection
    - Tool definition translation
    - Streaming response normalization
    - Failover coordination
    - Conversation history management across provider switches (Requirements 13.3, 14.1-14.4)
    
    The engine ensures that all responses conform to the unified GenerateResponse
    format (Property 1) and that streaming yields plain string tokens across all
    providers (Property 15).
    
    Attributes:
        registry: Provider_Registry for managing provider adapters
        failover: Failover_Controller for handling provider failures
        memory: Optional memory module for long-term context injection
        rag: Optional RAG module for document context injection
        conversation_history: ConversationHistoryManager for tracking history across provider switches
    
    Example:
        from friday.modules.providers import Provider_Registry, API_Key_Store
        from friday.modules.providers.adapters import OpenAI_Adapter
        
        registry = Provider_Registry.get_instance()
        key_store = API_Key_Store()
        key_store.load_from_env()
        
        registry.register(OpenAI_Adapter(key_store))
        registry.set_active("openai", "gpt-4o")
        
        engine = Unified_AI_Engine(registry, failover_controller)
        
        response = engine.generate(
            messages=[{"role": "user", "content": "Hello!"}],
            user_id="user123",
            session_id="session456"
        )
        print(response.content)
    
    Requirements: 1.1, 1.5, 11.1, 11.2, 13.3, 14.1, 14.2, 14.3, 14.4
    """

    def __init__(
        self,
        registry: "Provider_Registry",
        failover_controller: Optional[Failover_Controller_Protocol] = None,
        memory_module: Optional[Any] = None,
        rag_module: Optional[Any] = None,
    ) -> None:
        """Initialize the Unified AI Engine.
        
        Args:
            registry: Provider_Registry instance for managing provider adapters.
            failover_controller: Optional Failover_Controller for handling provider
                failures. If None, failover is disabled and errors propagate directly.
            memory_module: Optional memory module for injecting long-term memory
                context into prompts. Can be added later via set_memory_module().
            rag_module: Optional RAG module for injecting document context into
                prompts. Can be added later via set_rag_module().
        """
        self.registry = registry
        self.failover = failover_controller
        self.memory = memory_module
        self.rag = rag_module
        
        # Conversation history manager for tracking history across provider switches
        # Requirements: 13.3, 14.1, 14.2, 14.3, 14.4
        self.conversation_history = ConversationHistoryManager()
        
        # Track the last request for context
        self._last_request_provider: Optional[str] = None
        self._last_request_model: Optional[str] = None

    def set_memory_module(self, memory_module: Any) -> None:
        """Set or update the memory module.
        
        Args:
            memory_module: Memory module instance for long-term context injection.
        """
        self.memory = memory_module

    def set_rag_module(self, rag_module: Any) -> None:
        """Set or update the RAG module.
        
        Args:
            rag_module: RAG module instance for document context injection.
        """
        self.rag = rag_module

    def generate(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        session_id: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: int = 1024,
        tools: Optional[list[dict]] = None,
        track_history: bool = True,
    ) -> GenerateResponse:
        """Generate a response with automatic context enrichment.
        
        Injects long-term memory and RAG context, then routes to the
        active provider. On failure, coordinates with Failover_Controller.
        Maintains conversation history across provider switches.
        
        Property 1: Unified Response Format Consistency
        For any valid message sent through the Unified_AI_Engine and for any
        configured provider, the response SHALL contain all required fields
        (content, model, provider, usage) in the unified GenerateResponse format.
        
        Property 19: Conversation History Preservation Across Provider Switches
        For any active conversation and for any sequence of provider switches,
        the complete conversation history SHALL remain intact and accessible.
        
        Args:
            messages: Chat messages in FRIDAY format. Each message is a dict
                with 'role' ('system', 'user', 'assistant', 'tool') and 'content'.
            user_id: User identifier for context retrieval.
            session_id: Session identifier for context retrieval.
            model: Specific model to use. If None, uses the active model.
            temperature: Sampling temperature (0.0 to 2.0). If None, uses
                provider default (typically 0.7).
            max_tokens: Maximum tokens in response (default: 1024).
            tools: Tool definitions in FRIDAY format (OpenAI-compatible).
            track_history: Whether to track messages in conversation history.
                Set to False for internal operations like tool selection.
            
        Returns:
            GenerateResponse with unified response data including content,
            model used, provider name, token usage, and any tool calls.
            
        Raises:
            ValueError: If no provider is configured or active.
            ProviderError: If the provider fails and no failover is available.
            
        Requirements: 1.1, 1.5, 13.3, 14.1, 14.2, 14.3
        """
        # Get the active adapter
        adapter = self.registry.get_active_adapter()
        if adapter is None:
            raise ValueError("No active provider configured")
        
        active_provider = self.registry.get_active_provider_name()
        active_model = model or self.registry.get_active_model()
        
        # Track incoming messages in conversation history (Requirement 14.1)
        if track_history:
            self._track_incoming_messages(session_id, messages)
        
        # Get conversation history to include in context (Requirement 14.2)
        # This ensures history is maintained across provider switches
        messages_with_history = self._include_conversation_history(
            session_id=session_id,
            new_messages=messages,
        )
        
        # Enrich messages with memory and RAG context
        enriched_messages = self._enrich_context(
            messages=messages_with_history,
            user_id=user_id,
            session_id=session_id,
        )
        
        # Set temperature default if not provided
        temp = temperature if temperature is not None else 0.7
        
        # Attempt generation with failover support
        response = self._generate_with_failover(
            adapter=adapter,
            provider_name=active_provider,
            messages=enriched_messages,
            model=active_model,
            max_tokens=max_tokens,
            temperature=temp,
            tools=tools,
        )
        
        # Track the response in conversation history with provider/model metadata
        # (Requirement 14.3: tag messages with provider and model)
        if track_history and response.content:
            self.conversation_history.add_assistant_message(
                session_id=session_id,
                content=response.content,
                provider=response.provider,
                model=response.model,
            )
        
        return response
    
    def _track_incoming_messages(
        self,
        session_id: str,
        messages: list[dict[str, str]],
    ) -> None:
        """Track incoming messages in conversation history.
        
        Adds new messages to the conversation history. Only adds messages
        that are not already tracked to avoid duplicates.
        
        Args:
            session_id: Session identifier
            messages: Incoming messages to track
            
        Requirements: 14.1
        """
        # Get current history to avoid duplicates
        current_history = self.conversation_history.get_history_as_dicts(
            session_id=session_id,
            include_metadata=False,
        )
        current_count = len(current_history)
        
        # Track only new messages (messages that aren't already in history)
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            # Skip system messages (they are typically added per-request)
            if role == "system":
                continue
            
            # Skip if this message is already in history
            # (compare by role and content)
            is_duplicate = False
            for existing in current_history:
                if existing.get("role") == role and existing.get("content") == content:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                if role == "user":
                    self.conversation_history.add_user_message(
                        session_id=session_id,
                        content=content,
                    )
                elif role == "tool":
                    self.conversation_history.add_tool_message(
                        session_id=session_id,
                        content=content,
                        name=msg.get("name", ""),
                        tool_call_id=msg.get("tool_call_id", ""),
                    )
    
    def _include_conversation_history(
        self,
        session_id: str,
        new_messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Include conversation history in messages for context preservation.
        
        This method ensures that when switching providers, the full conversation
        history is included in the new provider's context.
        
        Property 20: History Inclusion on Provider Switch
        When a provider switch occurs, the conversation history SHALL be
        included in the new provider's context.
        
        Args:
            session_id: Session identifier
            new_messages: New messages being sent
            
        Returns:
            Messages with conversation history included
            
        Requirements: 14.2
        """
        # If there's no existing history, just return the new messages
        if not self.conversation_history.has_history(session_id):
            return new_messages
        
        # Get existing history as messages for the provider
        history_messages = self.conversation_history.get_messages_for_provider(
            session_id=session_id,
        )
        
        # Extract system message from new_messages if present
        system_message = None
        non_system_new = []
        for msg in new_messages:
            if msg.get("role") == "system":
                system_message = msg
            else:
                non_system_new.append(msg)
        
        # Build the final messages list:
        # 1. System message (if any)
        # 2. Conversation history (excluding duplicates with new messages)
        # 3. New non-system messages
        result = []
        
        if system_message:
            result.append(system_message)
        
        # Add history, but avoid duplicating messages that are in new_messages
        # History already contains tracked messages, so we just need to avoid
        # adding the same user message that's in new_messages
        new_contents = {(m.get("role"), m.get("content")) for m in non_system_new}
        
        for hist_msg in history_messages:
            if hist_msg.get("role") == "system":
                continue  # Skip system messages from history
            key = (hist_msg.get("role"), hist_msg.get("content"))
            if key not in new_contents:
                result.append(hist_msg)
        
        # Add the new non-system messages
        result.extend(non_system_new)
        
        return result

    def _generate_with_failover(
        self,
        adapter: "Provider_Adapter",
        provider_name: Optional[str],
        messages: list[dict[str, str]],
        model: Optional[str],
        max_tokens: int,
        temperature: float,
        tools: Optional[list[dict]],
        attempted_providers: Optional[set[str]] = None,
    ) -> GenerateResponse:
        """Generate with failover handling.
        
        Attempts to generate using the provided adapter. On failure,
        coordinates with Failover_Controller to try backup providers.
        
        Args:
            adapter: Provider adapter to use
            provider_name: Name of the provider
            messages: Enriched messages
            model: Model to use
            max_tokens: Maximum tokens
            temperature: Sampling temperature
            tools: Tool definitions
            attempted_providers: Set of providers already attempted (for recursion)
            
        Returns:
            GenerateResponse from successful provider
            
        Raises:
            ProviderError: If all providers fail
        """
        if attempted_providers is None:
            attempted_providers = set()
        
        if provider_name:
            attempted_providers.add(provider_name)
        
        start_time = time.time()
        
        try:
            # Attempt generation
            response = adapter.generate(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                tools=tools,
            )
            
            # Record success metrics
            latency_ms = (time.time() - start_time) * 1000
            if provider_name:
                self.registry.record_request(
                    provider=provider_name,
                    success=True,
                    latency_ms=latency_ms,
                )
            
            # Track last request info
            self._last_request_provider = response.provider
            self._last_request_model = response.model
            
            # Ensure response has all required fields (Property 1)
            return self._ensure_valid_response(response)
            
        except Exception as e:
            # Record failure metrics
            latency_ms = (time.time() - start_time) * 1000
            error_message = str(e)
            
            if provider_name:
                self.registry.record_request(
                    provider=provider_name,
                    success=False,
                    latency_ms=latency_ms,
                    error=error_message,
                )
            
            logger.warning(f"Provider {provider_name} failed: {error_message}")
            
            # Attempt failover if controller is available
            if self.failover is not None and provider_name:
                backup_adapter = self.failover.handle_failure(
                    failed_provider=provider_name,
                    error=error_message,
                )
                
                if backup_adapter is not None:
                    backup_name = backup_adapter.provider_name
                    
                    # Avoid infinite loops by checking if we've already tried this provider
                    if backup_name not in attempted_providers:
                        logger.info(f"Failing over from {provider_name} to {backup_name}")
                        return self._generate_with_failover(
                            adapter=backup_adapter,
                            provider_name=backup_name,
                            messages=messages,
                            model=None,  # Use backup's default model
                            max_tokens=max_tokens,
                            temperature=temperature,
                            tools=tools,
                            attempted_providers=attempted_providers,
                        )
            
            # No failover available or all backups exhausted
            raise self._create_error_from_exception(e, provider_name)

    def _ensure_valid_response(self, response: GenerateResponse) -> GenerateResponse:
        """Ensure response has all required fields.
        
        Property 1: Unified Response Format Consistency
        For any valid message sent through the Unified_AI_Engine and for any
        configured provider, the response SHALL contain all required fields
        (content, model, provider, usage) in the unified GenerateResponse format.
        
        Args:
            response: The GenerateResponse to validate
            
        Returns:
            The same response if valid, or a corrected response with defaults
        """
        # Ensure content is a string
        content = response.content if response.content is not None else ""
        
        # Ensure model is a string
        model = response.model if response.model else "unknown"
        
        # Ensure provider is a string
        provider = response.provider if response.provider else "unknown"
        
        # Ensure usage is a dict with required keys
        usage = response.usage if response.usage else {}
        if "prompt_tokens" not in usage:
            usage["prompt_tokens"] = 0
        if "completion_tokens" not in usage:
            usage["completion_tokens"] = 0
        if "total_tokens" not in usage:
            usage["total_tokens"] = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
        
        # Return corrected response if any field was missing
        if (content != response.content or 
            model != response.model or 
            provider != response.provider or 
            usage != response.usage):
            return GenerateResponse(
                content=content,
                model=model,
                provider=provider,
                usage=usage,
                tool_calls=response.tool_calls,
                finish_reason=response.finish_reason or "stop",
            )
        
        return response

    def stream_generate(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        session_id: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: int = 1024,
        track_history: bool = True,
    ) -> Generator[str, None, None]:
        """Stream tokens with unified format across all providers.
        
        Property 15: Streaming Format Normalization
        For any provider's native streaming response format, stream_generate()
        SHALL yield plain string tokens without provider-specific metadata or
        wrapper objects.
        
        Property 19: Conversation History Preservation Across Provider Switches
        For any active conversation and for any sequence of provider switches,
        the complete conversation history SHALL remain intact and accessible.
        
        Requirement 11.2: WHEN streaming is active, THE Unified_AI_Engine SHALL
        yield tokens to the frontend as they arrive without buffering.
        
        Args:
            messages: Chat messages in FRIDAY format.
            user_id: User identifier for context retrieval.
            session_id: Session identifier for context retrieval.
            model: Specific model to use. If None, uses the active model.
            temperature: Sampling temperature (0.0 to 2.0). If None, uses
                provider default.
            max_tokens: Maximum tokens in response (default: 1024).
            track_history: Whether to track messages in conversation history.
            
        Yields:
            Plain string tokens as they arrive from the provider.
            
        Raises:
            ValueError: If no provider is configured or active.
            ProviderError: If the provider fails and no failover is available.
            
        Requirements: 1.5, 11.1, 11.2, 13.3, 14.1, 14.2, 14.3
        """
        # Get the active adapter
        adapter = self.registry.get_active_adapter()
        if adapter is None:
            raise ValueError("No active provider configured")
        
        active_provider = self.registry.get_active_provider_name()
        active_model = model or self.registry.get_active_model()
        
        # Track incoming messages in conversation history (Requirement 14.1)
        if track_history:
            self._track_incoming_messages(session_id, messages)
        
        # Get conversation history to include in context (Requirement 14.2)
        messages_with_history = self._include_conversation_history(
            session_id=session_id,
            new_messages=messages,
        )
        
        # Enrich messages with memory and RAG context
        enriched_messages = self._enrich_context(
            messages=messages_with_history,
            user_id=user_id,
            session_id=session_id,
        )
        
        # Set temperature default if not provided
        temp = temperature if temperature is not None else 0.7
        
        # Accumulate streamed content for history tracking
        accumulated_content: list[str] = []
        
        # Stream with failover support
        for token in self._stream_with_failover(
            adapter=adapter,
            provider_name=active_provider,
            messages=enriched_messages,
            model=active_model,
            max_tokens=max_tokens,
            temperature=temp,
        ):
            accumulated_content.append(token)
            yield token
        
        # Track the complete response in conversation history with provider/model metadata
        # (Requirement 14.3: tag messages with provider and model)
        if track_history and accumulated_content:
            full_content = "".join(accumulated_content)
            # Use the last request provider/model which was set during streaming
            final_provider = self._last_request_provider or active_provider
            final_model = self._last_request_model or active_model
            self.conversation_history.add_assistant_message(
                session_id=session_id,
                content=full_content,
                provider=final_provider or "unknown",
                model=final_model or "unknown",
            )

    def stream_with_partial_recovery(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        session_id: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: int = 1024,
    ) -> Generator[str, None, StreamingSession]:
        """Stream tokens with explicit partial content recovery support.
        
        Similar to stream_generate(), but catches StreamingInterruptedError
        and returns the partial content via the generator's return value.
        Callers can use this to handle interruptions gracefully.
        
        Requirement 11.3: IF a streaming connection is interrupted, THEN THE
        Unified_AI_Engine SHALL attempt to resume or fail gracefully with
        partial content.
        
        Requirement 11.4: THE Unified_AI_Engine SHALL preserve markdown
        formatting in streamed content across all providers.
        
        Args:
            messages: Chat messages in FRIDAY format.
            user_id: User identifier for context retrieval.
            session_id: Session identifier for context retrieval.
            model: Specific model to use. If None, uses the active model.
            temperature: Sampling temperature (0.0 to 2.0). If None, uses
                provider default.
            max_tokens: Maximum tokens in response (default: 1024).
            
        Yields:
            Plain string tokens as they arrive from the provider.
            
        Returns:
            StreamingSession containing accumulated content and state info
            when the stream completes or is interrupted.
            
        Example:
            gen = engine.stream_with_partial_recovery(messages, user_id, session_id)
            accumulated = ""
            try:
                for token in gen:
                    accumulated += token
                    print(token, end="", flush=True)
            except StreamingInterruptedError as e:
                # Handle interruption - partial content is available
                partial = e.partial_content
                print(f"\\n\\n[Interrupted with {len(partial)} chars]")
        """
        # Create a session to track state
        session = StreamingSession(
            provider_name=self.registry.get_active_provider_name(),
            model=model or self.registry.get_active_model(),
        )
        
        try:
            for token in self.stream_generate(
                messages=messages,
                user_id=user_id,
                session_id=session_id,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                session.accumulate(token)
                yield token
        except StreamingInterruptedError as e:
            # Propagate the error - caller can access partial content via the exception
            raise
        except GeneratorExit:
            # Client disconnected - mark session and re-raise
            session.mark_interrupted()
            raise
        
        return session

    def _stream_with_failover(
        self,
        adapter: "Provider_Adapter",
        provider_name: Optional[str],
        messages: list[dict[str, str]],
        model: Optional[str],
        max_tokens: int,
        temperature: float,
        attempted_providers: Optional[set[str]] = None,
    ) -> Generator[str, None, None]:
        """Stream with failover handling and interruption recovery.
        
        Property 15: Streaming Format Normalization
        For any provider's native streaming response format, stream_generate()
        SHALL yield plain string tokens without provider-specific metadata or
        wrapper objects.
        
        Property 16: Markdown Preservation in Streaming
        For any markdown-formatted content yielded through streaming, the
        concatenation of all yielded tokens SHALL preserve the original
        markdown structure (headers, lists, code blocks, emphasis).
        
        Requirement 11.3: IF a streaming connection is interrupted, THEN THE
        Unified_AI_Engine SHALL attempt to resume or fail gracefully with
        partial content.
        
        Requirement 11.4: THE Unified_AI_Engine SHALL preserve markdown
        formatting in streamed content across all providers.
        
        Args:
            adapter: Provider adapter to use
            provider_name: Name of the provider
            messages: Enriched messages
            model: Model to use
            max_tokens: Maximum tokens
            temperature: Sampling temperature
            attempted_providers: Set of providers already attempted
            
        Yields:
            Plain string tokens
        """
        if attempted_providers is None:
            attempted_providers = set()
        
        if provider_name:
            attempted_providers.add(provider_name)
        
        start_time = time.time()
        
        # Create a streaming session to track content and markdown state
        session = StreamingSession(provider_name=provider_name, model=model)
        
        try:
            # Get the stream from the adapter
            stream = adapter.stream_generate(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            
            # Yield tokens as they arrive (Property 15 - normalize to plain strings)
            # Track content with markdown state (Property 16)
            for token in stream:
                # Normalize to plain string
                if isinstance(token, str):
                    normalized_token = token
                elif hasattr(token, 'content'):
                    # Handle StreamChunk or similar objects
                    normalized_token = str(token.content)
                else:
                    # Fallback: convert to string
                    normalized_token = str(token)
                
                # Accumulate and track markdown state
                session.accumulate(normalized_token)
                yield normalized_token
            
            # Record success metrics
            latency_ms = (time.time() - start_time) * 1000
            if provider_name:
                self.registry.record_request(
                    provider=provider_name,
                    success=True,
                    latency_ms=latency_ms,
                )
            
            # Track last request info
            self._last_request_provider = provider_name
            self._last_request_model = model
            
        except GeneratorExit:
            # Client disconnected - this is a normal interruption
            # Requirement 11.3: Fail gracefully with partial content
            session.mark_interrupted()
            latency_ms = (time.time() - start_time) * 1000
            
            logger.info(
                f"Stream to {provider_name} interrupted by client after {latency_ms:.0f}ms, "
                f"partial content: {len(session.partial_content)} chars"
            )
            
            # Record as successful since we delivered partial content
            if provider_name and session.partial_content:
                self.registry.record_request(
                    provider=provider_name,
                    success=True,
                    latency_ms=latency_ms,
                )
            
            # Re-raise to properly close the generator
            raise
            
        except (ConnectionError, TimeoutError, OSError) as e:
            # Connection interruptions - try to recover gracefully
            # Requirement 11.3: Return partial content on interruption
            session.mark_interrupted(e)
            latency_ms = (time.time() - start_time) * 1000
            error_message = str(e)
            
            logger.warning(
                f"Stream connection to {provider_name} interrupted: {error_message}, "
                f"partial content: {len(session.partial_content)} chars"
            )
            
            if provider_name:
                self.registry.record_request(
                    provider=provider_name,
                    success=False,
                    latency_ms=latency_ms,
                    error=error_message,
                )
            
            # If we have partial content, yield graceful closing and finish
            if session.partial_content:
                graceful_close = session.markdown_preserver.get_graceful_close()
                if graceful_close:
                    yield graceful_close
                return
            
            # No content yet - attempt failover
            if self.failover is not None and provider_name:
                backup_adapter = self.failover.handle_failure(
                    failed_provider=provider_name,
                    error=error_message,
                )
                
                if backup_adapter is not None:
                    backup_name = backup_adapter.provider_name
                    
                    if backup_name not in attempted_providers:
                        logger.info(f"Failing over stream from {provider_name} to {backup_name}")
                        yield from self._stream_with_failover(
                            adapter=backup_adapter,
                            provider_name=backup_name,
                            messages=messages,
                            model=None,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            attempted_providers=attempted_providers,
                        )
                        return
            
            # No failover or all backups exhausted
            raise StreamingInterruptedError(
                partial_content=session.get_partial_result(),
                original_error=e,
                message=f"Streaming connection interrupted: {error_message}"
            )
            
        except Exception as e:
            # Other errors (API errors, etc.)
            session.mark_interrupted(e)
            latency_ms = (time.time() - start_time) * 1000
            error_message = str(e)
            
            if provider_name:
                self.registry.record_request(
                    provider=provider_name,
                    success=False,
                    latency_ms=latency_ms,
                    error=error_message,
                )
            
            logger.warning(f"Provider {provider_name} stream failed: {error_message}")
            
            # If we've already yielded content, gracefully close and finish
            # Requirement 11.3: Return partial content on interruption
            if session.partial_content:
                graceful_close = session.markdown_preserver.get_graceful_close()
                if graceful_close:
                    yield graceful_close
                
                # Raise with partial content info
                raise StreamingInterruptedError(
                    partial_content=session.get_partial_result(),
                    original_error=e,
                    message=f"Streaming failed with partial content: {error_message}"
                )
            
            # No content yet - attempt failover
            if self.failover is not None and provider_name:
                backup_adapter = self.failover.handle_failure(
                    failed_provider=provider_name,
                    error=error_message,
                )
                
                if backup_adapter is not None:
                    backup_name = backup_adapter.provider_name
                    
                    if backup_name not in attempted_providers:
                        logger.info(f"Failing over stream from {provider_name} to {backup_name}")
                        yield from self._stream_with_failover(
                            adapter=backup_adapter,
                            provider_name=backup_name,
                            messages=messages,
                            model=None,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            attempted_providers=attempted_providers,
                        )
                        return
            
            # No failover available or all backups exhausted
            raise self._create_error_from_exception(e, provider_name)

    def select_tools(
        self,
        message: str,
        tools: list[dict],
        timeout: float = 3.0,
    ) -> ToolSelectionResult:
        """Select tools using the active provider.
        
        Uses the AI provider to determine which tools are relevant for a given
        message. This is useful for pre-filtering tools before a full generation
        request.
        
        Args:
            message: The user's message to analyze for tool selection.
            tools: List of available tools in FRIDAY format.
            timeout: Maximum time in seconds to wait for selection (default: 3.0).
            
        Returns:
            ToolSelectionResult with selected tools and metadata.
            If the selection times out, returns empty tools with timed_out=True.
            
        Raises:
            ValueError: If no provider is configured or active.
        """
        # Get the active adapter
        adapter = self.registry.get_active_adapter()
        if adapter is None:
            raise ValueError("No active provider configured")
        
        # Check if provider supports tool calling
        if not adapter.capabilities.supports_tool_calling:
            logger.warning(
                f"Provider {adapter.provider_name} does not support tool calling, "
                "returning all tools"
            )
            return ToolSelectionResult(
                selected_tools=tools,
                confidence=0.5,
                reasoning="Provider does not support tool selection; returning all tools",
            )
        
        # If no tools provided, return empty result
        if not tools:
            return ToolSelectionResult(
                selected_tools=[],
                confidence=1.0,
                reasoning="No tools provided",
            )
        
        # Build a prompt for tool selection
        tool_names = [t.get("name", t.get("function", {}).get("name", "unknown")) for t in tools]
        selection_prompt = self._build_tool_selection_prompt(message, tool_names)
        
        try:
            # Use a quick generation to select tools
            import asyncio
            import concurrent.futures
            
            start_time = time.time()
            
            # Run with timeout using a thread pool
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    adapter.generate,
                    [{"role": "user", "content": selection_prompt}],
                    None,  # Use default model
                    256,   # Low max tokens for quick response
                    0.0,   # Zero temperature for deterministic selection
                    None,  # No tools needed for selection
                )
                
                try:
                    response = future.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    logger.warning(f"Tool selection timed out after {timeout}s")
                    return ToolSelectionResult(
                        selected_tools=tools,  # Return all tools on timeout
                        confidence=0.0,
                        reasoning="Tool selection timed out",
                        timed_out=True,
                    )
            
            # Parse the response to extract selected tool names
            selected_names = self._parse_tool_selection_response(response.content, tool_names)
            
            # Filter tools to only selected ones
            selected_tools = [
                t for t in tools
                if self._get_tool_name(t) in selected_names
            ]
            
            elapsed = time.time() - start_time
            
            return ToolSelectionResult(
                selected_tools=selected_tools if selected_tools else tools,
                confidence=0.8 if selected_tools else 0.5,
                reasoning=f"Selected {len(selected_tools)} of {len(tools)} tools in {elapsed:.2f}s",
            )
            
        except Exception as e:
            logger.warning(f"Tool selection failed: {e}")
            # On error, return all tools
            return ToolSelectionResult(
                selected_tools=tools,
                confidence=0.0,
                reasoning=f"Tool selection failed: {e}",
            )

    def _build_tool_selection_prompt(self, message: str, tool_names: list[str]) -> str:
        """Build a prompt for tool selection.
        
        Args:
            message: User's message
            tool_names: List of available tool names
            
        Returns:
            Prompt string for the model
        """
        tools_list = ", ".join(tool_names)
        return f"""Given the following user message and list of available tools, identify which tools might be useful. Respond with ONLY a comma-separated list of tool names that are relevant. If no tools are relevant, respond with "NONE".

User message: {message}

Available tools: {tools_list}

Relevant tools:"""

    def _parse_tool_selection_response(
        self, 
        response: str, 
        available_tools: list[str]
    ) -> set[str]:
        """Parse tool names from the selection response.
        
        Args:
            response: Model's response text
            available_tools: List of valid tool names
            
        Returns:
            Set of selected tool names
        """
        if not response:
            return set()
        
        response = response.strip().upper()
        
        if response == "NONE":
            return set()
        
        # Parse comma-separated list
        available_set = {name.lower() for name in available_tools}
        selected = set()
        
        for name in response.split(","):
            name = name.strip().lower()
            if name in available_set:
                # Return original casing
                for orig in available_tools:
                    if orig.lower() == name:
                        selected.add(orig)
                        break
        
        return selected

    def _get_tool_name(self, tool: dict) -> str:
        """Extract tool name from a tool definition.
        
        Args:
            tool: Tool definition dict
            
        Returns:
            Tool name string
        """
        if "name" in tool:
            return tool["name"]
        if "function" in tool and isinstance(tool["function"], dict):
            return tool["function"].get("name", "unknown")
        return "unknown"

    def _enrich_context(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        session_id: str,
    ) -> list[dict[str, str]]:
        """Enrich messages with memory and RAG context.
        
        Injects long-term memory context and RAG document context into the
        conversation messages while respecting the provider's context window limit.
        
        Property 17: Context Injection
        For any available context (long-term memory or RAG documents) and for any
        provider, the context SHALL be present in the messages array sent to the
        provider's generate() method.
        
        Property 18: Context Window Limit Enforcement
        For any provider with a defined context_window limit and for any combination
        of messages, memory context, and RAG context, the total token count of the
        injected context SHALL NOT exceed the provider's context_window.
        
        Args:
            messages: Original messages
            user_id: User identifier for context retrieval
            session_id: Session identifier for context retrieval
            
        Returns:
            Messages with injected context (memory and RAG)
            
        Requirements: 13.1, 13.2, 13.4
        """
        # If no memory or RAG modules, return messages unchanged
        if self.memory is None and self.rag is None:
            return messages
        
        # Create a copy to avoid modifying the original
        enriched = list(messages)
        
        # Get provider's context window limit
        max_context_tokens = self._get_provider_context_limit()
        
        # Estimate current message token count
        current_tokens = self._estimate_messages_tokens(messages)
        
        # Reserve tokens for response (at least 1024 tokens for response)
        response_reserve = 1024
        available_tokens = max_context_tokens - current_tokens - response_reserve
        
        if available_tokens <= 0:
            # No room for additional context
            logger.warning(
                f"No available tokens for context injection. "
                f"Current: {current_tokens}, Max: {max_context_tokens}"
            )
            return enriched
        
        # Allocate tokens between memory and RAG
        # Split available tokens: 40% for memory, 60% for RAG (RAG often more relevant)
        memory_budget = int(available_tokens * 0.4)
        rag_budget = int(available_tokens * 0.6)
        
        context_parts: list[str] = []
        
        # 1. Retrieve long-term memory context
        if self.memory is not None:
            memory_context = self._get_memory_context(
                user_id=user_id,
                session_id=session_id,
                messages=messages,
                max_tokens=memory_budget,
            )
            if memory_context:
                context_parts.append(memory_context)
                # Update remaining budget for RAG
                memory_tokens_used = self._estimate_token_count(memory_context)
                rag_budget = available_tokens - memory_tokens_used
        
        # 2. Retrieve RAG document context
        if self.rag is not None and rag_budget > 0:
            rag_context = self._get_rag_context(
                user_id=user_id,
                session_id=session_id,
                messages=messages,
                max_tokens=rag_budget,
            )
            if rag_context:
                context_parts.append(rag_context)
        
        # 3. Inject context into messages
        if context_parts:
            enriched = self._inject_context_into_messages(enriched, context_parts)
        
        return enriched

    def _get_provider_context_limit(self) -> int:
        """Get the context window limit for the active provider.
        
        Returns:
            Maximum context window in tokens for the active provider,
            or a default of 8192 if unavailable.
        """
        adapter = self.registry.get_active_adapter()
        if adapter is None:
            return 8192  # Default fallback
        
        return adapter.capabilities.max_context_window

    def _estimate_token_count(self, text: str) -> int:
        """Estimate token count for text.
        
        Uses a simple heuristic: approximately 4 characters per token for English.
        This provides a reasonable estimate without requiring a tokenizer.
        
        Args:
            text: The text to estimate tokens for
            
        Returns:
            Estimated token count
        """
        if not text:
            return 0
        # Simple heuristic: ~4 characters per token for English text
        return len(text) // 4

    def _estimate_messages_tokens(self, messages: list[dict[str, str]]) -> int:
        """Estimate total token count for a list of messages.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            
        Returns:
            Estimated total token count
        """
        total = 0
        for msg in messages:
            # Count content tokens
            content = msg.get("content", "")
            total += self._estimate_token_count(content)
            # Add overhead for message structure (~4 tokens per message)
            total += 4
        return total

    def _get_memory_context(
        self,
        user_id: str,
        session_id: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> Optional[str]:
        """Retrieve long-term memory context for injection.
        
        Args:
            user_id: User identifier
            session_id: Session identifier
            messages: Current messages (for query extraction)
            max_tokens: Maximum token budget for memory
            
        Returns:
            Formatted memory context string, or None
            
        Requirements: 13.1
        """
        if self.memory is None:
            return None
        
        # Extract query from the last user message for relevance filtering
        query = self._extract_query_from_messages(messages)
        
        try:
            memory_context = self.memory.get_relevant_memories(
                user_id=user_id,
                session_id=session_id,
                query=query,
                max_tokens=max_tokens,
            )
            
            if memory_context:
                # Format the memory context with a clear header
                formatted = (
                    "[Long-term Memory Context]\n"
                    "The following information is from the user's long-term memory:\n\n"
                    f"{memory_context}\n"
                    "[End Memory Context]"
                )
                
                # Verify it fits within budget
                if self._estimate_token_count(formatted) <= max_tokens:
                    return formatted
                else:
                    # Truncate if needed
                    return self._truncate_context(formatted, max_tokens)
            
        except Exception as e:
            logger.warning(f"Failed to retrieve memory context: {e}")
        
        return None

    def _get_rag_context(
        self,
        user_id: str,
        session_id: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> Optional[str]:
        """Retrieve RAG document context for injection.
        
        Args:
            user_id: User identifier
            session_id: Session identifier
            messages: Current messages (for query extraction)
            max_tokens: Maximum token budget for RAG
            
        Returns:
            Formatted RAG context string with document references, or None
            
        Requirements: 13.2
        """
        if self.rag is None:
            return None
        
        # Extract query from the last user message
        query = self._extract_query_from_messages(messages)
        
        if not query:
            return None
        
        try:
            rag_context = self.rag.get_relevant_documents(
                user_id=user_id,
                session_id=session_id,
                query=query,
                max_tokens=max_tokens,
            )
            
            if rag_context:
                # Format the RAG context with a clear header
                formatted = (
                    "[Retrieved Document Context]\n"
                    "The following information was retrieved from relevant documents:\n\n"
                    f"{rag_context}\n"
                    "[End Document Context]"
                )
                
                # Verify it fits within budget
                if self._estimate_token_count(formatted) <= max_tokens:
                    return formatted
                else:
                    # Truncate if needed
                    return self._truncate_context(formatted, max_tokens)
            
        except Exception as e:
            logger.warning(f"Failed to retrieve RAG context: {e}")
        
        return None

    def _extract_query_from_messages(
        self, 
        messages: list[dict[str, str]]
    ) -> Optional[str]:
        """Extract a query string from messages for context retrieval.
        
        Uses the last user message as the query, which is typically the
        most relevant for retrieving context.
        
        Args:
            messages: List of message dictionaries
            
        Returns:
            Query string from the last user message, or None
        """
        # Find the last user message
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "").strip()
                if content:
                    return content
        return None

    def _truncate_context(self, context: str, max_tokens: int) -> str:
        """Truncate context to fit within token budget.
        
        Preserves the start and end markers while truncating the middle
        content to fit within the token limit.
        
        Args:
            context: The context string to truncate
            max_tokens: Maximum token budget
            
        Returns:
            Truncated context string
        """
        # Calculate approximate character limit (4 chars per token)
        max_chars = max_tokens * 4
        
        if len(context) <= max_chars:
            return context
        
        # Truncate with indication that content was cut
        truncation_note = "\n[... content truncated to fit context window ...]\n"
        available_chars = max_chars - len(truncation_note)
        
        # Keep the first portion
        truncated = context[:available_chars] + truncation_note
        
        return truncated

    def _inject_context_into_messages(
        self,
        messages: list[dict[str, str]],
        context_parts: list[str],
    ) -> list[dict[str, str]]:
        """Inject context into the messages array.
        
        Context is injected into the system message if one exists,
        or prepended as a new system message.
        
        Property 17: Context Injection
        For any available context (long-term memory or RAG documents) and for any
        provider, the context SHALL be present in the messages array sent to the
        provider's generate() method.
        
        Args:
            messages: Original messages
            context_parts: List of context strings to inject
            
        Returns:
            Messages with injected context
        """
        if not context_parts:
            return messages
        
        # Combine all context parts
        combined_context = "\n\n".join(context_parts)
        
        # Create a copy of messages
        result = list(messages)
        
        # Find the system message
        system_idx = None
        for i, msg in enumerate(result):
            if msg.get("role") == "system":
                system_idx = i
                break
        
        if system_idx is not None:
            # Append context to existing system message
            existing_content = result[system_idx].get("content", "")
            result[system_idx] = {
                "role": "system",
                "content": f"{existing_content}\n\n{combined_context}",
            }
        else:
            # Prepend a new system message with context
            context_message = {
                "role": "system",
                "content": combined_context,
            }
            result.insert(0, context_message)
        
        return result

    def _create_error_from_exception(
        self, 
        e: Exception, 
        provider: Optional[str]
    ) -> ProviderError:
        """Create a ProviderError from an exception.
        
        Args:
            e: The caught exception
            provider: Provider name
            
        Returns:
            ProviderError with appropriate type and message
        """
        error_message = str(e)
        error_type = "unknown"
        retry_after = None
        is_retryable = True
        
        # Detect error types from message
        error_lower = error_message.lower()
        
        if "rate limit" in error_lower or "rate_limit" in error_lower:
            error_type = "rate_limit"
            # Try to extract retry-after from message
            import re
            match = re.search(r"retry.?after[:\s]+(\d+)", error_lower)
            if match:
                retry_after = int(match.group(1))
        elif "auth" in error_lower or "api key" in error_lower or "unauthorized" in error_lower:
            error_type = "auth"
            is_retryable = False
        elif "timeout" in error_lower:
            error_type = "timeout"
        elif "connection" in error_lower or "network" in error_lower:
            error_type = "connection"
        elif "server" in error_lower or "500" in error_message or "502" in error_message:
            error_type = "server"
        
        return ProviderError(
            provider=provider or "unknown",
            error_type=error_type,
            message=error_message,
            retry_after=retry_after,
            is_retryable=is_retryable,
        )

    def get_active_provider_info(self) -> dict[str, Any]:
        """Get information about the currently active provider.
        
        Returns:
            Dictionary with provider name, model, and status information.
        """
        adapter = self.registry.get_active_adapter()
        
        if adapter is None:
            return {
                "provider": None,
                "model": None,
                "status": ProviderStatus.NOT_CONFIGURED.value,
                "in_failover": False,
            }
        
        health = adapter.get_health()
        failover_status = self.failover.get_failover_status() if self.failover else {}
        
        return {
            "provider": adapter.provider_name,
            "model": self.registry.get_active_model(),
            "status": health.status.value,
            "latency_ms": health.latency_ms,
            "in_failover": failover_status.get("in_failover", False),
            "failover_from": failover_status.get("failover_from"),
        }

    # ========================================================================
    # Tool Calling Compatibility Layer
    # ========================================================================
    # 
    # These methods implement the tool calling compatibility layer as specified
    # in Requirements 12.1, 12.2, 12.3, and 12.4. The layer ensures FRIDAY's
    # tools work seamlessly with all providers by:
    # 
    # 1. Translating FRIDAY tool definitions to each provider's native format
    # 2. Parsing tool calls from provider responses to FRIDAY's standard format
    # 3. Providing a prompt-based fallback for providers without native support
    # 
    # Properties validated:
    # - Property 5: Tool Definition Translation
    # - Property 6: Tool Call Parsing

    def translate_tools_for_provider(
        self,
        friday_tools: list[dict],
        provider_name: Optional[str] = None,
    ) -> list[dict]:
        """Translate FRIDAY tool definitions to the provider's native format.
        
        Property 5: Tool Definition Translation
        For any valid FRIDAY tool definition (in OpenAI-compatible format with
        name, description, parameters) and for any provider that supports tool
        calling, the translate_tools() method SHALL produce a valid tool
        definition in that provider's native format.
        
        FRIDAY uses OpenAI-compatible tool format internally:
        {
            "type": "function",
            "function": {
                "name": str,
                "description": str,
                "parameters": {...}  # JSON Schema
            }
        }
        
        This method delegates to the adapter's translate_tools() method to
        convert to the provider's native format (OpenAI, Anthropic, Gemini, etc.).
        
        Args:
            friday_tools: Tool definitions in FRIDAY/OpenAI-compatible format.
                Can be the full format or simplified format:
                - Full: {"type": "function", "function": {...}}
                - Simplified: {"name": ..., "description": ..., "parameters": ...}
            provider_name: Optional specific provider to translate for.
                If None, uses the active provider.
                
        Returns:
            Tools in the provider's native format. Returns empty list if:
            - No tools provided
            - No provider is active/specified
            - Provider doesn't support tool calling
            
        Raises:
            ValueError: If specified provider is not registered.
            
        Requirements: 12.1, 12.4
        
        Example:
            # Translate tools for the active provider
            native_tools = engine.translate_tools_for_provider([
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get current weather",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {"type": "string"}
                            },
                            "required": ["location"]
                        }
                    }
                }
            ])
        """
        # Handle empty/None input
        if not friday_tools:
            return []
        
        # Get the adapter
        adapter = None
        if provider_name:
            adapter = self.registry.get_adapter(provider_name)
            if adapter is None:
                raise ValueError(f"Provider '{provider_name}' is not registered")
        else:
            adapter = self.registry.get_active_adapter()
        
        if adapter is None:
            logger.warning("No provider available for tool translation")
            return []
        
        # Check if provider supports tool calling
        if not adapter.capabilities.supports_tool_calling:
            logger.info(
                f"Provider {adapter.provider_name} does not support native tool calling, "
                "use execute_with_tools() for prompt-based fallback"
            )
            return []
        
        # Delegate to the adapter's translate_tools method
        try:
            return adapter.translate_tools(friday_tools)
        except Exception as e:
            logger.error(f"Failed to translate tools for {adapter.provider_name}: {e}")
            return []

    def parse_tool_calls_from_response(
        self,
        response: Any,
        provider_name: Optional[str] = None,
    ) -> list[dict]:
        """Parse tool calls from a provider response to FRIDAY's standard format.
        
        Property 6: Tool Call Parsing
        For any valid tool call response from any provider, parse_tool_calls()
        SHALL produce a list of FRIDAY ToolCall objects with correctly extracted
        id, function_name, and arguments.
        
        FRIDAY's standard ToolCall format:
        {
            "id": str,           # Unique identifier for the tool call
            "function": {
                "name": str,     # Name of the function to call
                "arguments": {}  # Parsed arguments dict (not JSON string)
            }
        }
        
        This method normalizes tool calls from any provider's response format
        to FRIDAY's standard format, enabling consistent tool execution
        regardless of which provider generated the response.
        
        Args:
            response: Raw provider response. Can be:
                - GenerateResponse object with tool_calls attribute
                - Provider-specific response object (ChatCompletionMessage, etc.)
                - Dict with "tool_calls" key
                - None (returns empty list)
            provider_name: Optional specific provider to use for parsing.
                If None, uses the active provider.
                
        Returns:
            List of tool calls in FRIDAY's standard format. Returns empty list if:
            - No response provided
            - Response contains no tool calls
            - Provider is not available
            
        Raises:
            ValueError: If specified provider is not registered.
            
        Requirements: 12.2
        
        Example:
            # Parse tool calls from a generate response
            response = engine.generate(messages, user_id, session_id, tools=my_tools)
            tool_calls = engine.parse_tool_calls_from_response(response)
            
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                args = tc["function"]["arguments"]
                # Execute the tool...
        """
        # Handle None input
        if response is None:
            return []
        
        # If response is a GenerateResponse, extract tool_calls directly
        if isinstance(response, GenerateResponse):
            return response.tool_calls or []
        
        # Get the adapter for parsing
        adapter = None
        if provider_name:
            adapter = self.registry.get_adapter(provider_name)
            if adapter is None:
                raise ValueError(f"Provider '{provider_name}' is not registered")
        else:
            adapter = self.registry.get_active_adapter()
        
        if adapter is None:
            logger.warning("No provider available for tool call parsing")
            return []
        
        # Delegate to the adapter's parse_tool_calls method
        try:
            return adapter.parse_tool_calls(response)
        except Exception as e:
            logger.error(f"Failed to parse tool calls from {adapter.provider_name}: {e}")
            return []

    def execute_with_tools(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        session_id: str,
        tools: list[dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: int = 1024,
    ) -> GenerateResponse:
        """Generate a response with tool calling support.
        
        This method handles tool-enabled generation with automatic fallback
        for providers that don't support native tool calling. For providers
        with native tool support, it uses the adapter's translate_tools()
        method. For providers without support, it uses prompt-based extraction.
        
        Requirement 12.3: IF a provider does not support tool calling, THEN
        THE Unified_AI_Engine SHALL use prompt-based tool extraction as fallback.
        
        Requirement 12.4: THE Unified_AI_Engine SHALL support tool calling for
        OpenAI, Anthropic, Gemini, and OpenRouter providers.
        
        Args:
            messages: Chat messages in FRIDAY format.
            user_id: User identifier for context retrieval.
            session_id: Session identifier for context retrieval.
            tools: Tool definitions in FRIDAY format (OpenAI-compatible).
            model: Specific model to use. If None, uses the active model.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens in response.
            
        Returns:
            GenerateResponse with content and any tool calls in FRIDAY format.
            Tool calls are normalized regardless of whether native or prompt-based
            extraction was used.
            
        Raises:
            ValueError: If no provider is configured or active.
            ProviderError: If the provider fails and no failover is available.
            
        Requirements: 12.1, 12.2, 12.3, 12.4
        
        Example:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get current weather for a location",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {"type": "string", "description": "City name"}
                            },
                            "required": ["location"]
                        }
                    }
                }
            ]
            
            response = engine.execute_with_tools(
                messages=[{"role": "user", "content": "What's the weather in Seattle?"}],
                user_id="user123",
                session_id="session456",
                tools=tools
            )
            
            if response.tool_calls:
                for tc in response.tool_calls:
                    print(f"Call {tc['function']['name']} with {tc['function']['arguments']}")
        """
        # Get the active adapter
        adapter = self.registry.get_active_adapter()
        if adapter is None:
            raise ValueError("No active provider configured")
        
        # Check if provider supports native tool calling
        if adapter.capabilities.supports_tool_calling:
            # Use native tool calling through the standard generate method
            logger.debug(f"Using native tool calling for {adapter.provider_name}")
            return self.generate(
                messages=messages,
                user_id=user_id,
                session_id=session_id,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
            )
        else:
            # Use prompt-based fallback
            logger.info(
                f"Provider {adapter.provider_name} does not support native tool calling, "
                "using prompt-based extraction"
            )
            return self._generate_with_prompt_tools(
                messages=messages,
                user_id=user_id,
                session_id=session_id,
                tools=tools,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    def _generate_with_prompt_tools(
        self,
        messages: list[dict[str, str]],
        user_id: str,
        session_id: str,
        tools: list[dict],
        model: Optional[str],
        temperature: Optional[float],
        max_tokens: int,
    ) -> GenerateResponse:
        """Generate with prompt-based tool extraction fallback.
        
        This is used for providers that don't support native tool calling.
        Tool definitions are included in the system prompt, and tool calls
        are extracted from the model's text response.
        
        Requirement 12.3: IF a provider does not support tool calling, THEN
        THE Unified_AI_Engine SHALL use prompt-based tool extraction as fallback.
        
        Args:
            messages: Chat messages
            user_id: User identifier
            session_id: Session identifier
            tools: Tool definitions
            model: Model to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            
        Returns:
            GenerateResponse with parsed tool calls (if any)
        """
        # Build tool descriptions for the prompt
        tool_prompt = self._build_tool_prompt(tools)
        
        # Inject tool instructions into messages
        augmented_messages = self._inject_tool_prompt(messages, tool_prompt)
        
        # Generate response without native tools
        response = self.generate(
            messages=augmented_messages,
            user_id=user_id,
            session_id=session_id,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=None,  # No native tools
        )
        
        # Parse tool calls from the text response
        extracted_tool_calls = self._extract_tool_calls_from_text(response.content, tools)
        
        # Return response with extracted tool calls
        if extracted_tool_calls:
            return GenerateResponse(
                content=response.content,
                model=response.model,
                provider=response.provider,
                usage=response.usage,
                tool_calls=extracted_tool_calls,
                finish_reason="tool_calls" if extracted_tool_calls else response.finish_reason,
            )
        
        return response

    def _build_tool_prompt(self, tools: list[dict]) -> str:
        """Build a prompt describing available tools.
        
        Creates a structured description of tools that can be injected into
        the system message for providers without native tool support.
        
        Args:
            tools: Tool definitions in FRIDAY format
            
        Returns:
            Formatted tool description string
        """
        if not tools:
            return ""
        
        tool_descriptions = []
        
        for tool in tools:
            # Extract tool info from either format
            if tool.get("type") == "function" and "function" in tool:
                func = tool["function"]
            else:
                func = tool
            
            name = func.get("name", "unknown")
            description = func.get("description", "No description")
            parameters = func.get("parameters", {})
            
            # Build parameter descriptions
            param_desc = ""
            props = parameters.get("properties", {})
            required = parameters.get("required", [])
            
            if props:
                param_lines = []
                for param_name, param_info in props.items():
                    param_type = param_info.get("type", "any")
                    param_description = param_info.get("description", "")
                    is_required = param_name in required
                    req_str = " (required)" if is_required else " (optional)"
                    param_lines.append(f"    - {param_name}: {param_type}{req_str} - {param_description}")
                param_desc = "\n" + "\n".join(param_lines)
            
            tool_descriptions.append(f"- {name}: {description}{param_desc}")
        
        return """You have access to the following tools:

{tools}

To use a tool, respond with a JSON object in this exact format:
```json
{{"tool_call": {{"name": "tool_name", "arguments": {{"arg1": "value1", "arg2": "value2"}}}}}}
```

You can make multiple tool calls by including multiple tool_call objects.
Only use tool_call format when you need to invoke a tool. Otherwise, respond normally.""".format(
            tools="\n".join(tool_descriptions)
        )

    def _inject_tool_prompt(
        self,
        messages: list[dict[str, str]],
        tool_prompt: str,
    ) -> list[dict[str, str]]:
        """Inject tool prompt into messages.
        
        Adds or appends to the system message to include tool descriptions
        for prompt-based tool calling.
        
        Args:
            messages: Original messages
            tool_prompt: Tool description prompt
            
        Returns:
            Messages with tool prompt injected
        """
        if not tool_prompt:
            return messages
        
        augmented = []
        has_system = False
        
        for msg in messages:
            if msg.get("role") == "system":
                # Append tool prompt to existing system message
                augmented.append({
                    "role": "system",
                    "content": msg.get("content", "") + "\n\n" + tool_prompt,
                })
                has_system = True
            else:
                augmented.append(msg.copy())
        
        # If no system message exists, create one
        if not has_system:
            augmented.insert(0, {
                "role": "system",
                "content": tool_prompt,
            })
        
        return augmented

    def _extract_tool_calls_from_text(
        self,
        content: str,
        tools: list[dict],
    ) -> list[dict]:
        """Extract tool calls from text response.
        
        Parses the model's text response to find tool call JSON objects
        when using prompt-based tool calling fallback.
        
        Args:
            content: Model's text response
            tools: Available tools (for validation)
            
        Returns:
            List of extracted tool calls in FRIDAY format
        """
        if not content:
            return []
        
        extracted_calls = []
        
        # Build set of valid tool names
        valid_names = set()
        for tool in tools:
            if tool.get("type") == "function" and "function" in tool:
                valid_names.add(tool["function"].get("name", ""))
            else:
                valid_names.add(tool.get("name", ""))
        
        # Pattern to find JSON blocks (code blocks or inline)
        # Match ```json...``` or ```...``` or raw JSON objects
        json_patterns = [
            r'```json\s*(.*?)```',  # ```json...```
            r'```\s*(.*?)```',       # ```...```
            r'\{[^{}]*"tool_call"[^{}]*\{[^{}]*\}[^{}]*\}',  # Inline tool_call
        ]
        
        for pattern in json_patterns[:2]:  # Code block patterns
            matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
            for match in matches:
                try:
                    data = json.loads(match.strip())
                    tool_call = self._parse_extracted_tool_call(data, valid_names)
                    if tool_call:
                        extracted_calls.append(tool_call)
                except json.JSONDecodeError:
                    continue
        
        # Try inline JSON pattern
        inline_matches = re.findall(json_patterns[2], content)
        for match in inline_matches:
            try:
                data = json.loads(match)
                tool_call = self._parse_extracted_tool_call(data, valid_names)
                if tool_call:
                    extracted_calls.append(tool_call)
            except json.JSONDecodeError:
                continue
        
        # Assign IDs if not present
        for idx, tc in enumerate(extracted_calls):
            if not tc.get("id"):
                tc["id"] = f"extracted_call_{idx}"
        
        return extracted_calls

    def _parse_extracted_tool_call(
        self,
        data: dict,
        valid_names: set[str],
    ) -> Optional[dict]:
        """Parse a single extracted tool call from JSON data.
        
        Args:
            data: Parsed JSON data
            valid_names: Set of valid tool names
            
        Returns:
            Parsed tool call dict or None if invalid
        """
        if not isinstance(data, dict):
            return None
        
        # Look for tool_call key
        tool_call_data = data.get("tool_call", data)
        if not isinstance(tool_call_data, dict):
            return None
        
        name = tool_call_data.get("name", "")
        arguments = tool_call_data.get("arguments", {})
        
        # Validate tool name
        if not name or name not in valid_names:
            return None
        
        # Ensure arguments is a dict
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        
        if not isinstance(arguments, dict):
            arguments = {}
        
        return {
            "id": tool_call_data.get("id", ""),
            "function": {
                "name": name,
                "arguments": arguments,
            }
        }

    def supports_tool_calling(self, provider_name: Optional[str] = None) -> bool:
        """Check if a provider supports native tool calling.
        
        Args:
            provider_name: Provider to check. If None, checks active provider.
            
        Returns:
            True if the provider supports native tool calling, False otherwise.
            
        Raises:
            ValueError: If specified provider is not registered.
        """
        adapter = None
        if provider_name:
            adapter = self.registry.get_adapter(provider_name)
            if adapter is None:
                raise ValueError(f"Provider '{provider_name}' is not registered")
        else:
            adapter = self.registry.get_active_adapter()
        
        if adapter is None:
            return False
        
        return adapter.capabilities.supports_tool_calling

    def get_tool_calling_providers(self) -> list[str]:
        """Get list of providers that support native tool calling.
        
        Returns:
            List of provider names that support tool calling.
            
        Requirement 12.4: THE Unified_AI_Engine SHALL support tool calling for
        OpenAI, Anthropic, Gemini, and OpenRouter providers.
        """
        providers_with_tools = []
        
        all_providers = self.registry.get_all_providers()
        for provider_info in all_providers:
            provider_name = provider_info.get("name")
            if provider_name:
                adapter = self.registry.get_adapter(provider_name)
                if adapter and adapter.capabilities.supports_tool_calling:
                    providers_with_tools.append(provider_name)
        
        return providers_with_tools

    # ========================================================================
    # Conversation History Management
    # ========================================================================
    # 
    # These methods provide access to conversation history that is maintained
    # across provider switches. History is tracked with provider and model
    # metadata so users can see which model generated each response.
    # 
    # Requirements: 13.3, 14.1, 14.2, 14.3, 14.4
    # Properties validated:
    # - Property 19: Conversation History Preservation Across Provider Switches
    # - Property 20: History Inclusion on Provider Switch
    # - Property 21: Message Provider Metadata

    def get_conversation_history(
        self,
        session_id: str,
        limit: Optional[int] = None,
        include_metadata: bool = False,
    ) -> list[dict[str, Any]]:
        """Get the conversation history for a session.
        
        Returns the conversation history, optionally with provider/model
        metadata included for each message.
        
        Property 19: Conversation History Preservation Across Provider Switches
        For any active conversation and for any sequence of provider switches,
        the complete conversation history SHALL remain intact and accessible.
        
        Args:
            session_id: Session identifier
            limit: Optional maximum number of messages to return
            include_metadata: If True, include provider/model metadata for
                assistant messages (for UI display per Requirement 14.4)
                
        Returns:
            List of message dictionaries. If include_metadata is True,
            assistant messages include 'provider', 'model', and 'timestamp' fields.
            
        Requirements: 14.1, 14.4
        
        Example:
            # Get history for display (with model info)
            history = engine.get_conversation_history("session123", include_metadata=True)
            for msg in history:
                if msg["role"] == "assistant":
                    print(f"[{msg.get('model', 'unknown')}]: {msg['content']}")
                else:
                    print(f"[{msg['role']}]: {msg['content']}")
        """
        return self.conversation_history.get_history_as_dicts(
            session_id=session_id,
            limit=limit,
            include_metadata=include_metadata,
        )

    def get_conversation_with_model_info(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Get conversation history with model information for UI display.
        
        Returns the complete conversation history with provider and model
        metadata included, allowing users to view which model generated
        each response.
        
        Property 21: Message Provider Metadata
        The Unified_AI_Engine SHALL tag each message in history with the
        provider and model that generated it.
        
        Args:
            session_id: Session identifier
            
        Returns:
            List of message dictionaries with provider/model metadata
            
        Requirements: 14.3, 14.4
        
        Example:
            # Display conversation showing which model responded
            messages = engine.get_conversation_with_model_info("session123")
            for msg in messages:
                if msg["role"] == "assistant":
                    provider = msg.get("provider", "unknown")
                    model = msg.get("model", "unknown")
                    print(f"[{provider}/{model}]: {msg['content'][:50]}...")
        """
        return self.conversation_history.get_messages_with_model_info(session_id)

    def clear_conversation_history(self, session_id: str) -> None:
        """Clear the conversation history for a session.
        
        Removes all tracked messages from the specified session's history.
        
        Args:
            session_id: Session identifier to clear
        """
        self.conversation_history.clear_history(session_id)

    def has_conversation_history(self, session_id: str) -> bool:
        """Check if a session has any conversation history.
        
        Args:
            session_id: Session identifier to check
            
        Returns:
            True if the session has history, False otherwise
        """
        return self.conversation_history.has_history(session_id)

    def get_conversation_stats(self, session_id: str) -> dict[str, Any]:
        """Get statistics about a conversation session.
        
        Returns information about the conversation including message count,
        provider usage, and last active provider.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dictionary with conversation statistics:
            - message_count: Total number of messages
            - provider_usage: Dict mapping provider names to message counts
            - last_provider: Name of last provider used
            - last_model: Name of last model used
            
        Requirements: 14.4
        """
        return {
            "message_count": self.conversation_history.get_message_count(session_id),
            "provider_usage": self.conversation_history.get_provider_usage(session_id),
            "last_provider": self.conversation_history.get_last_provider(session_id),
            "last_model": self.conversation_history.get_last_model(session_id),
        }

    def get_active_sessions_count(self) -> int:
        """Get the number of active conversation sessions.
        
        Returns:
            Number of sessions with tracked conversation history
        """
        return self.conversation_history.get_session_count()
