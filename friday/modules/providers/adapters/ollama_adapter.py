"""Ollama Provider Adapter for FRIDAY.

This module implements the Provider_Adapter interface for local Ollama models.
It connects to a locally running Ollama server to provide AI capabilities
without sending data to external services.

Features:
- Chat completions (generate)
- Streaming responses via NDJSON (stream_generate)
- Message format translation to Ollama chat format
- Dynamic model discovery from local server
- 3-second timeout for unreachable server detection
- Basic tool calling support (model-dependent)

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5

Property 4: Message Format Translation
For any valid FRIDAY message format (with role, content, and optional metadata)
and for Ollama, the adapter's message translation SHALL produce a valid message
in Ollama's chat completion format.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Generator, Optional

import requests

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


# Default Ollama server URL
DEFAULT_OLLAMA_HOST = "http://localhost:11434"

# Connection timeout for server availability check (3 seconds per Requirement 5.5)
CONNECTION_TIMEOUT = 3.0

# Request timeout for normal API calls
REQUEST_TIMEOUT = 120.0

# Default model if none specified and server has models
DEFAULT_MODEL = "llama3.2"


class Ollama_Adapter(Provider_Adapter):
    """Provider adapter for local Ollama models.
    
    This adapter implements the Provider_Adapter interface for Ollama's
    local server API, enabling AI capabilities without external data transfer.
    
    The adapter handles:
    - Message format translation from FRIDAY format to Ollama chat format
    - Synchronous and streaming response generation
    - Dynamic model discovery from local Ollama server
    - 3-second timeout for unreachable server detection
    - Basic tool calling support (for models that support it)
    - Health monitoring and configuration validation
    
    Attributes:
        _key_store: API_Key_Store instance (used for OLLAMA_HOST config)
        _host: Ollama server URL (from OLLAMA_HOST env var or default)
        _metrics: Request metrics for health monitoring
        _last_error: Most recent error message
        _last_error_time: Timestamp of the last error
        _cached_models: Cached list of available models
        _models_cache_time: When models were last fetched
    
    Example:
        from friday.modules.providers import API_Key_Store
        
        key_store = API_Key_Store()
        key_store.load_from_env()
        
        adapter = Ollama_Adapter(key_store)
        if adapter.is_configured():
            response = adapter.generate([
                {"role": "user", "content": "Hello!"}
            ])
            print(response.content)
    
    Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
    """

    def __init__(self, key_store: "API_Key_Store") -> None:
        """Initialize the Ollama adapter.
        
        Args:
            key_store: API_Key_Store instance. While Ollama doesn't require
                an API key, the key_store is used for consistency and to
                retrieve the OLLAMA_HOST configuration if set.
        """
        self._key_store = key_store
        self._host = os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST)
        self._metrics = ProviderMetrics()
        self._last_error: Optional[str] = None
        self._last_error_time: Optional[datetime] = None
        self._cached_models: Optional[list[dict[str, Any]]] = None
        self._models_cache_time: Optional[float] = None
        self._models_cache_ttl = 300.0  # 5 minutes cache TTL

    @property
    def provider_name(self) -> str:
        """Return the provider identifier.
        
        Returns:
            'ollama' - the unique identifier for this provider.
        """
        return "ollama"

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return the provider's capabilities.
        
        Returns:
            ProviderCapabilities describing Ollama's features. Note that
            tool calling support varies by model.
        """
        return ProviderCapabilities(
            supports_streaming=True,
            supports_tool_calling=True,  # Model-dependent, checked at runtime
            supports_vision=False,  # Some models support vision, but not all
            max_context_window=8192,  # Varies by model
            supported_models=[],  # Dynamically populated from server
        )

    def _get_base_url(self) -> str:
        """Get the Ollama server base URL.
        
        Returns:
            The Ollama server URL from OLLAMA_HOST env var or default.
        """
        return self._host.rstrip("/")

    def _check_server_reachable(self, timeout: float = CONNECTION_TIMEOUT) -> bool:
        """Check if the Ollama server is reachable.
        
        Uses a 3-second timeout as per Requirement 5.5 to quickly detect
        when the server is unavailable.
        
        Args:
            timeout: Connection timeout in seconds (default: 3.0)
            
        Returns:
            True if server responds, False otherwise.
        """
        try:
            url = f"{self._get_base_url()}/api/tags"
            response = requests.get(url, timeout=timeout)
            return response.status_code == 200
        except (requests.ConnectionError, requests.Timeout, requests.RequestException):
            return False

    def is_configured(self) -> bool:
        """Check if the provider has valid configuration.
        
        For Ollama, this checks if the server is reachable within 3 seconds.
        No API key is required since Ollama runs locally.
        
        Returns:
            True if Ollama server is reachable, False otherwise.
            
        Requirement: 5.1, 5.5
        """
        return self._check_server_reachable()

    def validate_config(self) -> tuple[bool, Optional[str]]:
        """Validate configuration by making a test API call.
        
        Attempts to list models from the Ollama server to verify the
        server is accessible and functioning.
        
        Returns:
            Tuple of (is_valid, error_message) where:
            - is_valid: True if server is accessible and has models
            - error_message: None if valid, or a descriptive error message
            
        Requirement: 5.1
        """
        try:
            url = f"{self._get_base_url()}/api/tags"
            response = requests.get(url, timeout=CONNECTION_TIMEOUT)
            
            if response.status_code != 200:
                return False, f"Ollama server returned status {response.status_code}"
            
            data = response.json()
            models = data.get("models", [])
            
            if not models:
                return True, "Ollama server is running but no models are installed"
            
            return True, None
            
        except requests.Timeout:
            return False, "Ollama server connection timed out (3s limit)"
        except requests.ConnectionError:
            return False, f"Cannot connect to Ollama server at {self._get_base_url()}"
        except requests.RequestException as e:
            return False, f"Ollama server error: {str(e)}"
        except json.JSONDecodeError:
            return False, "Ollama server returned invalid JSON"

    def _translate_messages(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Translate FRIDAY messages to Ollama chat format.
        
        Property 4: Message Format Translation
        For any valid FRIDAY message format (with role, content, and optional metadata)
        and for Ollama, the adapter's message translation SHALL produce a valid message
        in Ollama's chat completion format.
        
        FRIDAY message format:
        {
            "role": "system" | "user" | "assistant" | "tool",
            "content": str,
            "name": Optional[str],
            "tool_call_id": Optional[str],
        }
        
        Ollama message format:
        {
            "role": "system" | "user" | "assistant" | "tool",
            "content": str,
        }
        
        Args:
            messages: List of messages in FRIDAY format
            
        Returns:
            List of messages in Ollama chat format
        """
        ollama_messages = []
        
        for msg in messages:
            ollama_msg: dict[str, Any] = {
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            }
            
            # Ollama uses similar role names to OpenAI
            # Map 'function' role to 'tool' if present
            if ollama_msg["role"] == "function":
                ollama_msg["role"] = "tool"
            
            ollama_messages.append(ollama_msg)
        
        return ollama_messages

    def _get_default_model(self) -> str:
        """Get the default model to use.
        
        Returns the first available model from the server, or DEFAULT_MODEL
        if no models are available or server is unreachable.
        
        Returns:
            Model name to use
        """
        try:
            models = self.get_available_models()
            if models:
                return models[0]["id"]
        except Exception:
            pass
        return DEFAULT_MODEL

    def generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> GenerateResponse:
        """Generate a response from Ollama.
        
        Sends messages to Ollama's chat API and returns the response
        in FRIDAY's unified format.
        
        Args:
            messages: Chat messages in FRIDAY format
            model: Specific model to use (default: first available model)
            max_tokens: Maximum tokens in response (mapped to num_predict)
            temperature: Sampling temperature 0.0-2.0 (default: 0.7)
            tools: Tool definitions in FRIDAY format (will be translated)
            
        Returns:
            GenerateResponse with unified response data
            
        Raises:
            ProviderError: On API errors
            
        Requirements: 5.1, 5.3
        """
        start_time = time.time()
        model = model or self._get_default_model()
        
        try:
            # Translate messages to Ollama format
            ollama_messages = self._translate_messages(messages)
            
            # Build request payload
            payload: dict[str, Any] = {
                "model": model,
                "messages": ollama_messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }
            
            # Add tools if provided and model supports them
            if tools:
                translated_tools = self.translate_tools(tools)
                if translated_tools:
                    payload["tools"] = translated_tools
            
            # Make the API call
            url = f"{self._get_base_url()}/api/chat"
            response = requests.post(
                url,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            
            if response.status_code != 200:
                raise Exception(f"Ollama returned status {response.status_code}: {response.text}")
            
            data = response.json()
            
            # Extract response data
            message_data = data.get("message", {})
            content = message_data.get("content", "")
            
            # Parse tool calls if present
            tool_calls = None
            if message_data.get("tool_calls"):
                tool_calls = self.parse_tool_calls(message_data)
            
            # Extract usage information (Ollama provides different metrics)
            usage = {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            }
            
            # Determine finish reason
            finish_reason = "stop"
            if data.get("done_reason"):
                finish_reason = data["done_reason"]
            elif tool_calls:
                finish_reason = "tool_calls"
            
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
        """Stream response tokens from Ollama.
        
        Uses Ollama's streaming API with NDJSON format to yield tokens
        as they arrive, providing a better user experience for longer responses.
        
        Args:
            messages: Chat messages in FRIDAY format
            model: Specific model to use (default: first available model)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature 0.0-2.0 (default: 0.7)
            
        Yields:
            String tokens as they arrive from Ollama
            
        Requirement: 5.4
        """
        start_time = time.time()
        model = model or self._get_default_model()
        
        try:
            # Translate messages to Ollama format
            ollama_messages = self._translate_messages(messages)
            
            # Build request payload
            payload: dict[str, Any] = {
                "model": model,
                "messages": ollama_messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            }
            
            # Make streaming request
            url = f"{self._get_base_url()}/api/chat"
            response = requests.post(
                url,
                json=payload,
                stream=True,
                timeout=REQUEST_TIMEOUT,
            )
            
            if response.status_code != 200:
                raise Exception(f"Ollama returned status {response.status_code}")
            
            # Stream NDJSON responses
            for line in response.iter_lines():
                if line:
                    try:
                        chunk = json.loads(line)
                        message = chunk.get("message", {})
                        content = message.get("content", "")
                        if content:
                            yield content
                        
                        # Check if this is the final chunk
                        if chunk.get("done", False):
                            break
                    except json.JSONDecodeError:
                        # Skip malformed lines
                        logger.warning(f"Failed to parse Ollama stream chunk: {line}")
                        continue
            
            # Record success
            latency_ms = (time.time() - start_time) * 1000
            self._record_success(latency_ms)
            
        except Exception as e:
            # Record failure
            self._record_failure(str(e))
            raise self._create_provider_error(e)

    def translate_tools(self, friday_tools: list[dict]) -> list[dict]:
        """Translate FRIDAY tool definitions to Ollama's tools format.
        
        Ollama uses a format similar to OpenAI for tool definitions.
        
        Property 5: Tool Definition Translation
        For any valid FRIDAY tool definition (in OpenAI-compatible format with
        name, description, parameters) and for Ollama, the translate_tools()
        method SHALL produce a valid tool definition in Ollama's native format.
        
        Args:
            friday_tools: Tools in FRIDAY/OpenAI-compatible format
            
        Returns:
            Tools in Ollama's native format
            
        Requirement: 12.1
        """
        if not friday_tools:
            return []
        
        if not isinstance(friday_tools, list):
            logger.warning(f"translate_tools expected list, got {type(friday_tools).__name__}")
            return []
        
        ollama_tools = []
        
        for idx, tool in enumerate(friday_tools):
            if tool is None:
                continue
            
            if not isinstance(tool, dict):
                logger.warning(f"Skipping non-dict tool at index {idx}")
                continue
            
            try:
                ollama_tool = self._normalize_tool_definition(tool)
                if ollama_tool:
                    ollama_tools.append(ollama_tool)
            except Exception as e:
                logger.warning(f"Failed to translate tool at index {idx}: {e}")
                continue
        
        return ollama_tools

    def _normalize_tool_definition(self, tool: dict) -> Optional[dict]:
        """Normalize a single tool definition to Ollama format.
        
        Ollama uses a format similar to OpenAI:
        {
            "type": "function",
            "function": {
                "name": str,
                "description": str,
                "parameters": {...}
            }
        }
        
        Args:
            tool: Tool definition in any supported format
            
        Returns:
            Normalized tool in Ollama format, or None if invalid
        """
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
        """Normalize tool parameters to a valid JSON Schema object.
        
        Args:
            parameters: Parameters definition (dict, None, or other)
            
        Returns:
            Valid JSON Schema object for Ollama
        """
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
        """Parse tool calls from Ollama response to FRIDAY format.
        
        Property 6: Tool Call Parsing
        For any valid tool call response from Ollama, parse_tool_calls() SHALL
        produce a list of FRIDAY ToolCall objects with correctly extracted id,
        function_name, and arguments.
        
        Args:
            response: Ollama response (dict with "tool_calls" key or list)
            
        Returns:
            List of tool calls in FRIDAY's format
            
        Requirement: 12.2
        """
        if response is None:
            return []
        
        tool_calls = []
        raw_tool_calls = None
        
        # Handle dict with tool_calls key
        if isinstance(response, dict) and "tool_calls" in response:
            raw_tool_calls = response["tool_calls"]
        # Handle list of tool calls directly
        elif isinstance(response, list):
            raw_tool_calls = response
        # Handle single tool call dict
        elif isinstance(response, dict) and ("function" in response or "name" in response):
            raw_tool_calls = [response]
        
        if not raw_tool_calls:
            return []
        
        if not isinstance(raw_tool_calls, list):
            return []
        
        for idx, tc in enumerate(raw_tool_calls):
            try:
                parsed = self._parse_single_tool_call(tc, idx)
                if parsed:
                    tool_calls.append(parsed)
            except Exception as e:
                logger.warning(f"Failed to parse tool call at index {idx}: {e}")
                continue
        
        return tool_calls

    def _parse_single_tool_call(self, tc: Any, index: int) -> Optional[dict]:
        """Parse a single tool call to FRIDAY format.
        
        Args:
            tc: A single tool call in Ollama format
            index: Index for generating ID if not present
            
        Returns:
            Parsed tool call dict or None if invalid
        """
        if not isinstance(tc, dict):
            return None
        
        # Ollama format: {"function": {"name": str, "arguments": dict}}
        func_data = tc.get("function", {})
        if not isinstance(func_data, dict):
            # Try direct name/arguments format
            func_data = tc
        
        func_name = func_data.get("name", "")
        if not func_name:
            return None
        
        # Get arguments (could be dict or JSON string)
        raw_args = func_data.get("arguments", {})
        arguments = self._parse_tool_arguments(raw_args, func_name)
        
        # Get or generate ID
        tc_id = tc.get("id", f"call_{index}")
        
        return {
            "id": str(tc_id),
            "function": {
                "name": str(func_name),
                "arguments": arguments,
            }
        }

    def _parse_tool_arguments(self, raw_args: Any, func_name: str) -> dict:
        """Parse tool call arguments from raw format.
        
        Args:
            raw_args: Arguments in string JSON or dict format
            func_name: Function name (for logging)
            
        Returns:
            Parsed arguments dict (empty dict on error)
        """
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
        """Get list of available Ollama models.
        
        Queries the local Ollama server for installed models. Results are
        cached for 5 minutes to avoid excessive API calls.
        
        Returns:
            List of ModelInfo-like dicts with model specifications
            
        Requirement: 5.2
        """
        # Check cache validity
        now = time.time()
        if (self._cached_models is not None and 
            self._models_cache_time is not None and
            now - self._models_cache_time < self._models_cache_ttl):
            return self._cached_models
        
        models = []
        
        try:
            url = f"{self._get_base_url()}/api/tags"
            response = requests.get(url, timeout=CONNECTION_TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                raw_models = data.get("models", [])
                
                for m in raw_models:
                    model_name = m.get("name", "")
                    if not model_name:
                        continue
                    
                    # Extract model details
                    details = m.get("details", {})
                    
                    models.append({
                        "id": model_name,
                        "name": model_name,
                        "provider": ProviderType.OLLAMA.value,
                        "context_window": self._estimate_context_window(model_name),
                        "supports_streaming": True,
                        "supports_tool_calling": self._model_supports_tools(model_name),
                        "supports_vision": self._model_supports_vision(model_name),
                        "input_cost_per_1k": None,  # Local, no cost
                        "output_cost_per_1k": None,
                    })
                
                # Update cache
                self._cached_models = models
                self._models_cache_time = now
                
        except (requests.ConnectionError, requests.Timeout, requests.RequestException) as e:
            logger.warning(f"Failed to fetch Ollama models: {e}")
        except json.JSONDecodeError:
            logger.warning("Ollama returned invalid JSON for model list")
        
        return models

    def _estimate_context_window(self, model_name: str) -> int:
        """Estimate context window size based on model name.
        
        Different Ollama models have different context windows. This provides
        reasonable estimates based on common model families.
        
        Args:
            model_name: Name of the model
            
        Returns:
            Estimated context window size in tokens
        """
        model_lower = model_name.lower()
        
        # Llama 3 models typically have 8K context
        if "llama3" in model_lower or "llama-3" in model_lower:
            return 8192
        # Llama 2 models have 4K context by default
        if "llama2" in model_lower or "llama-2" in model_lower:
            return 4096
        # Mistral models have 8K-32K context
        if "mistral" in model_lower:
            if "large" in model_lower:
                return 32768
            return 8192
        # Mixtral models have 32K context
        if "mixtral" in model_lower:
            return 32768
        # CodeLlama models have 16K context
        if "codellama" in model_lower or "code-llama" in model_lower:
            return 16384
        # Phi models
        if "phi" in model_lower:
            return 4096
        # Gemma models
        if "gemma" in model_lower:
            return 8192
        # Qwen models
        if "qwen" in model_lower:
            return 32768
        
        # Default estimate
        return 4096

    def _model_supports_tools(self, model_name: str) -> bool:
        """Check if a model supports tool calling.
        
        Tool calling support varies by model. This provides reasonable
        estimates based on known model capabilities.
        
        Args:
            model_name: Name of the model
            
        Returns:
            True if model likely supports tool calling
        """
        model_lower = model_name.lower()
        
        # Models known to support tool calling
        tool_capable_models = [
            "llama3",
            "llama-3",
            "mistral",
            "mixtral",
            "qwen",
            "command-r",
        ]
        
        return any(m in model_lower for m in tool_capable_models)

    def _model_supports_vision(self, model_name: str) -> bool:
        """Check if a model supports vision/image inputs.
        
        Args:
            model_name: Name of the model
            
        Returns:
            True if model supports vision inputs
        """
        model_lower = model_name.lower()
        
        # Models known to support vision
        vision_models = [
            "llava",
            "bakllava",
            "moondream",
        ]
        
        return any(m in model_lower for m in vision_models)

    def get_health(self) -> ProviderHealth:
        """Get current health status and metrics.
        
        Returns the adapter's current operational status along with
        performance metrics for monitoring and failover decisions.
        
        For Ollama, unavailable status is determined by the 3-second
        connection timeout as per Requirement 5.5.
        
        Returns:
            ProviderHealth with status, latency, success/error rates
        """
        # Check server reachability with 3-second timeout
        server_reachable = self._check_server_reachable()
        
        # Determine status based on reachability and metrics
        if not server_reachable:
            status = ProviderStatus.UNAVAILABLE
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
            last_checked=datetime.now().isoformat(),
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
        
        # Try to extract message from response errors
        if hasattr(error, 'response'):
            try:
                response = error.response
                if hasattr(response, 'text'):
                    return response.text[:200]  # Limit message length
            except Exception:
                pass
        
        return error_str

    def _create_provider_error(self, error: Exception) -> ProviderError:
        """Create a ProviderError from an exception.
        
        Handles Ollama-specific error types:
        - timeout: Connection timeouts (server unreachable)
        - connection: Network/connection errors
        - server: Server-side errors
        
        Args:
            error: The exception raised during the API call
            
        Returns:
            ProviderError with appropriate error_type and message
        """
        error_message = self._extract_error_message(error)
        error_type = "unknown"
        retry_after: Optional[int] = None
        is_retryable = True
        
        error_class_name = type(error).__name__
        error_str = str(error).lower()
        
        # Check for timeout errors
        if isinstance(error, requests.Timeout) or "timeout" in error_str:
            error_type = "timeout"
            is_retryable = True
        
        # Check for connection errors
        elif isinstance(error, requests.ConnectionError) or "connection" in error_str:
            error_type = "connection"
            is_retryable = True
        
        # Check for server errors
        elif "500" in str(error) or "502" in str(error) or "503" in str(error):
            error_type = "server"
            is_retryable = True
        
        # Check for model not found
        elif "model" in error_str and ("not found" in error_str or "does not exist" in error_str):
            error_type = "not_found"
            is_retryable = False
        
        return ProviderError(
            provider=self.provider_name,
            error_type=error_type,
            message=error_message,
            retry_after=retry_after,
            is_retryable=is_retryable,
        )
