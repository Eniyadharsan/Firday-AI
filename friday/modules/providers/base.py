"""Abstract base class for AI provider adapters.

This module defines the Provider_Adapter abstract base class that all AI provider
adapters must implement. The adapter pattern enables FRIDAY to communicate with
any supported AI provider through a consistent interface.

Each adapter is responsible for:
- Translating FRIDAY's unified message format to the provider's native API format
- Handling response parsing back to FRIDAY's unified format
- Managing provider-specific configuration and validation
- Reporting health metrics and capabilities

Requirements: 1.1, 1.2, 1.4
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Generator, Optional

if TYPE_CHECKING:
    from friday.modules.providers.models import (
        GenerateResponse,
        ProviderCapabilities,
        ProviderHealth,
    )


class Provider_Adapter(ABC):
    """Abstract base class for all AI provider adapters.
    
    Each adapter translates FRIDAY's unified message format to the provider's
    native API format and handles response parsing back to FRIDAY format.
    
    All concrete provider adapters (OpenAI, Anthropic, Gemini, etc.) must
    inherit from this class and implement all abstract methods and properties.
    
    The adapter pattern allows adding new providers without modifying core
    FRIDAY logic - each adapter handles provider-specific API translation.
    
    Abstract Properties:
        provider_name: Unique identifier for this provider (e.g., 'openai')
        capabilities: ProviderCapabilities describing what this provider supports
        
    Abstract Methods:
        is_configured: Check if the provider has valid configuration
        validate_config: Validate configuration by making a test API call
        generate: Generate a response from the provider
        stream_generate: Stream response tokens from the provider
        translate_tools: Translate FRIDAY tool definitions to provider format
        parse_tool_calls: Parse tool calls from provider response
        get_available_models: Get list of available models
        get_health: Get current health status and metrics
    
    Example:
        class OpenAI_Adapter(Provider_Adapter):
            @property
            def provider_name(self) -> str:
                return "openai"
            
            @property
            def capabilities(self) -> ProviderCapabilities:
                return ProviderCapabilities(
                    supports_streaming=True,
                    supports_tool_calling=True,
                    max_context_window=128000,
                    supported_models=["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"]
                )
            
            # ... implement remaining abstract methods
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier (e.g., 'openai', 'anthropic').
        
        This name is used as the unique identifier for this provider in the
        Provider_Registry and for logging/metrics purposes.
        
        Returns:
            A lowercase string identifier for this provider.
        """
        pass

    @property
    @abstractmethod
    def capabilities(self) -> "ProviderCapabilities":
        """Return the provider's capabilities.
        
        Describes what features this provider supports, including streaming,
        tool calling, vision, context window size, and available models.
        
        Returns:
            ProviderCapabilities instance describing this provider's features.
        """
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if the provider has valid configuration (API key, etc.).
        
        This method should check if all required configuration is present,
        such as API keys or host URLs, but should not make network calls.
        
        Returns:
            True if the provider has all required configuration, False otherwise.
        """
        pass

    @abstractmethod
    def validate_config(self) -> tuple[bool, Optional[str]]:
        """Validate configuration by making a test API call.
        
        Unlike is_configured(), this method should actually attempt to
        communicate with the provider's API to verify the configuration
        is correct and the service is accessible.
        
        Returns:
            Tuple of (is_valid, error_message) where:
            - is_valid: True if configuration is valid and API is accessible
            - error_message: None if valid, or a descriptive error message
        """
        pass

    @abstractmethod
    def generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> "GenerateResponse":
        """Generate a response from the provider.
        
        This is the primary method for non-streaming generation. It sends
        messages to the provider's API and returns the complete response.
        
        Args:
            messages: Chat messages in FRIDAY format. Each message is a dict
                with 'role' ('system', 'user', 'assistant', 'tool') and 'content'.
            model: Specific model to use. If None, uses the provider's default.
            max_tokens: Maximum tokens in the response (default: 1024).
            temperature: Sampling temperature from 0.0 to 2.0 (default: 0.7).
                Lower values are more deterministic, higher more creative.
            tools: Tool definitions in FRIDAY format (OpenAI-compatible).
                Will be translated to the provider's native format.
        
        Returns:
            GenerateResponse with unified response data including content,
            model used, provider name, token usage, and any tool calls.
        
        Raises:
            ProviderError: On API errors, with retry-after info if available.
        """
        pass

    @abstractmethod
    def stream_generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Generator[str, None, None]:
        """Stream response tokens from the provider.
        
        This method enables real-time streaming of the response, yielding
        tokens as they arrive from the provider. This provides a better
        user experience for longer responses.
        
        Args:
            messages: Chat messages in FRIDAY format. Each message is a dict
                with 'role' ('system', 'user', 'assistant', 'tool') and 'content'.
            model: Specific model to use. If None, uses the provider's default.
            max_tokens: Maximum tokens in the response (default: 1024).
            temperature: Sampling temperature from 0.0 to 2.0 (default: 0.7).
        
        Yields:
            String tokens as they arrive from the provider. The concatenation
            of all yielded tokens forms the complete response.
        
        Note:
            Tool calling is not supported in streaming mode for most providers.
            Use the non-streaming generate() method when tools are needed.
        """
        pass

    @abstractmethod
    def translate_tools(self, friday_tools: list[dict]) -> list[dict]:
        """Translate FRIDAY tool definitions to provider's native format.
        
        FRIDAY uses OpenAI-compatible tool definitions internally. This method
        converts those definitions to whatever format the provider's API expects.
        
        Args:
            friday_tools: Tools in OpenAI-compatible format. Each tool has:
                - type: "function"
                - function: {name, description, parameters (JSON Schema)}
        
        Returns:
            Tools in the provider's native format. The exact structure depends
            on the provider (e.g., Anthropic uses a different schema).
        
        Example:
            # Input (FRIDAY/OpenAI format):
            [{
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                        "required": ["location"]
                    }
                }
            }]
            
            # Output varies by provider
        """
        pass

    @abstractmethod
    def parse_tool_calls(self, response: Any) -> list[dict]:
        """Parse tool calls from provider response to FRIDAY format.
        
        When the provider's response includes tool/function calls, this method
        extracts them and converts them to FRIDAY's standard ToolCall format.
        
        Args:
            response: Raw provider response. The type varies by provider
                (could be a dict, a response object, etc.).
        
        Returns:
            List of tool calls in FRIDAY's format. Each tool call has:
                - id: Unique identifier for this call
                - function: {name, arguments (parsed dict)}
        
        Example:
            # Output format:
            [{
                "id": "call_abc123",
                "function": {
                    "name": "get_weather",
                    "arguments": {"location": "Seattle"}
                }
            }]
        """
        pass

    @abstractmethod
    def get_available_models(self) -> list[dict[str, Any]]:
        """Get list of available models for this provider.
        
        Returns information about all models this provider supports,
        including their capabilities and context window sizes.
        
        Returns:
            List of model info dicts. Each dict should contain:
                - id: Model identifier (e.g., "gpt-4o")
                - name: Human-readable name (e.g., "GPT-4 Opus")
                - context_window: Max context size in tokens
                - supports_streaming: Whether streaming is supported
                - supports_tool_calling: Whether tools are supported
                - supports_vision: Whether image inputs are supported
        
        Note:
            Some providers (like Ollama) may need to query their API to get
            the list of available models. Others may return a static list.
        """
        pass

    @abstractmethod
    def get_health(self) -> "ProviderHealth":
        """Get current health status and metrics.
        
        Returns the provider's current operational status along with
        performance metrics. This is used for monitoring and failover decisions.
        
        Returns:
            ProviderHealth with:
                - status: Current ProviderStatus (OPERATIONAL, DEGRADED, etc.)
                - latency_ms: Average response latency
                - success_rate: Ratio of successful requests
                - error_rate: Ratio of failed requests
                - last_error: Most recent error message (if any)
                - last_checked: Timestamp of last health check
        """
        pass
