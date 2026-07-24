"""Data models for the multi-provider AI integration.

This module contains all data models, enums, and dataclasses used throughout
the provider abstraction layer. These models provide a unified interface for
working with multiple AI providers.

Models:
- ProviderStatus: Provider operational status enum
- ProviderType: Supported AI provider types enum
- ProviderCapabilities: Provider capability description
- GenerateResponse: Unified response format from any provider
- ProviderHealth: Health metrics for a provider
- ProviderMetrics: Request tracking metrics
- ProviderConfig: Configuration for a provider
- ModelInfo: Information about an available model
- ActiveProviderState: Current active provider state
- FridayMessage: Internal message format
- ConversationContext: Context for conversations
- StreamChunk: Streaming response chunk
- ToolCallRequest: Parsed tool call from provider response
- ProviderError: Provider error with retry info
- ModelManagerResponse: Response for Model Manager UI
- ActiveBadgeResponse: Response for Active Model Badge
- HealthResponse: Extended health response with provider metrics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class ProviderStatus(Enum):
    """Provider operational status.
    
    Indicates the current operational state of a provider:
    - OPERATIONAL: Provider is functioning normally
    - DEGRADED: Provider has >50% error rate over 10 requests
    - UNAVAILABLE: Provider has 5 consecutive failures
    - NOT_CONFIGURED: Provider API key is not configured
    """
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"


class ProviderType(Enum):
    """Supported AI provider types."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    DEEPSEEK = "deepseek"
    GROK = "grok"
    OPENROUTER = "openrouter"
    CEREBRAS = "cerebras"


@dataclass
class ProviderCapabilities:
    """Describes what a provider supports.
    
    Attributes:
        supports_streaming: Whether the provider supports streaming responses
        supports_tool_calling: Whether the provider supports function/tool calling
        supports_vision: Whether the provider supports image inputs
        max_context_window: Maximum tokens the provider can handle in context
        supported_models: List of model identifiers supported by this provider
    """
    supports_streaming: bool = True
    supports_tool_calling: bool = True
    supports_vision: bool = False
    max_context_window: int = 8192
    supported_models: list[str] = field(default_factory=list)


@dataclass
class GenerateResponse:
    """Unified response from any provider.
    
    This dataclass normalizes responses from all providers into a consistent
    format that FRIDAY can work with regardless of the underlying provider.
    
    Attributes:
        content: The generated text content
        model: The model that generated this response
        provider: The provider identifier (e.g., 'openai', 'anthropic')
        usage: Token usage statistics with keys: prompt_tokens, completion_tokens, total_tokens
        tool_calls: Optional list of tool call requests from the response
        finish_reason: Why the generation stopped ('stop', 'length', 'tool_calls', etc.)
    """
    content: str
    model: str
    provider: str
    usage: dict[str, int]
    tool_calls: Optional[list[dict]] = None
    finish_reason: str = "stop"


@dataclass
class ProviderHealth:
    """Health metrics for a provider.
    
    Attributes:
        status: Current operational status of the provider
        latency_ms: Average response latency in milliseconds
        success_rate: Ratio of successful requests (0.0 to 1.0)
        error_rate: Ratio of failed requests (0.0 to 1.0)
        last_error: Most recent error message, if any
        last_checked: ISO timestamp of last health check
    """
    status: ProviderStatus
    latency_ms: float
    success_rate: float
    error_rate: float
    last_error: Optional[str] = None
    last_checked: Optional[str] = None


@dataclass
class ProviderMetrics:
    """Metrics tracked for provider health monitoring.
    
    Attributes:
        total_requests: Total number of requests made to this provider
        successful_requests: Number of successful requests
        failed_requests: Number of failed requests
        total_latency_ms: Sum of all response latencies (for calculating average)
        last_error: Most recent error message
        last_error_time: Timestamp of the most recent error
        consecutive_failures: Number of failures in a row (resets on success)
    """
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    consecutive_failures: int = 0

    @property
    def success_rate(self) -> float:
        """Calculate success rate as ratio of successful to total requests."""
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests

    @property
    def error_rate(self) -> float:
        """Calculate error rate as ratio of failed to total requests."""
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests

    @property
    def average_latency_ms(self) -> float:
        """Calculate average latency from total latency and successful requests."""
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency_ms / self.successful_requests


@dataclass
class ProviderConfig:
    """Configuration for a provider.
    
    Attributes:
        provider_type: The type of provider
        api_key_env: Environment variable name containing the API key
        base_url: Custom base URL for the API (for Ollama or custom endpoints)
        default_model: Default model to use if none specified
        enabled: Whether this provider is enabled
        extra_settings: Provider-specific additional settings
    """
    provider_type: ProviderType
    api_key_env: str
    base_url: Optional[str] = None
    default_model: Optional[str] = None
    enabled: bool = True
    extra_settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelInfo:
    """Information about an available model.
    
    Attributes:
        id: Unique model identifier
        name: Human-readable model name
        provider: Provider that offers this model
        context_window: Maximum context window size in tokens
        supports_streaming: Whether the model supports streaming
        supports_tool_calling: Whether the model supports tool/function calling
        supports_vision: Whether the model supports image inputs
        input_cost_per_1k: Cost in USD per 1000 input tokens
        output_cost_per_1k: Cost in USD per 1000 output tokens
    """
    id: str
    name: str
    provider: ProviderType
    context_window: int
    supports_streaming: bool = True
    supports_tool_calling: bool = True
    supports_vision: bool = False
    input_cost_per_1k: Optional[float] = None
    output_cost_per_1k: Optional[float] = None


