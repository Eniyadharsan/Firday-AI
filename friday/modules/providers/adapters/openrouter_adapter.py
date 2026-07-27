"""OpenRouter Provider Adapter for FRIDAY.

This module implements the Provider_Adapter interface for OpenRouter.
OpenRouter provides access to various AI models (OpenAI, Anthropic, Google, etc.)
through a unified OpenAI-compatible API.

Features:
- OpenAI-compatible API (chat completions)
- Streaming responses (stream_generate)
- Dynamic model catalog from OpenRouter's /models endpoint
- Tool/function calling support
- Health monitoring and configuration validation

OpenRouter API specifics:
- Base URL: https://openrouter.ai/api/v1
- Requires additional headers: HTTP-Referer, X-Title for app attribution
- API key loaded from OPENROUTER_API_KEY environment variable

Requirements: 6.3, 6.4
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


# OpenRouter API configuration
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

# Default model if none specified (a popular, cost-effective choice)
DEFAULT_MODEL = "openai/gpt-4o-mini"

# Popular models available through OpenRouter (used as fallback if API unavailable)
# These models are commonly available and represent different providers
POPULAR_MODELS: dict[str, dict[str, Any]] = {
    "openai/gpt-4o": {
        "name": "GPT-4 Omni",
        "context_window": 128000,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
    },
    "openai/gpt-4o-mini": {
        "name": "GPT-4 Omni Mini",
        "context_window": 128000,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
    },
    "anthropic/claude-3-opus": {
        "name": "Claude 3 Opus",
        "context_window": 200000,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
    },
    "anthropic/claude-3-sonnet": {
        "name": "Claude 3 Sonnet",
        "context_window": 200000,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
    },
    "anthropic/claude-3-haiku": {
        "name": "Claude 3 Haiku",
        "context_window": 200000,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
    },
    "google/gemini-pro": {
        "name": "Gemini Pro",
        "context_window": 32768,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": False,
    },
    "google/gemini-pro-1.5": {
        "name": "Gemini Pro 1.5",
        "context_window": 1000000,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
    },
    "meta-llama/llama-3-70b-instruct": {
        "name": "Llama 3 70B Instruct",
        "context_window": 8192,
        "supports_streaming": True,
        "supports_tool_calling": False,
        "supports_vision": False,
    },
    "mistralai/mistral-large": {
        "name": "Mistral Large",
        "context_window": 32768,
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": False,
    },
}

# App attribution headers required by OpenRouter
APP_NAME = "FRIDAY AI Assistant"
APP_REFERER = "https://friday-ai.local"


class OpenRouter_Adapter(Provider_Adapter):
    """Provider adapter for OpenRouter multi-model API.
    
    This adapter implements the Provider_Adapter interface for OpenRouter,
    which provides access to multiple AI providers through a unified
    OpenAI-compatible API.
    
    OpenRouter-specific features:
    - Access to models from OpenAI, Anthropic, Google, Meta, Mistral, etc.
    - Dynamic model catalog via /models endpoint
    - Required HTTP-Referer and X-Title headers for app attribution
    
    Attributes:
        _key_store: API_Key_Store instance for retrieving the OpenRouter API key
        _client: HTTP client for API requests (lazy initialized)
        _metrics: Request metrics for health monitoring
        _cached_models: Cached list of available models
        _models_cache_time: Timestamp of last model cache update
    
    Requirements: 6.3, 6.4
    """

    def __init__(self, key_store: "API_Key_Store") -> None:
        """Initialize the OpenRouter adapter.
        
        Args:
            key_store: API_Key_Store instance for retrieving the OpenRouter API key.
                The key should be loaded from the OPENROUTER_API_KEY environment variable.
        """
        self._key_store = key_store
        self._client: Optional[Any] = None  # Lazy initialized openai.OpenAI client
        self._metrics = ProviderMetrics()
        self._last_error: Optional[str] = None
        self._last_error_time: Optional[datetime] = None
        self._cached_models: Optional[list[dict[str, Any]]] = None
        self._models_cache_time: Optional[float] = None
        # Cache models for 5 minutes
        self._models_cache_ttl = 300

    @property
    def provider_name(self) -> str:
        """Return the provider identifier.
        
        Returns:
            'openrouter' - the unique identifier for this provider.
        """
        return "openrouter"

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return the provider's capabilities.
        
        Returns:
            ProviderCapabilities describing OpenRouter's features including
            streaming, tool calling, and available models.
        """
        return ProviderCapabilities(
            supports_streaming=True,
            supports_tool_calling=True,
            supports_vision=True,  # Many models support vision
            max_context_window=200000,  # Claude 3 Opus has largest context
            supported_models=list(POPULAR_MODELS.keys()),
        )

    def _get_client(self) -> Any:
        """Get or create the OpenAI-compatible client for OpenRouter.
        
        Lazy initializes the client on first use with OpenRouter's base URL
        and the required additional headers for app attribution.
        
        Returns:
            The OpenAI client instance configured for OpenRouter.
            
        Raises:
            ImportError: If the openai library is not installed.
            ValueError: If the OpenRouter API key is not configured.
        """
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError:
                raise ImportError(
                    "The 'openai' library is required for OpenRouter integration. "
                    "Install it with: pip install openai"
                )
            
            api_key = self._key_store.get_key("openrouter")
            if not api_key:
                raise ValueError("OpenRouter API key is not configured")
            
            # OpenRouter uses OpenAI-compatible API with custom base URL
            # and requires additional headers for app attribution
            self._client = OpenAI(
                api_key=api_key,
                base_url=OPENROUTER_API_BASE,
                default_headers={
                    "HTTP-Referer": APP_REFERER,
                    "X-Title": APP_NAME,
                }
            )
        
        return self._client

    def _reset_client(self) -> None:
        """Reset the OpenRouter client.
        
        Forces re-creation of the client on next use. This is useful when
        the API key has been updated.
        """
        self._client = None

    def is_configured(self) -> bool:
        """Check if the provider has valid configuration.
        
        Checks if an OpenRouter API key is configured in the key store.
        Does not make network calls.
        
        Returns:
            True if an OpenRouter API key is configured, False otherwise.
            
        Requirement: 6.3
        """
        return self._key_store.is_configured("openrouter")

    def validate_config(self) -> tuple[bool, Optional[str]]:
        """Validate configuration by making a test API call.
        
        Attempts to list models from the OpenRouter API to verify the API key
        is valid and the service is accessible.
        
        Returns:
            Tuple of (is_valid, error_message) where:
            - is_valid: True if configuration is valid and API is accessible
            - error_message: None if valid, or a descriptive error message
            
        Requirement: 6.3
        """
        if not self.is_configured():
            return False, "OpenRouter API key is not configured"
        
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
        """Translate FRIDAY messages to OpenAI/OpenRouter chat completion format.
        
        OpenRouter uses the same message format as OpenAI, so this is
        essentially the same translation logic.
        
        Args:
            messages: List of messages in FRIDAY format
            
        Returns:
            List of messages in OpenRouter/OpenAI chat completion format
        """
        openrouter_messages = []
        
        for msg in messages:
            openrouter_msg: dict[str, Any] = {
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            }
            
            # Handle tool/function messages
            if msg.get("role") == "tool":
                if "tool_call_id" in msg:
                    openrouter_msg["tool_call_id"] = msg["tool_call_id"]
                if "name" in msg:
                    openrouter_msg["name"] = msg["name"]
            
            # Handle assistant messages with tool calls
            if msg.get("role") == "assistant" and "tool_calls" in msg:
                openrouter_msg["tool_calls"] = msg["tool_calls"]
            
            # Handle function name for function messages (legacy format)
            if msg.get("role") == "function" and "name" in msg:
                openrouter_msg["name"] = msg["name"]
            
            openrouter_messages.append(openrouter_msg)
        
        return openrouter_messages

    def generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> GenerateResponse:
        """Generate a response from OpenRouter.
        
        Sends messages to OpenRouter's chat completions API and returns the
        response in FRIDAY's unified format.
        
        Args:
            messages: Chat messages in FRIDAY format
            model: Specific model to use (default: openai/gpt-4o-mini)
            max_tokens: Maximum tokens in response (default: 1024)
            temperature: Sampling temperature 0.0-2.0 (default: 0.7)
            tools: Tool definitions in FRIDAY format (will be translated)
            
        Returns:
            GenerateResponse with unified response data
            
        Raises:
            ProviderError: On API errors with retry-after info if available
            
        Requirements: 6.3, 6.4
        """
        start_time = time.time()
        model = model or DEFAULT_MODEL
        
        try:
            client = self._get_client()
            
            # Translate messages to OpenRouter/OpenAI format
            openrouter_messages = self._translate_messages(messages)
            
            # Build request parameters
            request_params: dict[str, Any] = {
                "model": model,
                "messages": openrouter_messages,
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
        """Stream response tokens from OpenRouter.
        
        Uses OpenRouter's streaming API to yield tokens as they arrive,
        providing a better user experience for longer responses.
        
        Args:
            messages: Chat messages in FRIDAY format
            model: Specific model to use (default: openai/gpt-4o-mini)
            max_tokens: Maximum tokens in response (default: 1024)
            temperature: Sampling temperature 0.0-2.0 (default: 0.7)
            
        Yields:
            String tokens as they arrive from OpenRouter
        """
        start_time = time.time()
        model = model or DEFAULT_MODEL
        
        try:
            client = self._get_client()
            
            # Translate messages to OpenRouter/OpenAI format
            openrouter_messages = self._translate_messages(messages)
            
            # Create streaming request
            stream = client.chat.completions.create(
                model=model,
                messages=openrouter_messages,
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
        """Translate FRIDAY tool definitions to OpenRouter's tools format.
        
        OpenRouter uses OpenAI-compatible format, so this is mostly
        a pass-through with validation and normalization.
        
        Args:
            friday_tools: Tools in FRIDAY/OpenAI-compatible format
            
        Returns:
            Tools in OpenRouter's native format (OpenAI-compatible)
        """
        if not friday_tools:
            return []
        
        if not isinstance(friday_tools, list):
            logger.warning(f"translate_tools expected list, got {type(friday_tools).__name__}")
            return []
        
        openrouter_tools = []
        
        for idx, tool in enumerate(friday_tools):
            if tool is None:
                logger.warning(f"Skipping None tool at index {idx}")
                continue
            
            if not isinstance(tool, dict):
                logger.warning(f"Skipping non-dict tool at index {idx}: {type(tool).__name__}")
                continue
            
            try:
                openrouter_tool = self._normalize_tool_definition(tool)
                if openrouter_tool:
                    openrouter_tools.append(openrouter_tool)
            except Exception as e:
                logger.warning(f"Failed to translate tool at index {idx}: {e}")
                continue
        
        return openrouter_tools

    def _normalize_tool_definition(self, tool: dict) -> Optional[dict]:
        """Normalize a single tool definition to OpenAI/OpenRouter format.
        
        Args:
            tool: Tool definition in any supported format
            
        Returns:
            Normalized tool in OpenRouter format, or None if invalid
        """
        # Full OpenAI format: {"type": "function", "function": {...}}
        if tool.get("type") == "function" and "function" in tool:
            func_def = tool["function"]
            if not isinstance(func_def, dict):
                logger.warning(f"Tool 'function' field is not a dict: {type(func_def).__name__}")
                return None
            
            name = func_def.get("name")
            if not name or not isinstance(name, str):
                logger.warning(f"Tool missing valid 'name' field in function definition")
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
        
        logger.warning(f"Unrecognized tool format, missing 'name' or 'type'='function' with 'function' field")
        return None


    def _normalize_parameters(self, parameters: Any) -> dict:
        """Normalize tool parameters to a valid JSON Schema object.
        
        Args:
            parameters: Parameters definition (dict, None, or other)
            
        Returns:
            Valid JSON Schema object for OpenRouter
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
        
        normalized = parameters.copy()
        if "type" not in normalized:
            normalized["type"] = "object"
        
        if "properties" not in normalized:
            normalized["properties"] = {}
        
        return normalized

    def parse_tool_calls(self, response: Any) -> list[dict]:
        """Parse tool calls from OpenRouter response to FRIDAY format.
        
        Args:
            response: OpenRouter response which can be:
                - ChatCompletionMessage object with tool_calls attribute
                - Dict with "tool_calls" key
                - List of tool call dicts directly
                - None or empty (returns empty list)
            
        Returns:
            List of tool calls in FRIDAY's format:
            [{"id": str, "function": {"name": str, "arguments": dict}}]
        """
        if response is None:
            return []
        
        tool_calls = []
        raw_tool_calls = None
        
        # Handle ChatCompletionMessage object
        if hasattr(response, 'tool_calls'):
            raw_tool_calls = response.tool_calls
        elif isinstance(response, dict) and "tool_calls" in response:
            raw_tool_calls = response["tool_calls"]
        elif isinstance(response, list):
            raw_tool_calls = response
        elif isinstance(response, dict) and ("id" in response or "function" in response):
            raw_tool_calls = [response]
        
        if not raw_tool_calls:
            return []
        
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
            tc: A single tool call in OpenRouter format (object or dict)
            
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
                else:
                    logger.warning(
                        f"Parsed arguments for '{func_name}' is not a dict: {type(parsed).__name__}"
                    )
                    return {}
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse tool call arguments for '{func_name}': {e}")
                return {}
        
        logger.warning(f"Unexpected arguments type for '{func_name}': {type(raw_args).__name__}")
        return {}

    def get_available_models(self) -> list[dict[str, Any]]:
        """Get list of available models from OpenRouter.
        
        Queries OpenRouter's /models endpoint to get the current catalog
        of available models. Results are cached for performance.
        
        Returns:
            List of ModelInfo-like dicts with model specifications.
            Falls back to POPULAR_MODELS if the API call fails.
            
        Requirement: 6.4
        """
        # Check cache first
        current_time = time.time()
        if (
            self._cached_models is not None
            and self._models_cache_time is not None
            and (current_time - self._models_cache_time) < self._models_cache_ttl
        ):
            return self._cached_models
        
        # Try to fetch from API
        try:
            models = self._fetch_models_from_api()
            if models:
                self._cached_models = models
                self._models_cache_time = current_time
                return models
        except Exception as e:
            logger.warning(f"Failed to fetch models from OpenRouter API: {e}")
        
        # Fall back to popular models
        return self._get_fallback_models()


    def _fetch_models_from_api(self) -> list[dict[str, Any]]:
        """Fetch available models from OpenRouter's /models endpoint.
        
        Returns:
            List of model info dicts from the API
        """
        import requests
        
        api_key = self._key_store.get_key("openrouter")
        if not api_key:
            raise ValueError("OpenRouter API key not configured")
        
        response = requests.get(
            f"{OPENROUTER_API_BASE}/models",
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": APP_REFERER,
                "X-Title": APP_NAME,
            },
            timeout=10
        )
        
        if response.status_code != 200:
            raise ValueError(f"API error: {response.status_code}")
        
        data = response.json()
        models = []
        
        # OpenRouter returns {"data": [...]} format
        raw_models = data.get("data", [])
        
        for model in raw_models:
            if not isinstance(model, dict):
                continue
            
            model_id = model.get("id", "")
            if not model_id:
                continue
            
            # Extract context length
            context_length = model.get("context_length", 8192)
            
            # Extract pricing info (OpenRouter returns pricing per token)
            pricing = model.get("pricing", {})
            prompt_price = pricing.get("prompt", 0)
            completion_price = pricing.get("completion", 0)
            
            # Convert to cost per 1k tokens
            input_cost = float(prompt_price) * 1000 if prompt_price else None
            output_cost = float(completion_price) * 1000 if completion_price else None
            
            models.append({
                "id": model_id,
                "name": model.get("name", model_id),
                "provider": ProviderType.OPENROUTER.value,
                "context_window": context_length,
                "supports_streaming": True,  # OpenRouter supports streaming for all models
                "supports_tool_calling": self._model_supports_tools(model_id),
                "supports_vision": self._model_supports_vision(model_id, model),
                "input_cost_per_1k": input_cost,
                "output_cost_per_1k": output_cost,
            })
        
        return models


    def _model_supports_tools(self, model_id: str) -> bool:
        """Check if a model supports tool calling based on its ID.
        
        Args:
            model_id: The model identifier
            
        Returns:
            True if the model is known to support tool calling
        """
        # Models known to support tool calling
        tool_supporting_prefixes = [
            "openai/",
            "anthropic/claude-3",
            "google/gemini",
            "mistralai/mistral-large",
            "mistralai/mixtral",
        ]
        
        for prefix in tool_supporting_prefixes:
            if model_id.startswith(prefix):
                return True
        
        return False

    def _model_supports_vision(self, model_id: str, model_data: dict) -> bool:
        """Check if a model supports vision based on its ID and metadata.
        
        Args:
            model_id: The model identifier
            model_data: The raw model data from the API
            
        Returns:
            True if the model supports vision/image inputs
        """
        # Check API-provided architecture info
        architecture = model_data.get("architecture", {})
        modality = architecture.get("modality", "")
        if "image" in modality.lower() or "vision" in modality.lower():
            return True
        
        # Check model ID for known vision-capable models
        vision_models = [
            "gpt-4o", "gpt-4-turbo", "gpt-4-vision",
            "claude-3-opus", "claude-3-sonnet", "claude-3-haiku",
            "gemini-pro-vision", "gemini-1.5",
        ]
        
        for vm in vision_models:
            if vm in model_id:
                return True
        
        return False

    def _get_fallback_models(self) -> list[dict[str, Any]]:
        """Get fallback list of popular models when API is unavailable.
        
        Returns:
            List of model info dicts from POPULAR_MODELS constant
        """
        models = []
        
        for model_id, spec in POPULAR_MODELS.items():
            models.append({
                "id": model_id,
                "name": spec["name"],
                "provider": ProviderType.OPENROUTER.value,
                "context_window": spec["context_window"],
                "supports_streaming": spec["supports_streaming"],
                "supports_tool_calling": spec["supports_tool_calling"],
                "supports_vision": spec.get("supports_vision", False),
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
        
        if hasattr(error, 'message'):
            return error.message
        if hasattr(error, 'body') and isinstance(error.body, dict):
            return error.body.get('message', error_str)
        
        return error_str


    def _create_provider_error(self, error: Exception) -> ProviderError:
        """Create a ProviderError from an exception.
        
        Handles OpenRouter/OpenAI-compatible error types with proper classification.
        
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
        
        error_class_name = type(error).__name__
        error_str = str(error).lower()
        
        # Rate limit errors
        if "RateLimitError" in error_class_name or "rate_limit" in error_str or "429" in str(error):
            error_type = "rate_limit"
            retry_after = self._extract_retry_after(error)
            is_retryable = True
            
        # Authentication errors
        elif "AuthenticationError" in error_class_name or "401" in str(error) or "invalid api key" in error_str:
            error_type = "auth"
            is_retryable = False
            
        # Permission errors
        elif "PermissionDeniedError" in error_class_name or "403" in str(error) or "permission" in error_str:
            error_type = "auth"
            is_retryable = False
            
        # Timeout errors
        elif ("Timeout" in error_class_name or "timeout" in error_str or 
              "ReadTimeout" in error_class_name or "ConnectTimeout" in error_class_name):
            error_type = "timeout"
            is_retryable = True
            
        # Connection errors
        elif ("APIConnectionError" in error_class_name or "ConnectionError" in error_class_name or
              "connection" in error_str or "network" in error_str or "unreachable" in error_str):
            error_type = "connection"
            is_retryable = True
            
        # Server errors (5xx)
        elif ("APIStatusError" in error_class_name or "InternalServerError" in error_class_name or
              "500" in str(error) or "502" in str(error) or "503" in str(error) or 
              "504" in str(error) or "server error" in error_str):
            error_type = "server"
            is_retryable = True
            
        # Bad request errors
        elif "BadRequestError" in error_class_name or "400" in str(error):
            error_type = "bad_request"
            is_retryable = False
            
        # Not found errors
        elif "NotFoundError" in error_class_name or "404" in str(error):
            error_type = "not_found"
            is_retryable = False
            
        # Content filter errors
        elif "content_filter" in error_str or "content policy" in error_str:
            error_type = "content_filter"
            is_retryable = False
            
        # Context length errors
        elif "context_length" in error_str or "maximum context length" in error_str:
            error_type = "context_length"
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
        
        # Try to extract from error message
        if retry_after is None:
            error_str = str(error)
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
