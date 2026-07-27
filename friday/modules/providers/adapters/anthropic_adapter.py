"""Anthropic Provider Adapter for FRIDAY.

This module implements the Provider_Adapter interface for Anthropic's Claude models.
It supports Claude Opus, Sonnet, and Haiku models through Anthropic's
messages API.

Features:
- Chat completions (generate)
- Streaming responses (stream_generate)
- Message format translation to Anthropic messages format
- Tool/function calling (translate_tools, parse_tool_calls)
- Health monitoring and configuration validation

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6

Property 4: Message Format Translation
For any valid FRIDAY message format (with role, content, and optional metadata)
and for Anthropic, the adapter's message translation SHALL produce a valid message
in Anthropic's messages API format.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Generator, Optional

from friday.modules.providers.base import Provider_Adapter
from friday.modules.providers.models import (
    GenerateResponse,
    ProviderCapabilities,
    ProviderError,
    ProviderHealth,
    ProviderMetrics,
    ProviderStatus,
    ProviderType,
)

if TYPE_CHECKING:
    from friday.modules.providers.key_store import API_Key_Store

logger = logging.getLogger(__name__)


# Anthropic supported models with their specifications
ANTHROPIC_MODELS: dict[str, dict[str, Any]] = {
    "claude-3-opus-20240229": {
        "name": "Claude 3 Opus",
        "context_window": 200000,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
        "input_cost_per_1k": 0.015,
        "output_cost_per_1k": 0.075,
    },
    "claude-3-sonnet-20240229": {
        "name": "Claude 3 Sonnet",
        "context_window": 200000,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
        "input_cost_per_1k": 0.003,
        "output_cost_per_1k": 0.015,
    },
    "claude-3-haiku-20240307": {
        "name": "Claude 3 Haiku",
        "context_window": 200000,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
        "input_cost_per_1k": 0.00025,
        "output_cost_per_1k": 0.00125,
    },
    "claude-3-5-sonnet-20241022": {
        "name": "Claude 3.5 Sonnet",
        "context_window": 200000,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
        "input_cost_per_1k": 0.003,
        "output_cost_per_1k": 0.015,
    },
}

# Default model if none specified
DEFAULT_MODEL = "claude-3-5-sonnet-20241022"

# Anthropic API base URL
ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"


class Anthropic_Adapter(Provider_Adapter):
    """Provider adapter for Anthropic Claude models.
    
    This adapter implements the Provider_Adapter interface for Anthropic's API,
    supporting Claude Opus, Sonnet, and Haiku models.
    
    The adapter handles:
    - Message format translation from FRIDAY format to Anthropic messages format
    - System messages passed separately (not in messages array)
    - Synchronous and streaming response generation
    - Tool/function calling translation to Anthropic's tool_use format
    - Error handling with overloaded error detection
    - Health monitoring and metrics tracking
    
    Key differences from OpenAI:
    - System messages are passed as a separate 'system' parameter
    - Messages use different structure with content blocks
    - Streaming uses Server-Sent Events (SSE) format
    - Tool calls use 'tool_use' content blocks
    
    Attributes:
        _key_store: API_Key_Store instance for retrieving the Anthropic API key
        _client: Anthropic client instance (lazy initialized)
        _metrics: Request metrics for health monitoring
        _last_error: Most recent error message
        _last_error_time: Timestamp of the last error
    
    Example:
        from friday.modules.providers import API_Key_Store
        
        key_store = API_Key_Store()
        key_store.load_from_env()
        
        adapter = Anthropic_Adapter(key_store)
        if adapter.is_configured():
            response = adapter.generate([
                {"role": "user", "content": "Hello!"}
            ])
            print(response.content)
    
    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
    """

    def __init__(self, key_store: "API_Key_Store") -> None:
        """Initialize the Anthropic adapter.
        
        Args:
            key_store: API_Key_Store instance for retrieving the Anthropic API key.
                The key should be loaded from the ANTHROPIC_API_KEY environment variable.
        """
        self._key_store = key_store
        self._client: Optional[Any] = None  # Lazy initialized anthropic.Anthropic client
        self._metrics = ProviderMetrics()
        self._last_error: Optional[str] = None
        self._last_error_time: Optional[datetime] = None

    @property
    def provider_name(self) -> str:
        """Return the provider identifier.
        
        Returns:
            'anthropic' - the unique identifier for this provider.
        """
        return "anthropic"

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return the provider's capabilities.
        
        Returns:
            ProviderCapabilities describing Anthropic's features including
            streaming, tool calling, vision support, and available models.
        """
        return ProviderCapabilities(
            supports_streaming=True,
            supports_tool_calling=True,
            supports_vision=True,  # Claude 3 models support vision
            max_context_window=200000,  # Claude 3 context window
            supported_models=list(ANTHROPIC_MODELS.keys()),
        )

    def _get_client(self) -> Any:
        """Get or create the Anthropic client.
        
        Lazy initializes the Anthropic client on first use. This allows the adapter
        to be created before the API key is necessarily available.
        
        Returns:
            The Anthropic client instance.
            
        Raises:
            ImportError: If the anthropic library is not installed.
            ValueError: If the Anthropic API key is not configured.
        """
        if self._client is None:
            try:
                from anthropic import Anthropic
            except ImportError:
                raise ImportError(
                    "The 'anthropic' library is required for Anthropic integration. "
                    "Install it with: pip install anthropic"
                )
            
            api_key = self._key_store.get_key("anthropic")
            if not api_key:
                raise ValueError("Anthropic API key is not configured")
            
            self._client = Anthropic(api_key=api_key)
        
        return self._client

    def _reset_client(self) -> None:
        """Reset the Anthropic client.
        
        Forces re-creation of the client on next use. This is useful when
        the API key has been updated.
        """
        self._client = None

    def is_configured(self) -> bool:
        """Check if the provider has valid configuration.
        
        Checks if an Anthropic API key is configured in the key store.
        Does not make network calls.
        
        Returns:
            True if an Anthropic API key is configured, False otherwise.
            
        Requirement: 3.1
        """
        return self._key_store.is_configured("anthropic")

    def validate_config(self) -> tuple[bool, Optional[str]]:
        """Validate configuration by making a test API call.
        
        Attempts to make a minimal message call to verify the API key
        is valid and the service is accessible.
        
        Returns:
            Tuple of (is_valid, error_message) where:
            - is_valid: True if configuration is valid and API is accessible
            - error_message: None if valid, or a descriptive error message
            
        Requirement: 3.1
        """
        if not self.is_configured():
            return False, "Anthropic API key is not configured"
        
        try:
            client = self._get_client()
            # Make a minimal API call to verify the key
            # Count tokens is a lightweight endpoint for validation
            client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1,
                messages=[{"role": "user", "content": "test"}],
            )
            return True, None
        except ImportError as e:
            return False, str(e)
        except Exception as e:
            error_message = self._extract_error_message(e)
            return False, error_message

    def _translate_messages(
        self, messages: list[dict[str, str]]
    ) -> tuple[Optional[str], list[dict[str, Any]]]:
        """Translate FRIDAY messages to Anthropic messages API format.
        
        Property 4: Message Format Translation
        For any valid FRIDAY message format (with role, content, and optional metadata)
        and for Anthropic, the adapter's message translation SHALL produce a valid message
        in Anthropic's messages API format.
        
        Key differences from OpenAI:
        - System messages are extracted and passed separately
        - Messages use 'content' which can be a string or list of content blocks
        - Tool results use 'tool_result' content blocks with tool_use_id
        
        FRIDAY message format:
        {
            "role": "system" | "user" | "assistant" | "tool",
            "content": str,
            "name": Optional[str],  # For tool messages
            "tool_call_id": Optional[str],  # For tool result messages
        }
        
        Anthropic message format:
        {
            "role": "user" | "assistant",
            "content": str | list[content_block],
        }
        
        Args:
            messages: List of messages in FRIDAY format
            
        Returns:
            Tuple of (system_message, anthropic_messages) where:
            - system_message: Extracted system message content or None
            - anthropic_messages: List of messages in Anthropic format
        """
        system_message: Optional[str] = None
        anthropic_messages: list[dict[str, Any]] = []
        
        # Track tool results that need to be grouped with user messages
        pending_tool_results: list[dict[str, Any]] = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # Extract system message (Anthropic takes it as separate parameter)
            if role == "system":
                system_message = content
                continue

            # Handle tool result messages
            if role == "tool":
                tool_call_id = msg.get("tool_call_id", "")
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": content,
                }
                pending_tool_results.append(tool_result)
                continue
            
            # Handle assistant messages (may contain tool_use blocks)
            if role == "assistant":
                # First flush any pending tool results as a user message
                if pending_tool_results:
                    anthropic_messages.append({
                        "role": "user",
                        "content": pending_tool_results,
                    })
                    pending_tool_results = []
                
                # Check if assistant message has tool calls
                if "tool_calls" in msg and msg["tool_calls"]:
                    # Build content blocks: text + tool_use blocks
                    content_blocks: list[dict[str, Any]] = []
                    if content:
                        content_blocks.append({"type": "text", "text": content})
                    
                    for tc in msg["tool_calls"]:
                        tool_use_block = {
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": tc.get("function", {}).get("name", ""),
                            "input": tc.get("function", {}).get("arguments", {}),
                        }
                        content_blocks.append(tool_use_block)
                    
                    anthropic_messages.append({
                        "role": "assistant",
                        "content": content_blocks,
                    })
                else:
                    # Simple text message
                    anthropic_messages.append({
                        "role": "assistant",
                        "content": content,
                    })
                continue

            # Handle user messages
            if role == "user":
                # First flush any pending tool results
                if pending_tool_results:
                    # Combine tool results with the user message
                    content_blocks: list[dict[str, Any]] = list(pending_tool_results)
                    content_blocks.append({"type": "text", "text": content})
                    anthropic_messages.append({
                        "role": "user",
                        "content": content_blocks,
                    })
                    pending_tool_results = []
                else:
                    anthropic_messages.append({
                        "role": "user",
                        "content": content,
                    })
                continue
            
            # Handle function role (legacy format, treat as tool)
            if role == "function":
                tool_call_id = msg.get("tool_call_id", msg.get("name", ""))
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": content,
                }
                pending_tool_results.append(tool_result)
                continue
        
        # Flush any remaining tool results
        if pending_tool_results:
            anthropic_messages.append({
                "role": "user",
                "content": pending_tool_results,
            })
        
        return system_message, anthropic_messages

    def generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> GenerateResponse:
        """Generate a response from Anthropic.
        
        Sends messages to Anthropic's messages API and returns the response
        in FRIDAY's unified format.
        
        Args:
            messages: Chat messages in FRIDAY format
            model: Specific model to use (default: claude-3-5-sonnet-20241022)
            max_tokens: Maximum tokens in response (default: 1024)
            temperature: Sampling temperature 0.0-1.0 (default: 0.7)
            tools: Tool definitions in FRIDAY format (will be translated)
            
        Returns:
            GenerateResponse with unified response data
            
        Raises:
            ProviderError: On API errors with retry info if available
            
        Requirements: 3.1, 3.2, 3.3, 3.5
        """
        start_time = time.time()
        model = model or DEFAULT_MODEL
        
        try:
            client = self._get_client()
            
            # Translate messages to Anthropic format
            system_message, anthropic_messages = self._translate_messages(messages)
            
            # Build request parameters
            request_params: dict[str, Any] = {
                "model": model,
                "messages": anthropic_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            
            # Add system message if present
            if system_message:
                request_params["system"] = system_message
            
            # Add tools if provided
            if tools:
                translated_tools = self.translate_tools(tools)
                if translated_tools:
                    request_params["tools"] = translated_tools

            # Make the API call
            response = client.messages.create(**request_params)
            
            # Extract response data
            content = ""
            tool_calls = None
            
            # Process content blocks
            for block in response.content:
                if block.type == "text":
                    content += block.text
                elif block.type == "tool_use":
                    if tool_calls is None:
                        tool_calls = []
                    tool_calls.append({
                        "id": block.id,
                        "function": {
                            "name": block.name,
                            "arguments": block.input if isinstance(block.input, dict) else {},
                        }
                    })
            
            # Map stop_reason to finish_reason
            finish_reason_map = {
                "end_turn": "stop",
                "max_tokens": "length",
                "stop_sequence": "stop",
                "tool_use": "tool_calls",
            }
            finish_reason = finish_reason_map.get(response.stop_reason, "stop")
            
            # Extract usage information
            usage = {
                "prompt_tokens": response.usage.input_tokens if response.usage else 0,
                "completion_tokens": response.usage.output_tokens if response.usage else 0,
                "total_tokens": (
                    (response.usage.input_tokens if response.usage else 0) +
                    (response.usage.output_tokens if response.usage else 0)
                ),
            }
            
            # Record success metrics
            latency_ms = (time.time() - start_time) * 1000
            self._record_success(latency_ms)
            
            return GenerateResponse(
                content=content,
                model=model,
                provider=self.provider_name,
                usage=usage,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
            )
            
        except Exception as e:
            # Record failure and extract error info
            latency_ms = (time.time() - start_time) * 1000
            self._record_failure(str(e))
            raise self._create_provider_error(e)

    def stream_generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Generator[str, None, None]:
        """Stream response tokens from Anthropic.
        
        Uses Anthropic's streaming API to yield tokens as they arrive,
        providing a better user experience for longer responses.
        
        Anthropic streaming uses Server-Sent Events (SSE) with these event types:
        - message_start: Initial message metadata
        - content_block_start: Start of a content block
        - content_block_delta: Token chunk within a content block
        - content_block_stop: End of a content block
        - message_delta: Final message metadata (usage, stop_reason)
        - message_stop: End of message
        
        Args:
            messages: Chat messages in FRIDAY format
            model: Specific model to use (default: claude-3-5-sonnet-20241022)
            max_tokens: Maximum tokens in response (default: 1024)
            temperature: Sampling temperature 0.0-1.0 (default: 0.7)
            
        Yields:
            String tokens as they arrive from Anthropic
            
        Requirement: 3.4
        """
        start_time = time.time()
        model = model or DEFAULT_MODEL
        
        try:
            client = self._get_client()
            
            # Translate messages to Anthropic format
            system_message, anthropic_messages = self._translate_messages(messages)
            
            # Build request parameters
            request_params: dict[str, Any] = {
                "model": model,
                "messages": anthropic_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            
            # Add system message if present
            if system_message:
                request_params["system"] = system_message

            # Create streaming request
            with client.messages.stream(**request_params) as stream:
                for text in stream.text_stream:
                    yield text
            
            # Record success
            latency_ms = (time.time() - start_time) * 1000
            self._record_success(latency_ms)
            
        except Exception as e:
            # Record failure
            self._record_failure(str(e))
            raise self._create_provider_error(e)

    def translate_tools(self, friday_tools: list[dict]) -> list[dict]:
        """Translate FRIDAY tool definitions to Anthropic's tool_use format.
        
        FRIDAY uses OpenAI-compatible format internally. This method converts
        those definitions to Anthropic's tool format.
        
        Property 5: Tool Definition Translation
        For any valid FRIDAY tool definition (in OpenAI-compatible format with
        name, description, parameters) and for Anthropic, the translate_tools()
        method SHALL produce a valid tool definition in Anthropic's native format.
        
        Anthropic tool format:
        {
            "name": str,
            "description": str,
            "input_schema": {  # JSON Schema
                "type": "object",
                "properties": {...},
                "required": [...]
            }
        }
        
        Args:
            friday_tools: Tools in FRIDAY/OpenAI-compatible format. Can be:
                - Full format: {"type": "function", "function": {...}}
                - Simplified format: {"name": ..., "description": ..., "parameters": ...}
            
        Returns:
            Tools in Anthropic's native format. Returns empty list for invalid input.
            
        Requirement: 3.5, 12.1
        """
        if not friday_tools:
            return []
        
        if not isinstance(friday_tools, list):
            logger.warning(f"translate_tools expected list, got {type(friday_tools).__name__}")
            return []
        
        anthropic_tools = []

        for idx, tool in enumerate(friday_tools):
            if tool is None:
                logger.warning(f"Skipping None tool at index {idx}")
                continue
            
            if not isinstance(tool, dict):
                logger.warning(f"Skipping non-dict tool at index {idx}: {type(tool).__name__}")
                continue
            
            try:
                anthropic_tool = self._normalize_tool_definition(tool)
                if anthropic_tool:
                    anthropic_tools.append(anthropic_tool)
            except Exception as e:
                logger.warning(f"Failed to translate tool at index {idx}: {e}")
                continue
        
        return anthropic_tools

    def _normalize_tool_definition(self, tool: dict) -> Optional[dict]:
        """Normalize a single tool definition to Anthropic format.
        
        Args:
            tool: Tool definition in any supported format
            
        Returns:
            Normalized tool in Anthropic format, or None if invalid
        """
        # Full OpenAI format: {"type": "function", "function": {...}}
        if tool.get("type") == "function" and "function" in tool:
            func_def = tool["function"]
            if not isinstance(func_def, dict):
                logger.warning(f"Tool 'function' field is not a dict: {type(func_def).__name__}")
                return None
            
            name = func_def.get("name")
            if not name or not isinstance(name, str):
                logger.warning("Tool missing valid 'name' field in function definition")
                return None
            
            return {
                "name": name.strip(),
                "description": str(func_def.get("description", "")).strip(),
                "input_schema": self._normalize_parameters(func_def.get("parameters")),
            }

        # Simplified format: {"name": ..., "description": ..., "parameters": ...}
        elif "name" in tool:
            name = tool.get("name")
            if not name or not isinstance(name, str):
                logger.warning(f"Tool has invalid 'name' field: {name}")
                return None
            
            return {
                "name": name.strip(),
                "description": str(tool.get("description", "")).strip(),
                "input_schema": self._normalize_parameters(tool.get("parameters")),
            }
        
        # Unknown format
        logger.warning("Unrecognized tool format, missing 'name' or 'type'='function' with 'function' field")
        return None

    def _normalize_parameters(self, parameters: Any) -> dict:
        """Normalize tool parameters to a valid JSON Schema object.
        
        Args:
            parameters: Parameters definition (dict, None, or other)
            
        Returns:
            Valid JSON Schema object for Anthropic
        """
        default_schema = {
            "type": "object",
            "properties": {},
        }
        
        if parameters is None:
            return default_schema
        
        if not isinstance(parameters, dict):
            logger.warning(f"Tool parameters is not a dict: {type(parameters).__name__}, using default")
            return default_schema
        
        # Ensure 'type' is present and is 'object' for function parameters
        normalized = parameters.copy()
        if "type" not in normalized:
            normalized["type"] = "object"
        
        # Ensure 'properties' exists
        if "properties" not in normalized:
            normalized["properties"] = {}
        
        return normalized

    def parse_tool_calls(self, response: Any) -> list[dict]:
        """Parse tool calls from Anthropic response to FRIDAY format.
        
        Property 6: Tool Call Parsing
        For any valid tool call response from Anthropic, parse_tool_calls() SHALL
        produce a list of FRIDAY ToolCall objects with correctly extracted id,
        function_name, and arguments.
        
        Anthropic tool calls come as 'tool_use' content blocks:
        {
            "type": "tool_use",
            "id": "toolu_...",
            "name": "function_name",
            "input": {...}
        }
        
        Args:
            response: Anthropic response which can be:
                - Message object with content attribute
                - Dict with "content" key
                - List of content blocks directly
                - None or empty (returns empty list)
            
        Returns:
            List of tool calls in FRIDAY's format:
            [{"id": str, "function": {"name": str, "arguments": dict}}]
            
        Requirement: 12.2
        """
        if response is None:
            return []
        
        tool_calls = []
        content_blocks = None
        
        # Handle Anthropic Message object
        if hasattr(response, 'content'):
            content_blocks = response.content
        # Handle dict format with content key
        elif isinstance(response, dict) and "content" in response:
            content_blocks = response["content"]
        # Handle list of content blocks directly
        elif isinstance(response, list):
            content_blocks = response
        
        if not content_blocks:
            return []
        
        # Ensure we have a list
        if not isinstance(content_blocks, list):
            content_blocks = [content_blocks]

        for block in content_blocks:
            try:
                parsed = self._parse_single_tool_call(block)
                if parsed:
                    tool_calls.append(parsed)
            except Exception as e:
                logger.warning(f"Failed to parse tool call: {e}")
                continue
        
        return tool_calls

    def _parse_single_tool_call(self, block: Any) -> Optional[dict]:
        """Parse a single tool call content block to FRIDAY format.
        
        Args:
            block: A content block (object or dict)
            
        Returns:
            Parsed tool call dict or None if not a tool_use block
        """
        # Handle Anthropic SDK content block object
        if hasattr(block, 'type'):
            if block.type != "tool_use":
                return None
            
            return {
                "id": block.id if hasattr(block, 'id') else "",
                "function": {
                    "name": block.name if hasattr(block, 'name') else "",
                    "arguments": block.input if hasattr(block, 'input') and isinstance(block.input, dict) else {},
                }
            }
        
        # Handle dict format
        if isinstance(block, dict):
            if block.get("type") != "tool_use":
                return None
            
            return {
                "id": str(block.get("id", "")),
                "function": {
                    "name": str(block.get("name", "")),
                    "arguments": block.get("input", {}) if isinstance(block.get("input"), dict) else {},
                }
            }
        
        return None

    def get_available_models(self) -> list[dict[str, Any]]:
        """Get list of available Anthropic models.
        
        Returns information about supported models including context window,
        capabilities, and pricing.
        
        Returns:
            List of ModelInfo-like dicts with model specifications
            
        Requirement: 3.2
        """
        models = []
        
        for model_id, spec in ANTHROPIC_MODELS.items():
            models.append({
                "id": model_id,
                "name": spec["name"],
                "provider": ProviderType.ANTHROPIC.value,
                "context_window": spec["context_window"],
                "supports_streaming": spec["supports_streaming"],
                "supports_tool_calling": spec["supports_tool_calling"],
                "supports_vision": spec["supports_vision"],
                "input_cost_per_1k": spec.get("input_cost_per_1k"),
                "output_cost_per_1k": spec.get("output_cost_per_1k"),
            })
        
        return models

    def get_health(self) -> ProviderHealth:
        """Get current health status and metrics.
        
        Returns the adapter's current operational status along with
        performance metrics for monitoring and failover decisions.
        
        Returns:
            ProviderHealth with status, latency, success/error rates
        """
        # Determine status based on configuration and metrics
        if not self.is_configured():
            status = ProviderStatus.NOT_CONFIGURED
        elif self._metrics.consecutive_failures >= 5:
            status = ProviderStatus.UNAVAILABLE
        elif self._metrics.total_requests >= 10 and self._metrics.error_rate > 0.5:
            status = ProviderStatus.DEGRADED
        else:
            status = ProviderStatus.OPERATIONAL
        
        return ProviderHealth(
            status=status,
            latency_ms=self._metrics.average_latency_ms,
            success_rate=self._metrics.success_rate,
            error_rate=self._metrics.error_rate,
            last_error=self._last_error,
            last_checked=self._last_error_time.isoformat() if self._last_error_time else None,
        )

    def _record_success(self, latency_ms: float) -> None:
        """Record a successful request for metrics tracking."""
        self._metrics.total_requests += 1
        self._metrics.successful_requests += 1
        self._metrics.total_latency_ms += latency_ms
        self._metrics.consecutive_failures = 0

    def _record_failure(self, error: str) -> None:
        """Record a failed request for metrics tracking."""
        self._metrics.total_requests += 1
        self._metrics.failed_requests += 1
        self._metrics.consecutive_failures += 1
        self._last_error = error
        self._last_error_time = datetime.now()

    def _extract_error_message(self, error: Exception) -> str:
        """Extract a user-friendly error message from an exception."""
        error_str = str(error)
        
        # Try to extract message from Anthropic API errors
        if hasattr(error, 'message'):
            return error.message
        if hasattr(error, 'body') and isinstance(error.body, dict):
            return error.body.get('message', error_str)
        
        return error_str

    def _create_provider_error(self, error: Exception) -> ProviderError:
        """Create a ProviderError from an exception.
        
        Handles Anthropic-specific error types with proper classification:
        - rate_limit: RateLimitError with retry-after extraction
        - auth: AuthenticationError
        - server: APIStatusError for 5xx errors
        - overloaded: Anthropic's overloaded_error (treated as server for failover)
        - timeout: APITimeoutError
        - connection: APIConnectionError
        
        Args:
            error: The exception raised during the API call
            
        Returns:
            ProviderError with appropriate error_type, message, retry_after,
            and is_retryable flag
            
        Requirement: 3.6
        """
        error_message = self._extract_error_message(error)
        error_type = "unknown"
        retry_after: Optional[int] = None
        is_retryable = True
        
        # Get error class name for classification
        error_class_name = type(error).__name__
        error_str = str(error).lower()
        
        # Check for overloaded errors first (Anthropic-specific)
        # These are indicated by "overloaded" in the error message
        if "overloaded" in error_str or "OverloadedError" in error_class_name:
            error_type = "overloaded"
            is_retryable = True  # Should trigger failover
            
        # Check for rate limit errors
        elif "RateLimitError" in error_class_name or "rate_limit" in error_str or "429" in str(error):
            error_type = "rate_limit"
            retry_after = self._extract_retry_after(error)
            is_retryable = True

        # Check for authentication errors
        elif "AuthenticationError" in error_class_name or "401" in str(error) or "invalid api key" in error_str:
            error_type = "auth"
            is_retryable = False
            
        # Check for permission errors
        elif "PermissionDeniedError" in error_class_name or "403" in str(error):
            error_type = "auth"
            is_retryable = False
            
        # Check for timeout errors
        elif "Timeout" in error_class_name or "timeout" in error_str:
            error_type = "timeout"
            is_retryable = True
            
        # Check for connection errors
        elif "APIConnectionError" in error_class_name or "ConnectionError" in error_class_name or "connection" in error_str:
            error_type = "connection"
            is_retryable = True
            
        # Check for server errors
        elif "APIStatusError" in error_class_name or "InternalServerError" in error_class_name or "500" in str(error) or "502" in str(error) or "503" in str(error):
            error_type = "server"
            is_retryable = True
            
        # Check for bad request errors
        elif "BadRequestError" in error_class_name or "400" in str(error):
            error_type = "bad_request"
            is_retryable = False
            
        # Check for not found errors
        elif "NotFoundError" in error_class_name or "404" in str(error):
            error_type = "not_found"
            is_retryable = False
        
        return ProviderError(
            provider=self.provider_name,
            error_type=error_type,
            message=error_message,
            retry_after=retry_after,
            is_retryable=is_retryable,
        )

    def _extract_retry_after(self, error: Exception) -> Optional[int]:
        """Extract retry-after value from a rate limit error.
        
        Attempts to extract the retry-after value from:
        1. The response headers (Retry-After header)
        2. The error message
        
        Args:
            error: The rate limit exception
            
        Returns:
            Number of seconds to wait before retrying, or None if not available
        """
        import re
        
        retry_after: Optional[int] = None
        
        # Try to extract from response headers
        if hasattr(error, 'response'):
            response = error.response
            if hasattr(response, 'headers'):
                retry_after_str = response.headers.get('retry-after') or response.headers.get('Retry-After')
                if retry_after_str:
                    try:
                        retry_after = int(retry_after_str)
                    except ValueError:
                        pass
        
        # If not found in headers, try to extract from error message
        if retry_after is None:
            error_str = str(error)
            patterns = [
                r'retry after (\d+)',
                r'retry in (\d+)',
                r'wait (\d+) second',
                r'try again in (\d+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, error_str, re.IGNORECASE)
                if match:
                    try:
                        retry_after = int(match.group(1))
                        break
                    except ValueError:
                        pass
        
        return retry_after
