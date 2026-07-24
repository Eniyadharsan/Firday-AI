"""DeepSeek Provider Adapter for FRIDAY.

This module implements the Provider_Adapter interface for DeepSeek's AI models.
DeepSeek provides an OpenAI-compatible API, making this adapter similar to the
OpenAI adapter but with DeepSeek-specific configuration.

Features:
- Chat completions (generate)
- Streaming responses (stream_generate)
- Message format translation (OpenAI-compatible)
- Tool/function calling support
- Health monitoring and configuration validation

Requirements: 6.1

The DeepSeek API is fully OpenAI-compatible, using the same request/response
format as OpenAI's chat completions API.
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


# DeepSeek supported models with their specifications
DEEPSEEK_MODELS: dict[str, dict[str, Any]] = {
    "deepseek-chat": {
        "name": "DeepSeek Chat",
        "context_window": 64000,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": False,
        "input_cost_per_1k": 0.00014,
        "output_cost_per_1k": 0.00028,
    },
    "deepseek-coder": {
        "name": "DeepSeek Coder",
        "context_window": 64000,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": False,
        "input_cost_per_1k": 0.00014,
        "output_cost_per_1k": 0.00028,
    },
}

# Default model if none specified
DEFAULT_MODEL = "deepseek-chat"

# DeepSeek API base URL (OpenAI-compatible)
DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"


class DeepSeek_Adapter(Provider_Adapter):
    """Provider adapter for DeepSeek AI models.
    
    This adapter implements the Provider_Adapter interface for DeepSeek's API,
    supporting deepseek-chat and deepseek-coder models. DeepSeek uses an
    OpenAI-compatible API, so this implementation is similar to OpenAI_Adapter.
    
    The adapter handles:
    - Message format translation from FRIDAY format to OpenAI chat format
    - Synchronous and streaming response generation
    - Tool/function calling translation
    - Error handling with rate limit retry-after extraction
    - Health monitoring and metrics tracking
    
    Attributes:
        _key_store: API_Key_Store instance for retrieving the DeepSeek API key
        _client: OpenAI client instance configured for DeepSeek (lazy initialized)
        _metrics: Request metrics for health monitoring
        _last_error: Most recent error message
        _last_error_time: Timestamp of the last error
    
    Example:
        from friday.modules.providers import API_Key_Store
        
        key_store = API_Key_Store()
        key_store.load_from_env()
        
        adapter = DeepSeek_Adapter(key_store)
        if adapter.is_configured():
            response = adapter.generate([
                {"role": "user", "content": "Hello!"}
            ])
            print(response.content)
    
    Requirements: 6.1
    """

    def __init__(self, key_store: "API_Key_Store") -> None:
        """Initialize the DeepSeek adapter.
        
        Args:
            key_store: API_Key_Store instance for retrieving the DeepSeek API key.
                The key should be loaded from the DEEPSEEK_API_KEY environment variable.
        """
        self._key_store = key_store
        self._client: Optional[Any] = None  # Lazy initialized openai.OpenAI client
        self._metrics = ProviderMetrics()
        self._last_error: Optional[str] = None
        self._last_error_time: Optional[datetime] = None


    @property
    def provider_name(self) -> str:
        """Return the provider identifier.
        
        Returns:
            'deepseek' - the unique identifier for this provider.
        """
        return "deepseek"

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return the provider's capabilities.
        
        Returns:
            ProviderCapabilities describing DeepSeek's features including
            streaming, tool calling, and available models.
        """
        return ProviderCapabilities(
            supports_streaming=True,
            supports_tool_calling=True,
            supports_vision=False,  # DeepSeek doesn't support vision
            max_context_window=64000,  # DeepSeek's context window
            supported_models=list(DEEPSEEK_MODELS.keys()),
        )

    def _get_client(self) -> Any:
        """Get or create the OpenAI client configured for DeepSeek.
        
        Lazy initializes the OpenAI client on first use with DeepSeek's base URL.
        This allows the adapter to be created before the API key is necessarily available.
        
        Returns:
            The OpenAI client instance configured for DeepSeek.
            
        Raises:
            ImportError: If the openai library is not installed.
            ValueError: If the DeepSeek API key is not configured.
        """
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError:
                raise ImportError(
                    "The 'openai' library is required for DeepSeek integration. "
                    "Install it with: pip install openai"
                )
            
            api_key = self._key_store.get_key("deepseek")
            if not api_key:
                raise ValueError("DeepSeek API key is not configured")
            
            self._client = OpenAI(api_key=api_key, base_url=DEEPSEEK_API_BASE)
        
        return self._client


    def _reset_client(self) -> None:
        """Reset the OpenAI client.
        
        Forces re-creation of the client on next use. This is useful when
        the API key has been updated.
        """
        self._client = None

    def is_configured(self) -> bool:
        """Check if the provider has valid configuration.
        
        Checks if a DeepSeek API key is configured in the key store.
        Does not make network calls.
        
        Returns:
            True if a DeepSeek API key is configured, False otherwise.
            
        Requirement: 6.1
        """
        return self._key_store.is_configured("deepseek")

    def validate_config(self) -> tuple[bool, Optional[str]]:
        """Validate configuration by making a test API call.
        
        Attempts to list models from the DeepSeek API to verify the API key
        is valid and the service is accessible.
        
        Returns:
            Tuple of (is_valid, error_message) where:
            - is_valid: True if configuration is valid and API is accessible
            - error_message: None if valid, or a descriptive error message
            
        Requirement: 6.1
        """
        if not self.is_configured():
            return False, "DeepSeek API key is not configured"
        
        try:
            client = self._get_client()
            # Make a lightweight API call to verify the key
            client.models.list()
            return True, None
        except ImportError as e:
            return False, str(e)
        except Exception as e:
            error_message = self._extract_error_message(e)
            return False, error_message


    def _translate_messages(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Translate FRIDAY messages to OpenAI/DeepSeek chat completion format.
        
        Property 4: Message Format Translation
        For any valid FRIDAY message format (with role, content, and optional metadata)
        and for DeepSeek, the adapter's message translation SHALL produce a valid message
        in DeepSeek's (OpenAI-compatible) chat completion format.
        
        FRIDAY message format:
        {
            "role": "system" | "user" | "assistant" | "tool",
            "content": str,
            "name": Optional[str],  # For tool messages
            "tool_call_id": Optional[str],  # For tool result messages
        }
        
        DeepSeek message format (OpenAI-compatible):
        {
            "role": "system" | "user" | "assistant" | "tool",
            "content": str,
            "name": Optional[str],  # For tool messages
            "tool_call_id": Optional[str],  # For tool result messages
            "tool_calls": Optional[list],  # For assistant messages with tool calls
        }
        
        Args:
            messages: List of messages in FRIDAY format
            
        Returns:
            List of messages in DeepSeek chat completion format
        """
        deepseek_messages = []
        
        for msg in messages:
            deepseek_msg: dict[str, Any] = {
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            }
            
            # Handle tool/function messages
            if msg.get("role") == "tool":
                # Tool result messages need tool_call_id
                if "tool_call_id" in msg:
                    deepseek_msg["tool_call_id"] = msg["tool_call_id"]
                # Tool messages may have a name
                if "name" in msg:
                    deepseek_msg["name"] = msg["name"]
            
            # Handle assistant messages with tool calls
            if msg.get("role") == "assistant" and "tool_calls" in msg:
                deepseek_msg["tool_calls"] = msg["tool_calls"]
            
            # Handle function name for function messages (legacy format)
            if msg.get("role") == "function" and "name" in msg:
                deepseek_msg["name"] = msg["name"]
            
            deepseek_messages.append(deepseek_msg)
        
        return deepseek_messages


    def generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> GenerateResponse:
        """Generate a response from DeepSeek.
        
        Sends messages to DeepSeek's chat completions API and returns the response
        in FRIDAY's unified format.
        
        Args:
            messages: Chat messages in FRIDAY format
            model: Specific model to use (default: deepseek-chat)
            max_tokens: Maximum tokens in response (default: 1024)
            temperature: Sampling temperature 0.0-2.0 (default: 0.7)
            tools: Tool definitions in FRIDAY format (will be translated)
            
        Returns:
            GenerateResponse with unified response data
            
        Raises:
            ProviderError: On API errors with retry-after info if available
            
        Requirements: 6.1
        """
        start_time = time.time()
        model = model or DEFAULT_MODEL
        
        try:
            client = self._get_client()
            
            # Translate messages to DeepSeek format
            deepseek_messages = self._translate_messages(messages)
            
            # Build request parameters
            request_params: dict[str, Any] = {
                "model": model,
                "messages": deepseek_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            
            # Add tools if provided
            if tools:
                translated_tools = self.translate_tools(tools)
                if translated_tools:
                    request_params["tools"] = translated_tools
            
            # Make the API call
            response = client.chat.completions.create(**request_params)
            
            # Extract response data
            choice = response.choices[0]
            content = choice.message.content or ""
            finish_reason = choice.finish_reason or "stop"

            
            # Parse tool calls if present
            tool_calls = None
            if choice.message.tool_calls:
                tool_calls = self.parse_tool_calls(choice.message)
            
            # Extract usage information
            usage = {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
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
        """Stream response tokens from DeepSeek.
        
        Uses DeepSeek's streaming API to yield tokens as they arrive,
        providing a better user experience for longer responses.
        
        Args:
            messages: Chat messages in FRIDAY format
            model: Specific model to use (default: deepseek-chat)
            max_tokens: Maximum tokens in response (default: 1024)
            temperature: Sampling temperature 0.0-2.0 (default: 0.7)
            
        Yields:
            String tokens as they arrive from DeepSeek
        """
        start_time = time.time()
        model = model or DEFAULT_MODEL
        
        try:
            client = self._get_client()
            
            # Translate messages to DeepSeek format
            deepseek_messages = self._translate_messages(messages)
            
            # Create streaming request
            stream = client.chat.completions.create(
                model=model,
                messages=deepseek_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            
            # Yield tokens as they arrive
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            
            # Record success
            latency_ms = (time.time() - start_time) * 1000
            self._record_success(latency_ms)
            
        except Exception as e:
            # Record failure
            self._record_failure(str(e))
            raise self._create_provider_error(e)


    def translate_tools(self, friday_tools: list[dict]) -> list[dict]:
        """Translate FRIDAY tool definitions to DeepSeek's tools format.
        
        FRIDAY uses OpenAI-compatible format internally, and DeepSeek also uses
        the same format, so this is mostly a pass-through with validation.
        
        Property 5: Tool Definition Translation
        For any valid FRIDAY tool definition (in OpenAI-compatible format with
        name, description, parameters) and for DeepSeek, the translate_tools()
        method SHALL produce a valid tool definition in DeepSeek's native format.
        
        Args:
            friday_tools: Tools in FRIDAY/OpenAI-compatible format. Can be:
                - Full format: {"type": "function", "function": {...}}
                - Simplified format: {"name": ..., "description": ..., "parameters": ...}
            
        Returns:
            Tools in DeepSeek's native format (OpenAI-compatible).
            Returns empty list for None/empty/invalid input.
        """
        # Handle None/empty input
        if not friday_tools:
            return []
        
        # Ensure we have a list
        if not isinstance(friday_tools, list):
            logger.warning(f"translate_tools expected list, got {type(friday_tools).__name__}")
            return []
        
        deepseek_tools = []
        
        for idx, tool in enumerate(friday_tools):
            # Skip None entries
            if tool is None:
                logger.warning(f"Skipping None tool at index {idx}")
                continue
            
            # Ensure tool is a dict
            if not isinstance(tool, dict):
                logger.warning(f"Skipping non-dict tool at index {idx}: {type(tool).__name__}")
                continue
            
            try:
                deepseek_tool = self._normalize_tool_definition(tool)
                if deepseek_tool:
                    deepseek_tools.append(deepseek_tool)
            except Exception as e:
                logger.warning(f"Failed to translate tool at index {idx}: {e}")
                continue
        
        return deepseek_tools


    def _normalize_tool_definition(self, tool: dict) -> Optional[dict]:
        """Normalize a single tool definition to DeepSeek/OpenAI format.
        
        Args:
            tool: Tool definition in any supported format
            
        Returns:
            Normalized tool in DeepSeek format, or None if invalid
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
                "type": "function",
                "function": {
                    "name": name.strip(),
                    "description": str(func_def.get("description", "")).strip(),
                    "parameters": self._normalize_parameters(func_def.get("parameters")),
                }
            }
        
        # Simplified format: {"name": ..., "description": ..., "parameters": ...}
        elif "name" in tool:
            name = tool.get("name")
            if not name or not isinstance(name, str):
                logger.warning(f"Tool has invalid 'name' field: {name}")
                return None
            
            return {
                "type": "function",
                "function": {
                    "name": name.strip(),
                    "description": str(tool.get("description", "")).strip(),
                    "parameters": self._normalize_parameters(tool.get("parameters")),
                }
            }
        
        # Unknown format
        logger.warning("Unrecognized tool format, missing 'name' or 'type'='function' with 'function' field")
        return None


    def _normalize_parameters(self, parameters: Any) -> dict:
        """Normalize tool parameters to a valid JSON Schema object.
        
        Args:
            parameters: Parameters definition (dict, None, or other)
            
        Returns:
            Valid JSON Schema object for DeepSeek/OpenAI
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
        """Parse tool calls from DeepSeek response to FRIDAY format.
        
        Property 6: Tool Call Parsing
        For any valid tool call response from DeepSeek, parse_tool_calls() SHALL
        produce a list of FRIDAY ToolCall objects with correctly extracted id,
        function_name, and arguments.
        
        Args:
            response: DeepSeek response which can be:
                - ChatCompletionMessage object with tool_calls attribute
                - Dict with "tool_calls" key
                - List of tool call dicts directly
                - None or empty (returns empty list)
            
        Returns:
            List of tool calls in FRIDAY's format:
            [{"id": str, "function": {"name": str, "arguments": dict}}]
            
            Returns empty list for None/empty/invalid input.
        """
        # Handle None/empty input
        if response is None:
            return []
        
        tool_calls = []
        raw_tool_calls = None
        
        # Handle ChatCompletionMessage object (from OpenAI SDK)
        if hasattr(response, 'tool_calls'):
            raw_tool_calls = response.tool_calls
        # Handle dict format with tool_calls key
        elif isinstance(response, dict) and "tool_calls" in response:
            raw_tool_calls = response["tool_calls"]
        # Handle list of tool calls directly
        elif isinstance(response, list):
            raw_tool_calls = response
        # Handle dict that might be a single tool call
        elif isinstance(response, dict) and ("id" in response or "function" in response):
            raw_tool_calls = [response]
        
        # No tool calls found
        if not raw_tool_calls:
            return []
        
        # Ensure we have a list
        if not isinstance(raw_tool_calls, list):
            logger.warning(f"Expected tool_calls to be a list, got {type(raw_tool_calls).__name__}")
            return []
        
        for idx, tc in enumerate(raw_tool_calls):
            try:
                parsed = self._parse_single_tool_call(tc)
                if parsed:
                    tool_calls.append(parsed)
            except Exception as e:
                logger.warning(f"Failed to parse tool call at index {idx}: {e}")
                continue
        
        return tool_calls


    def _parse_single_tool_call(self, tc: Any) -> Optional[dict]:
        """Parse a single tool call to FRIDAY format.
        
        Args:
            tc: A single tool call in DeepSeek/OpenAI format (object or dict)
            
        Returns:
            Parsed tool call dict or None if invalid
        """
        # Handle OpenAI SDK tool call object (has attributes)
        if hasattr(tc, 'id') and hasattr(tc, 'function'):
            tc_id = tc.id or ""
            func_name = tc.function.name if hasattr(tc.function, 'name') else ""
            raw_args = tc.function.arguments if hasattr(tc.function, 'arguments') else "{}"
            
            arguments = self._parse_tool_arguments(raw_args, func_name)
            
            return {
                "id": str(tc_id),
                "function": {
                    "name": str(func_name),
                    "arguments": arguments,
                }
            }
        
        # Handle dict format
        if isinstance(tc, dict):
            tc_id = tc.get("id", "")
            func_data = tc.get("function", {})
            
            if not isinstance(func_data, dict):
                logger.warning(f"Tool call 'function' field is not a dict: {type(func_data).__name__}")
                return None
            
            func_name = func_data.get("name", "")
            raw_args = func_data.get("arguments", "{}")
            
            # Skip if no function name
            if not func_name:
                logger.warning("Tool call missing function name")
                return None
            
            arguments = self._parse_tool_arguments(raw_args, func_name)
            
            return {
                "id": str(tc_id) if tc_id else "",
                "function": {
                    "name": str(func_name),
                    "arguments": arguments,
                }
            }
        
        logger.warning(f"Unrecognized tool call format: {type(tc).__name__}")
        return None


    def _parse_tool_arguments(self, raw_args: Any, func_name: str) -> dict:
        """Parse tool call arguments from raw format.
        
        Args:
            raw_args: Arguments in string JSON or dict format
            func_name: Function name (for logging)
            
        Returns:
            Parsed arguments dict (empty dict on error)
        """
        # Already a dict
        if isinstance(raw_args, dict):
            return raw_args
        
        # Empty/None
        if not raw_args:
            return {}
        
        # String (JSON)
        if isinstance(raw_args, str):
            # Handle empty string
            if not raw_args.strip():
                return {}
            
            try:
                parsed = json.loads(raw_args)
                if isinstance(parsed, dict):
                    return parsed
                else:
                    logger.warning(
                        f"Parsed arguments for '{func_name}' is not a dict: {type(parsed).__name__}"
                    )
                    return {}
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse tool call arguments for '{func_name}': {e}")
                return {}
        
        # Unknown type
        logger.warning(f"Unexpected arguments type for '{func_name}': {type(raw_args).__name__}")
        return {}


    def get_available_models(self) -> list[dict[str, Any]]:
        """Get list of available DeepSeek models.
        
        Returns information about supported models including context window,
        capabilities, and pricing.
        
        Returns:
            List of ModelInfo-like dicts with model specifications
        """
        models = []
        
        for model_id, spec in DEEPSEEK_MODELS.items():
            models.append({
                "id": model_id,
                "name": spec["name"],
                "provider": ProviderType.DEEPSEEK.value,
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
        
        # Try to extract message from API errors
        if hasattr(error, 'message'):
            return error.message
        if hasattr(error, 'body') and isinstance(error.body, dict):
            return error.body.get('message', error_str)
        
        return error_str


    def _create_provider_error(self, error: Exception) -> ProviderError:
        """Create a ProviderError from an exception.
        
        Handles API-specific error types with proper classification:
        - rate_limit: RateLimitError (429) with retry-after extraction
        - auth: AuthenticationError (401), PermissionDeniedError (403)
        - server: APIStatusError for 5xx errors (500, 502, 503)
        - timeout: APITimeoutError, ReadTimeout, ConnectTimeout
        - connection: APIConnectionError, network-related errors
        
        Args:
            error: The exception raised during the API call
            
        Returns:
            ProviderError with appropriate error_type, message, retry_after,
            and is_retryable flag
        """
        error_message = self._extract_error_message(error)
        error_type = "unknown"
        retry_after: Optional[int] = None
        is_retryable = True
        
        # Get error class name and full string representation for classification
        error_class_name = type(error).__name__
        error_str = str(error).lower()
        
        # Check for rate limit errors first (429 status)
        if "RateLimitError" in error_class_name or "rate_limit" in error_str or "429" in str(error):
            error_type = "rate_limit"
            retry_after = self._extract_retry_after(error)
            is_retryable = True
            
        # Check for authentication errors (401 status)
        elif "AuthenticationError" in error_class_name or "401" in str(error) or "invalid api key" in error_str:
            error_type = "auth"
            is_retryable = False  # Auth errors require manual intervention
            
        # Check for permission errors (403 status)
        elif "PermissionDeniedError" in error_class_name or "403" in str(error) or "permission" in error_str:
            error_type = "auth"  # Treat as auth error since it requires account changes
            is_retryable = False
            
        # Check for timeout errors
        elif ("Timeout" in error_class_name or "timeout" in error_str or 
              "ReadTimeout" in error_class_name or "ConnectTimeout" in error_class_name):
            error_type = "timeout"
            is_retryable = True

            
        # Check for connection errors
        elif ("APIConnectionError" in error_class_name or "ConnectionError" in error_class_name or
              "connection" in error_str or "network" in error_str or "unreachable" in error_str):
            error_type = "connection"
            is_retryable = True
            
        # Check for server errors (5xx status)
        elif ("APIStatusError" in error_class_name or "InternalServerError" in error_class_name or
              "500" in str(error) or "502" in str(error) or "503" in str(error) or 
              "504" in str(error) or "server error" in error_str):
            error_type = "server"
            is_retryable = True  # Server errors are typically transient
            
        # Check for bad request errors (400 status)
        elif "BadRequestError" in error_class_name or "400" in str(error):
            error_type = "bad_request"
            is_retryable = False  # Bad requests require fixing the request
            
        # Check for not found errors (404 status)
        elif "NotFoundError" in error_class_name or "404" in str(error):
            error_type = "not_found"
            is_retryable = False
            
        # Check for content filter errors
        elif "content_filter" in error_str or "content policy" in error_str:
            error_type = "content_filter"
            is_retryable = False
            
        # Check for context length errors
        elif "context_length" in error_str or "maximum context length" in error_str:
            error_type = "context_length"
            is_retryable = False  # Requires reducing input size
        
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
        2. The error message (often contains "Please retry after X seconds")
        
        Args:
            error: The rate limit exception
            
        Returns:
            Number of seconds to wait before retrying, or None if not available
        """
        import re
        
        retry_after: Optional[int] = None
        
        # Try to extract from response headers (OpenAI SDK exposes this)
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
            # Match patterns like "retry after 20 seconds" or "retry in 20s"
            patterns = [
                r'retry after (\d+)',
                r'retry in (\d+)',
                r'wait (\d+) second',
                r'Please try again in (\d+)',
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