@dataclass
class ActiveProviderState:
    """Current active provider state for badge display.
    
    Attributes:
        provider: The active provider type
        model: The active model name
        status: Current operational status
        latency_ms: Most recent response latency
        in_failover: Whether currently operating on a backup provider
        failover_from: Original provider if in failover mode
    """
    provider: ProviderType
    model: str
    status: ProviderStatus
    latency_ms: Optional[float] = None
    in_failover: bool = False
    failover_from: Optional[str] = None


@dataclass
class FridayMessage:
    """Internal message format used by FRIDAY.
    
    Attributes:
        role: Message role ('system', 'user', 'assistant', 'tool')
        content: The message content
        name: Tool name for tool messages
        tool_call_id: ID of the tool call this message responds to
        provider: Provider that generated this message (for assistant messages)
        model: Model that generated this message (for assistant messages)
        timestamp: ISO timestamp when the message was created
    """
    role: str
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    timestamp: Optional[str] = None


@dataclass
class ConversationContext:
    """Context injected into conversations.
    
    Attributes:
        user_id: User identifier
        session_id: Current session identifier
        long_term_memory: Relevant long-term memory context
        rag_context: Retrieved document context
        conversation_history: Previous messages in the conversation
    """
    user_id: str
    session_id: str
    long_term_memory: Optional[str] = None
    rag_context: Optional[str] = None
    conversation_history: list[FridayMessage] = field(default_factory=list)


@dataclass
class StreamChunk:
    """A chunk from streaming response.
    
    Attributes:
        content: Text content of this chunk
        is_final: Whether this is the last chunk
        tool_call_delta: Partial tool call data if present
    """
    content: str
    is_final: bool = False
    tool_call_delta: Optional[dict] = None


@dataclass
class ToolCallRequest:
    """Tool call parsed from provider response.
    
    Attributes:
        id: Unique identifier for this tool call
        function_name: Name of the function to call
        arguments: Parsed arguments for the function
        provider_format: Original provider format for debugging
    """
    id: str
    function_name: str
    arguments: dict[str, Any]
    provider_format: str


@dataclass
class ProviderError:
    """Error from a provider with retry info.
    
    Attributes:
        provider: Provider that returned the error
        error_type: Type of error ('rate_limit', 'auth', 'server', 'timeout', 'connection')
        message: Human-readable error message
        retry_after: Seconds to wait before retrying (if available)
        is_retryable: Whether the request can be retried
    """
    provider: str
    error_type: str
    message: str
    retry_after: Optional[int] = None
    is_retryable: bool = True


@dataclass
class ModelManagerResponse:
    """Response for Model Manager UI.
    
    Attributes:
        providers: List of providers with their status information
        active_provider: Currently active provider identifier
        active_model: Currently active model identifier
        session_usage: Token usage statistics for the current session
    """
    providers: list[dict[str, Any]]
    active_provider: str
    active_model: str
    session_usage: dict[str, int]


@dataclass
class ActiveBadgeResponse:
    """Response for Active Model Badge updates.
    
    Attributes:
        provider: Current provider identifier
        model: Current model identifier
        status: Status string ('operational', 'degraded', 'unavailable')
        status_color: Color code ('green', 'yellow', 'red')
        in_failover: Whether currently in failover mode
        failover_message: Optional message about failover state
    """
    provider: str
    model: str
    status: str
    status_color: str
    in_failover: bool
    failover_message: Optional[str] = None


@dataclass
class HealthResponse:
    """Extended health response with provider metrics.
    
    Attributes:
        status: Overall system status
        version: System version
        providers: Health metrics for each provider
        active_provider: Currently active provider identifier
        tool_calling_available: Whether tool calling is available
    """
    status: str
    version: str
    providers: dict[str, ProviderHealth]
    active_provider: str
    tool_calling_available: bool


def get_status_color(status: ProviderStatus) -> str:
    """Map ProviderStatus to display color.
    
    Property 8: Status Color Mapping
    - OPERATIONAL -> green
    - DEGRADED -> yellow
    - UNAVAILABLE -> red
    - NOT_CONFIGURED -> gray
    
    Args:
        status: The provider status to map
        
    Returns:
        Color string for UI display
    """
    color_map = {
        ProviderStatus.OPERATIONAL: "green",
        ProviderStatus.DEGRADED: "yellow",
        ProviderStatus.UNAVAILABLE: "red",
        ProviderStatus.NOT_CONFIGURED: "gray",
    }
    return color_map.get(status, "gray")
