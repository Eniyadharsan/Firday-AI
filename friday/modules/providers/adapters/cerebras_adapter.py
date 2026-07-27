"""Cerebras Provider Adapter for FRIDAY.

This module implements the Provider_Adapter interface for Cerebras AI models.
Cerebras uses an OpenAI-compatible API format, making integration straightforward.

Features:
- Chat completions (generate)
- Streaming responses (stream_generate)
- Message format translation to OpenAI-compatible chat format
- Tool/function calling (translate_tools, parse_tool_calls)
- Health monitoring and configuration validation

Requirements: 6.5

This adapter refactors the existing Cerebras integration from friday/modules/llm.py
to conform to the Provider_Adapter interface pattern used by all other providers.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Generator, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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


# Cerebras supported models with their specifications
CEREBRAS_MODELS: dict[str, dict[str, Any]] = {
    "llama-4-scout-17b-16e-instruct": {
        "name": "Llama 4 Scout 17B",
        "context_window": 131072,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": False,
    },
    "llama3.1-8b": {
        "name": "Llama 3.1 8B",
        "context_window": 8192,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": False,
    },
    "llama3.1-70b": {
        "name": "Llama 3.1 70B",
        "context_window": 8192,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": False,
    },
    "qwen-3-32b": {
        "name": "Qwen 3 32B",
        "context_window": 32768,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": False,
    },
}

# Default model if none specified
DEFAULT_MODEL = "llama-4-scout-17b-16e-instruct"

# Cerebras API base URL
CEREBRAS_API_BASE = "https://api.cerebras.ai/v1"


class Cerebras_Adapter(Provider_Adapter):
    """Provider adapter for Cerebras AI models.
    
    This adapter implements the Provider_Adapter interface for Cerebras's API,
    which is OpenAI-compatible. It refactors the existing Cerebras integration
    from friday/modules/llm.py to conform to the unified adapter pattern.
    
    The adapter handles:
    - Message format translation from FRIDAY format to OpenAI-compatible format
    - Synchronous and streaming response generation
    - Tool/function calling translation
    - Error handling with retry logic
    - Health monitoring and metrics tracking
    
    Attributes:
        _key_store: API_Key_Store instance for retrieving the Cerebras API key
        _session: Requests session with connection pooling for efficient API calls
        _metrics: Request metrics for health monitoring
        _last_error: Most recent error message
        _last_error_time: Timestamp of the last error
    
    Example:
        from friday.modules.providers import API_Key_Store
        
        key_store = API_Key_Store()
        key_store.load_from_env()
        
        adapter = Cerebras_Adapter(key_store)
        if adapter.is_configured():
            response = adapter.generate([
                {"role": "user", "content": "Hello!"}
            ])
            print(response.content)
    
    Requirements: 6.5
    """

    def __init__(self, key_store: "API_Key_Store") -> None:
        """Initialize the Cerebras adapter.
        
        Args:
            key_store: API_Key_Store instance for retrieving the Cerebras API key.
                The key should be loaded from the CEREBRAS_API_KEY environment variable.
        """
        self._key_store = key_store
        self._session: Optional[requests.Session] = None
        self._metrics = ProviderMetrics()
        self._last_error: Optional[str] = None
        self._last_error_time: Optional[datetime] = None


    @property
    def provider_name(self) -> str:
        """Return the provider identifier.
        
        Returns:
            'cerebras' - the unique identifier for this provider.
        """
        return "cerebras"

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return the provider's capabilities.
        
        Returns:
            ProviderCapabilities describing Cerebras's features including
            streaming, tool calling, and available models.
        """
        return ProviderCapabilities(
            supports_streaming=True,
            supports_tool_calling=True,
            supports_vision=False,
            max_context_window=131072,  # Llama 4 Scout's context window
            supported_models=list(CEREBRAS_MODELS.keys()),
        )

    def _get_session(self) -> requests.Session:
        """Get or create a requests session with connection pooling.
        
        Lazy initializes the session on first use with proper headers
        and connection pooling configuration for optimal performance.
        
        Returns:
            The configured requests Session instance.
            
        Raises:
            ValueError: If the Cerebras API key is not configured.
        """
        if self._session is None:
            api_key = self._key_store.get_key("cerebras")
            if not api_key:
                raise ValueError("Cerebras API key is not configured")
            
            self._session = requests.Session()
            self._session.headers.update({
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            })
            
            # Configure connection pooling and retry logic
            adapter = HTTPAdapter(
                pool_connections=5,
                pool_maxsize=10,
                max_retries=Retry(
                    total=1,
                    backoff_factor=0.3,
                    status_forcelist=[502, 503, 504]
                ),
            )
            self._session.mount("https://", adapter)
        
        return self._session


    def _reset_session(self) -> None:
        """Reset the requests session.
        
        Forces re-creation of the session on next use. This is useful when
        the API key has been updated.
        """
        if self._session:
            self._session.close()
        self._session = None

    def is_configured(self) -> bool:
        """Check if the provider has valid configuration.
        
        Checks if a Cerebras API key is configured in the key store.
        Does not make network calls.
        
        Returns:
            True if a Cerebras API key is configured, False otherwise.
        """
        return self._key_store.is_configured("cerebras")

    def validate_config(self) -> tuple[bool, Optional[str]]:
        """Validate configuration by making a test API call.
        
        Attempts to list models from the Cerebras API to verify the API key
        is valid and the service is accessible.
        
        Returns:
            Tuple of (is_valid, error_message) where:
            - is_valid: True if configuration is valid and API is accessible
            - error_message: None if valid, or a descriptive error message
        """
        if not self.is_configured():
            return False, "Cerebras API key is not configured"
        
        try:
            session = self._get_session()
            response = session.get(
                f"{CEREBRAS_API_BASE}/models",
                timeout=10
            )
            
            if response.status_code == 200:
                return True, None
            elif response.status_code == 401:
                return False, "Invalid API key"
            else:
                return False, f"API error: {response.status_code}"
                
        except requests.Timeout:
            return False, "API request timed out"
        except requests.ConnectionError:
            return False, "Could not connect to Cerebras API"
        except Exception as e:
            return False, str(e)


    def _translate_messages(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Translate FRIDAY messages to Cerebras (OpenAI-compatible) format.
        
        FRIDAY message format:
        {
            "role": "system" | "user" | "assistant" | "tool",
            "content": str,
            "name": Optional[str],
            "tool_call_id": Optional[str],
        }
        
        Args:
            messages: List of messages in FRIDAY format
            
        Returns:
            List of messages in OpenAI-compatible chat completion format
        """
        translated_messages = []
        
        for msg in messages:
            translated_msg: dict[str, Any] = {
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            }
            
            # Handle tool messages
            if msg.get("role") == "tool":
                if "tool_call_id" in msg:
                    translated_msg["tool_call_id"] = msg["tool_call_id"]
                if "name" in msg:
                    translated_msg["name"] = msg["name"]
            
            # Handle assistant messages with tool calls
            if msg.get("role") == "assistant" and "tool_calls" in msg:
                translated_msg["tool_calls"] = msg["tool_calls"]
            
            translated_messages.append(translated_msg)
        
        return translated_messages


    def generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> GenerateResponse:
        """Generate a response from Cerebras.
        
        Sends messages to Cerebras's chat completions API and returns the response
        in FRIDAY's unified format.
        
        Args:
            messages: Chat messages in FRIDAY format
            model: Specific model to use (default: llama-4-scout-17b-16e-instruct)
            max_tokens: Maximum tokens in response (default: 1024)
            temperature: Sampling temperature 0.0-1.5 (default: 0.7)
            tools: Tool definitions in FRIDAY format (will be translated)
            
        Returns:
            GenerateResponse with unified response data
            
        Raises:
            ProviderError: On API errors with retry-after info if available
        """
        start_time = time.time()
        model = model or DEFAULT_MODEL
        
        # Clamp temperature to valid range
        temperature = max(0.0, min(1.5, temperature))
        
        try:
            session = self._get_session()
            
            # Translate messages to Cerebras format
            cerebras_messages = self._translate_messages(messages)
            
            # Build request parameters
            request_params: dict[str, Any] = {
                "model": model,
                "messages": cerebras_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            
            # Add tools if provided
            if tools:
                translated_tools = self.translate_tools(tools)
                if translated_tools:
                    request_params["tools"] = translated_tools
            
            # Make the API call
            response = session.post(
                f"{CEREBRAS_API_BASE}/chat/completions",
                json=request_params,
                timeout=30,
            )

            
            # Handle error responses
            if response.status_code == 429:
                self._record_failure("Rate limit exceeded")
                raise self._create_provider_error_from_response(response, "rate_limit")
            elif response.status_code == 401:
                self._record_failure("Invalid API key")
                raise self._create_provider_error_from_response(response, "auth")
            elif response.status_code >= 500:
                self._record_failure(f"Server error: {response.status_code}")
                raise self._create_provider_error_from_response(response, "server")
            elif response.status_code >= 400:
                self._record_failure(f"Client error: {response.status_code}")
                raise self._create_provider_error_from_response(response, "bad_request")
            
            # Parse successful response
            data = response.json()
            
            choice = data.get("choices", [{}])[0]
            message_data = choice.get("message", {})
            content = message_data.get("content", "") or ""
            finish_reason = choice.get("finish_reason", "stop") or "stop"
            
            # Parse tool calls if present
            tool_calls = None
            if message_data.get("tool_calls"):
                tool_calls = self.parse_tool_calls(message_data)
            
            # Extract usage information
            usage_data = data.get("usage", {})
            usage = {
                "prompt_tokens": usage_data.get("prompt_tokens", 0),
                "completion_tokens": usage_data.get("completion_tokens", 0),
                "total_tokens": usage_data.get("total_tokens", 0),
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
            
        except requests.Timeout:
            latency_ms = (time.time() - start_time) * 1000
            self._record_failure("Request timeout")
            raise ProviderError(
                provider=self.provider_name,
                error_type="timeout",
                message="Request timed out",
                is_retryable=True,
            )
        except requests.ConnectionError as e:
            self._record_failure(str(e))
            raise ProviderError(
                provider=self.provider_name,
                error_type="connection",
                message="Could not connect to Cerebras API",
                is_retryable=True,
            )
        except ProviderError:
            raise
        except Exception as e:
            self._record_failure(str(e))
            raise ProviderError(
                provider=self.provider_name,
                error_type="unknown",
                message=str(e),
                is_retryable=True,
            )


    def stream_generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Generator[str, None, None]:
        """Stream response tokens from Cerebras.
        
        Uses Cerebras's streaming API to yield tokens as they arrive,
        providing a better user experience for longer responses.
        
        Args:
            messages: Chat messages in FRIDAY format
            model: Specific model to use (default: llama-4-scout-17b-16e-instruct)
            max_tokens: Maximum tokens in response (default: 1024)
            temperature: Sampling temperature 0.0-1.5 (default: 0.7)
            
        Yields:
            String tokens as they arrive from Cerebras
        """
        start_time = time.time()
        model = model or DEFAULT_MODEL
        
        # Clamp temperature to valid range
        temperature = max(0.0, min(1.5, temperature))
        
        try:
            session = self._get_session()
            
            # Translate messages to Cerebras format
            cerebras_messages = self._translate_messages(messages)
            
            # Create streaming request
            response = session.post(
                f"{CEREBRAS_API_BASE}/chat/completions",
                json={
                    "model": model,
                    "messages": cerebras_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "stream": True,
                },
                timeout=60,
                stream=True,
            )
            
            response.raise_for_status()
            
            # Yield tokens as they arrive
            for line in response.iter_lines():
                if line:
                    text = line.decode("utf-8")
                    if text.startswith("data: ") and text != "data: [DONE]":
                        try:
                            chunk = json.loads(text[6:])
                            delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if delta:
                                yield delta
                        except json.JSONDecodeError:
                            continue
            
            # Record success
            latency_ms = (time.time() - start_time) * 1000
            self._record_success(latency_ms)
            
        except requests.Timeout:
            self._record_failure("Stream timeout")
            yield "Error: Request timed out"
        except requests.RequestException as e:
            self._record_failure(str(e))
            yield f"Error: {str(e)}"
        except Exception as e:
            self._record_failure(str(e))
            yield "Error generating response."


    def translate_tools(self, friday_tools: list[dict]) -> list[dict]:
        """Translate FRIDAY tool definitions to Cerebras's tools format.
        
        Cerebras uses OpenAI-compatible format, so this is mostly
        a pass-through with validation and normalization.
        
        Args:
            friday_tools: Tools in FRIDAY/OpenAI-compatible format
            
        Returns:
            Tools in Cerebras's native format. Returns empty list for None/empty input.
        """
        if not friday_tools:
            return []
        
        if not isinstance(friday_tools, list):
            logger.warning(f"translate_tools expected list, got {type(friday_tools).__name__}")
            return []
        
        cerebras_tools = []
        
        for idx, tool in enumerate(friday_tools):
            if tool is None:
                continue
            
            if not isinstance(tool, dict):
                logger.warning(f"Skipping non-dict tool at index {idx}")
                continue
            
            try:
                normalized = self._normalize_tool_definition(tool)
                if normalized:
                    cerebras_tools.append(normalized)
            except Exception as e:
                logger.warning(f"Failed to translate tool at index {idx}: {e}")
                continue
        
        return cerebras_tools

    def _normalize_tool_definition(self, tool: dict) -> Optional[dict]:
        """Normalize a single tool definition to Cerebras (OpenAI-compatible) format."""
        # Full format: {"type": "function", "function": {...}}
        if tool.get("type") == "function" and "function" in tool:
            func_def = tool["function"]
            if not isinstance(func_def, dict):
                return None
            
            name = func_def.get("name")
            if not name or not isinstance(name, str):
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
                return None
            
            return {
                "type": "function",
                "function": {
                    "name": name.strip(),
                    "description": str(tool.get("description", "")).strip(),
                    "parameters": self._normalize_parameters(tool.get("parameters")),
                }
            }
        
        return None


    def _normalize_parameters(self, parameters: Any) -> dict:
        """Normalize tool parameters to a valid JSON Schema object."""
        default_schema = {
            "type": "object",
            "properties": {},
        }
        
        if parameters is None:
            return default_schema
        
        if not isinstance(parameters, dict):
            return default_schema
        
        normalized = parameters.copy()
        if "type" not in normalized:
            normalized["type"] = "object"
        if "properties" not in normalized:
            normalized["properties"] = {}
        
        return normalized

    def parse_tool_calls(self, response: Any) -> list[dict]:
        """Parse tool calls from Cerebras response to FRIDAY format.
        
        Args:
            response: Cerebras response (dict with "tool_calls" key or list directly)
            
        Returns:
            List of tool calls in FRIDAY's format:
            [{"id": str, "function": {"name": str, "arguments": dict}}]
        """
        if response is None:
            return []
        
        raw_tool_calls = None
        
        # Handle dict with tool_calls key
        if isinstance(response, dict) and "tool_calls" in response:
            raw_tool_calls = response["tool_calls"]
        # Handle list directly
        elif isinstance(response, list):
            raw_tool_calls = response
        
        if not raw_tool_calls:
            return []
        
        if not isinstance(raw_tool_calls, list):
            return []
        
        tool_calls = []
        
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
        """Parse a single tool call to FRIDAY format."""
        if not isinstance(tc, dict):
            return None
        
        tc_id = tc.get("id", "")
        func_data = tc.get("function", {})
        
        if not isinstance(func_data, dict):
            return None
        
        func_name = func_data.get("name", "")
        raw_args = func_data.get("arguments", "{}")
        
        if not func_name:
            return None
        
        # Parse arguments
        arguments = self._parse_tool_arguments(raw_args, func_name)
        
        return {
            "id": str(tc_id) if tc_id else "",
            "function": {
                "name": str(func_name),
                "arguments": arguments,
            }
        }

    def _parse_tool_arguments(self, raw_args: Any, func_name: str) -> dict:
        """Parse tool call arguments from raw format."""
        if isinstance(raw_args, dict):
            return raw_args
        
        if not raw_args:
            return {}
        
        if isinstance(raw_args, str):
            if not raw_args.strip():
                return {}
            
            try:
                parsed = json.loads(raw_args)
                if isinstance(parsed, dict):
                    return parsed
                return {}
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse arguments for '{func_name}'")
                return {}
        
        return {}


    def get_available_models(self) -> list[dict[str, Any]]:
        """Get list of available Cerebras models.
        
        Returns information about supported models including context window
        and capabilities.
        
        Returns:
            List of ModelInfo-like dicts with model specifications
        """
        models = []
        
        for model_id, spec in CEREBRAS_MODELS.items():
            models.append({
                "id": model_id,
                "name": spec["name"],
                "provider": ProviderType.CEREBRAS.value,
                "context_window": spec["context_window"],
                "supports_streaming": spec["supports_streaming"],
                "supports_tool_calling": spec["supports_tool_calling"],
                "supports_vision": spec["supports_vision"],
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

    def _create_provider_error_from_response(
        self,
        response: requests.Response,
        error_type: str,
    ) -> ProviderError:
        """Create a ProviderError from an HTTP response.
        
        Args:
            response: The HTTP response object
            error_type: The type of error ('rate_limit', 'auth', 'server', etc.)
            
        Returns:
            ProviderError with appropriate fields set
        """
        retry_after: Optional[int] = None
        is_retryable = error_type in ("rate_limit", "server", "timeout", "connection")
        
        # Try to extract retry-after from headers
        if error_type == "rate_limit":
            retry_after_str = response.headers.get("retry-after") or response.headers.get("Retry-After")
            if retry_after_str:
                try:
                    retry_after = int(retry_after_str)
                except ValueError:
                    pass
        
        # Try to extract error message from response body
        try:
            error_data = response.json()
            error_message = error_data.get("error", {}).get("message", f"HTTP {response.status_code}")
        except Exception:
            error_message = f"HTTP {response.status_code}"
        
        return ProviderError(
            provider=self.provider_name,
            error_type=error_type,
            message=error_message,
            retry_after=retry_after,
            is_retryable=is_retryable,
        )
