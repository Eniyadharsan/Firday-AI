"""Google Gemini Provider Adapter for FRIDAY.

This module implements the Provider_Adapter interface for Google's Gemini models.
It supports Gemini 1.5 Pro, Gemini 1.5 Flash, and Gemini Pro (legacy) models
through Google's generative AI API.

Features:
- Text generation (generate) via generateContent API
- Streaming responses (stream_generate)
- Message format translation to Gemini content format
- Tool/function calling (translate_tools, parse_tool_calls)
- Health monitoring and configuration validation

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5

Property 4: Message Format Translation
For any valid FRIDAY message format (with role, content, and optional metadata)
and for Gemini, the adapter's message translation SHALL produce a valid message
in Gemini's generateContent format.
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


# Gemini supported models with their specifications
GEMINI_MODELS: dict[str, dict[str, Any]] = {
    # Stable aliases first — they always route to a currently-available model,
    # so they work across free-tier and billed keys without 404/deprecation.
    "gemini-flash-latest": {
        "name": "Gemini Flash (Latest)",
        "context_window": 1048576,  # 1M tokens
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
        "input_cost_per_1k": 0.000075,
        "output_cost_per_1k": 0.0003,
    },
    "gemini-pro-latest": {
        "name": "Gemini Pro (Latest)",
        "context_window": 1048576,  # 1M tokens
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
        "input_cost_per_1k": 0.00125,
        "output_cost_per_1k": 0.005,
    },
    "gemini-2.0-flash": {
        "name": "Gemini 2.0 Flash",
        "context_window": 1048576,  # 1M tokens
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
        "input_cost_per_1k": 0.000075,
        "output_cost_per_1k": 0.0003,
    },
    "gemini-2.5-flash": {
        "name": "Gemini 2.5 Flash",
        "context_window": 1048576,  # 1M tokens
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
        "input_cost_per_1k": 0.000075,
        "output_cost_per_1k": 0.0003,
    },
    "gemini-2.5-pro": {
        "name": "Gemini 2.5 Pro",
        "context_window": 1048576,  # 1M tokens
        "supports_streaming": True,
        "supports_tool_calling": True,
        "supports_vision": True,
        "input_cost_per_1k": 0.00125,
        "output_cost_per_1k": 0.005,
    },
}

# Default model if none specified — the stable alias avoids deprecation 404s.
DEFAULT_MODEL = "gemini-flash-latest"

# Role mapping from FRIDAY/OpenAI format to Gemini format
# Gemini uses "user" and "model" roles
ROLE_MAPPING = {
    "user": "user",
    "assistant": "model",
    "system": "user",  # Gemini handles system prompts differently
    "tool": "user",  # Tool results are sent as user messages
}


class Gemini_Adapter(Provider_Adapter):
    """Provider adapter for Google Gemini models.
    
    This adapter implements the Provider_Adapter interface for Google's AI API,
    supporting Gemini 1.5 Pro, Gemini 1.5 Flash, and Gemini Pro models.
    
    The adapter handles:
    - Message format translation from FRIDAY format to Gemini content format
    - Synchronous and streaming response generation
    - Tool/function calling translation using Gemini's function declarations
    - Error handling with proper error classification
    - Health monitoring and metrics tracking
    
    Gemini-specific notes:
    - Gemini uses "parts" array for content
    - Role mapping: user → user, assistant → model
    - System instructions are handled via GenerativeModel configuration
    - Function calling uses "function_declarations" format
    
    Attributes:
        _key_store: API_Key_Store instance for retrieving the Gemini API key
        _client: Gemini GenerativeModel instance (lazy initialized)
        _metrics: Request metrics for health monitoring
        _last_error: Most recent error message
        _last_error_time: Timestamp of the last error
    
    Example:
        from friday.modules.providers import API_Key_Store
        
        key_store = API_Key_Store()
        key_store.load_from_env()
        
        adapter = Gemini_Adapter(key_store)
        if adapter.is_configured():
            response = adapter.generate([
                {"role": "user", "content": "Hello!"}
            ])
            print(response.content)
    
    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
    """

    def __init__(self, key_store: "API_Key_Store") -> None:
        """Initialize the Gemini adapter.
        
        Args:
            key_store: API_Key_Store instance for retrieving the Gemini API key.
                The key should be loaded from the GOOGLE_AI_API_KEY environment variable.
        """
        self._key_store = key_store
        self._genai: Optional[Any] = None  # Lazy initialized google.generativeai module
        self._metrics = ProviderMetrics()
        self._last_error: Optional[str] = None
        self._last_error_time: Optional[datetime] = None


    @property
    def provider_name(self) -> str:
        """Return the provider identifier.
        
        Returns:
            'gemini' - the unique identifier for this provider.
        """
        return "gemini"

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return the provider's capabilities.
        
        Returns:
            ProviderCapabilities describing Gemini's features including
            streaming, tool calling, vision support, and available models.
        """
        return ProviderCapabilities(
            supports_streaming=True,
            supports_tool_calling=True,
            supports_vision=True,  # Gemini 1.5 models support vision
            max_context_window=1048576,  # Gemini 1.5's context window
            supported_models=list(GEMINI_MODELS.keys()),
        )

    def _get_genai(self) -> Any:
        """Get the configured google.generativeai module.
        
        Lazy initializes and configures the Google AI SDK on first use.
        
        Returns:
            The configured google.generativeai module.
            
        Raises:
            ImportError: If the google-generativeai library is not installed.
            ValueError: If the Google AI API key is not configured.
        """
        if self._genai is None:
            try:
                import google.generativeai as genai
            except ImportError:
                raise ImportError(
                    "The 'google-generativeai' library is required for Gemini integration. "
                    "Install it with: pip install google-generativeai"
                )
            
            api_key = self._key_store.get_key("gemini")
            if not api_key:
                raise ValueError("Google AI API key is not configured")
            
            genai.configure(api_key=api_key)
            self._genai = genai
        
        return self._genai


    def _reset_client(self) -> None:
        """Reset the Gemini client.
        
        Forces re-configuration on next use. This is useful when
        the API key has been updated.
        """
        self._genai = None

    def is_configured(self) -> bool:
        """Check if the provider has valid configuration.
        
        Checks if a Google AI API key is configured in the key store.
        Does not make network calls.
        
        Returns:
            True if a Google AI API key is configured, False otherwise.
            
        Requirement: 4.1
        """
        return self._key_store.is_configured("gemini")

    def validate_config(self) -> tuple[bool, Optional[str]]:
        """Validate configuration by making a test API call.
        
        Attempts to list models from the Google AI API to verify the API key
        is valid and the service is accessible.
        
        Returns:
            Tuple of (is_valid, error_message) where:
            - is_valid: True if configuration is valid and API is accessible
            - error_message: None if valid, or a descriptive error message
            
        Requirement: 4.1
        """
        if not self.is_configured():
            return False, "Google AI API key is not configured"
        
        try:
            genai = self._get_genai()
            # Make a lightweight API call to verify the key
            list(genai.list_models())
            return True, None
        except ImportError as e:
            return False, str(e)
        except Exception as e:
            error_message = self._extract_error_message(e)
            return False, error_message


    def _translate_messages(self, messages: list[dict[str, str]]) -> tuple[list[dict[str, Any]], Optional[str]]:
        """Translate FRIDAY messages to Gemini content format.
        
        Property 4: Message Format Translation
        For any valid FRIDAY message format (with role, content, and optional metadata)
        and for Gemini, the adapter's message translation SHALL produce a valid message
        in Gemini's generateContent format.
        
        FRIDAY message format:
        {
            "role": "system" | "user" | "assistant" | "tool",
            "content": str,
            "name": Optional[str],  # For tool messages
            "tool_call_id": Optional[str],  # For tool result messages
        }
        
        Gemini content format:
        {
            "role": "user" | "model",
            "parts": [{"text": str}] | [{"function_response": {...}}]
        }
        
        Args:
            messages: List of messages in FRIDAY format
            
        Returns:
            Tuple of (gemini_contents, system_instruction) where:
            - gemini_contents: List of messages in Gemini content format
            - system_instruction: Extracted system prompt (if any)
        """
        gemini_contents = []
        system_instruction = None
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # Extract system instruction (Gemini handles this separately)
            if role == "system":
                system_instruction = content
                continue
            
            # Handle tool/function result messages
            if role == "tool":
                tool_call_id = msg.get("tool_call_id", "")
                name = msg.get("name", "unknown_function")
                
                # Try to parse content as JSON for function response
                try:
                    response_data = json.loads(content) if content else {}
                except json.JSONDecodeError:
                    response_data = {"result": content}
                
                gemini_contents.append({
                    "role": "user",
                    "parts": [{
                        "function_response": {
                            "name": name,
                            "response": response_data,
                        }
                    }]
                })
                continue

            
            # Handle assistant messages with tool calls
            if role == "assistant" and "tool_calls" in msg:
                parts = []
                # Add text content if present
                if content:
                    parts.append({"text": content})
                # Add function calls
                for tc in msg["tool_calls"]:
                    func = tc.get("function", {})
                    args_str = func.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except json.JSONDecodeError:
                        args = {}
                    
                    parts.append({
                        "function_call": {
                            "name": func.get("name", ""),
                            "args": args,
                        }
                    })
                
                gemini_contents.append({
                    "role": "model",
                    "parts": parts,
                })
                continue
            
            # Map role to Gemini format
            gemini_role = ROLE_MAPPING.get(role, "user")
            
            gemini_contents.append({
                "role": gemini_role,
                "parts": [{"text": content}],
            })
        
        return gemini_contents, system_instruction


    def generate(
        self,
        messages: list[dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> GenerateResponse:
        """Generate a response from Gemini.
        
        Sends messages to Gemini's generateContent API and returns the response
        in FRIDAY's unified format.
        
        Args:
            messages: Chat messages in FRIDAY format
            model: Specific model to use (default: gemini-1.5-pro)
            max_tokens: Maximum tokens in response (default: 1024)
            temperature: Sampling temperature 0.0-2.0 (default: 0.7)
            tools: Tool definitions in FRIDAY format (will be translated)
            
        Returns:
            GenerateResponse with unified response data
            
        Raises:
            ProviderError: On API errors
            
        Requirements: 4.1, 4.2, 4.3, 4.5
        """
        start_time = time.time()
        model_name = model or DEFAULT_MODEL
        
        try:
            genai = self._get_genai()
            
            # Translate messages to Gemini format
            gemini_contents, system_instruction = self._translate_messages(messages)
            
            # Build generation config
            generation_config = genai.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            )
            
            # Create model with optional system instruction
            model_kwargs: dict[str, Any] = {
                "model_name": model_name,
                "generation_config": generation_config,
            }
            
            if system_instruction:
                model_kwargs["system_instruction"] = system_instruction
            
            # Add tools if provided
            if tools:
                translated_tools = self.translate_tools(tools)
                if translated_tools:
                    model_kwargs["tools"] = translated_tools
            
            generative_model = genai.GenerativeModel(**model_kwargs)

            
            # Make the API call
            response = generative_model.generate_content(gemini_contents)
            
            # Extract response data
            content = ""
            tool_calls = None
            finish_reason = "stop"
            
            if response.candidates:
                candidate = response.candidates[0]
                
                # Extract text content
                if candidate.content and candidate.content.parts:
                    text_parts = []
                    function_calls = []
                    
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text:
                            text_parts.append(part.text)
                        if hasattr(part, 'function_call') and part.function_call:
                            function_calls.append(part.function_call)
                    
                    content = "".join(text_parts)
                    
                    # Parse function calls if present
                    if function_calls:
                        tool_calls = self._parse_function_calls(function_calls)
                        finish_reason = "tool_calls"
                
                # Map finish reason
                if hasattr(candidate, 'finish_reason'):
                    fr = str(candidate.finish_reason)
                    if "STOP" in fr:
                        finish_reason = "stop"
                    elif "MAX_TOKENS" in fr:
                        finish_reason = "length"
                    elif "SAFETY" in fr:
                        finish_reason = "content_filter"
            
            # Extract usage information
            usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
            
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage["prompt_tokens"] = getattr(response.usage_metadata, 'prompt_token_count', 0)
                usage["completion_tokens"] = getattr(response.usage_metadata, 'candidates_token_count', 0)
                usage["total_tokens"] = getattr(response.usage_metadata, 'total_token_count', 0)

            
            # Record success metrics
            latency_ms = (time.time() - start_time) * 1000
            self._record_success(latency_ms)
            
            return GenerateResponse(
                content=content,
                model=model_name,
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
        """Stream response tokens from Gemini.
        
        Uses Gemini's streaming API to yield tokens as they arrive,
        providing a better user experience for longer responses.
        
        Args:
            messages: Chat messages in FRIDAY format
            model: Specific model to use (default: gemini-1.5-pro)
            max_tokens: Maximum tokens in response (default: 1024)
            temperature: Sampling temperature 0.0-2.0 (default: 0.7)
            
        Yields:
            String tokens as they arrive from Gemini
            
        Requirement: 4.4
        """
        start_time = time.time()
        model_name = model or DEFAULT_MODEL
        
        try:
            genai = self._get_genai()
            
            # Translate messages to Gemini format
            gemini_contents, system_instruction = self._translate_messages(messages)

            
            # Build generation config
            generation_config = genai.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            )
            
            # Create model with optional system instruction
            model_kwargs: dict[str, Any] = {
                "model_name": model_name,
                "generation_config": generation_config,
            }
            
            if system_instruction:
                model_kwargs["system_instruction"] = system_instruction
            
            generative_model = genai.GenerativeModel(**model_kwargs)
            
            # Create streaming request
            response_stream = generative_model.generate_content(
                gemini_contents,
                stream=True,
            )
            
            # Yield tokens as they arrive
            for chunk in response_stream:
                if chunk.text:
                    yield chunk.text
            
            # Record success
            latency_ms = (time.time() - start_time) * 1000
            self._record_success(latency_ms)
            
        except Exception as e:
            # Record failure
            self._record_failure(str(e))
            raise self._create_provider_error(e)


    def translate_tools(self, friday_tools: list[dict]) -> list[dict]:
        """Translate FRIDAY tool definitions to Gemini's function declarations format.
        
        FRIDAY uses OpenAI-compatible format internally. This method converts
        those definitions to Gemini's function declarations format.
        
        Property 5: Tool Definition Translation
        For any valid FRIDAY tool definition (in OpenAI-compatible format with
        name, description, parameters) and for Gemini, the translate_tools()
        method SHALL produce a valid tool definition in Gemini's native format.
        
        Args:
            friday_tools: Tools in FRIDAY/OpenAI-compatible format. Can be:
                - Full format: {"type": "function", "function": {...}}
                - Simplified format: {"name": ..., "description": ..., "parameters": ...}
            
        Returns:
            Tools in Gemini's function declarations format.
            Returns empty list for None/empty/invalid input.
            
        Requirement: 4.5, 12.1
        """
        # Handle None/empty input
        if not friday_tools:
            return []
        
        # Ensure we have a list
        if not isinstance(friday_tools, list):
            logger.warning(f"translate_tools expected list, got {type(friday_tools).__name__}")
            return []
        
        function_declarations = []
        
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
                func_decl = self._normalize_tool_to_gemini(tool)
                if func_decl:
                    function_declarations.append(func_decl)
            except Exception as e:
                logger.warning(f"Failed to translate tool at index {idx}: {e}")
                continue
        
        return function_declarations


    def _normalize_tool_to_gemini(self, tool: dict) -> Optional[dict]:
        """Normalize a single tool definition to Gemini function declaration format.
        
        Args:
            tool: Tool definition in any supported format
            
        Returns:
            Normalized tool in Gemini format, or None if invalid
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
                "parameters": self._normalize_parameters_for_gemini(func_def.get("parameters")),
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
                "parameters": self._normalize_parameters_for_gemini(tool.get("parameters")),
            }
        
        # Unknown format
        logger.warning("Unrecognized tool format, missing 'name' or 'type'='function' with 'function' field")
        return None


    def _normalize_parameters_for_gemini(self, parameters: Any) -> dict:
        """Normalize tool parameters to Gemini's expected format.
        
        Gemini expects JSON Schema format for parameters.
        
        Args:
            parameters: Parameters definition (dict, None, or other)
            
        Returns:
            Valid JSON Schema object for Gemini
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


    def _parse_function_calls(self, function_calls: list[Any]) -> list[dict]:
        """Parse Gemini function calls to FRIDAY format.
        
        Args:
            function_calls: List of Gemini FunctionCall objects
            
        Returns:
            List of tool calls in FRIDAY format
        """
        tool_calls = []
        
        for idx, fc in enumerate(function_calls):
            try:
                # Extract function name
                name = getattr(fc, 'name', '') or ''
                
                # Extract arguments
                args = {}
                if hasattr(fc, 'args') and fc.args:
                    # Gemini returns args as a dict-like object
                    args = dict(fc.args)
                
                tool_calls.append({
                    "id": f"call_{idx}_{name}",  # Gemini doesn't provide IDs
                    "function": {
                        "name": name,
                        "arguments": args,
                    }
                })
            except Exception as e:
                logger.warning(f"Failed to parse function call at index {idx}: {e}")
                continue
        
        return tool_calls

    def parse_tool_calls(self, response: Any) -> list[dict]:
        """Parse tool calls from Gemini response to FRIDAY format.
        
        Property 6: Tool Call Parsing
        For any valid tool call response from Gemini, parse_tool_calls() SHALL
        produce a list of FRIDAY ToolCall objects with correctly extracted id,
        function_name, and arguments.
        
        Args:
            response: Gemini response which can be:
                - GenerateContentResponse with candidates
                - Dict with "candidates" key
                - List of function call objects
                - None or empty (returns empty list)
            
        Returns:
            List of tool calls in FRIDAY's format:
            [{"id": str, "function": {"name": str, "arguments": dict}}]
            
        Requirement: 12.2
        """
        # Handle None/empty input
        if response is None:
            return []
        
        tool_calls = []

        
        # Handle Gemini GenerateContentResponse
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and candidate.content:
                if hasattr(candidate.content, 'parts'):
                    function_calls = []
                    for part in candidate.content.parts:
                        if hasattr(part, 'function_call') and part.function_call:
                            function_calls.append(part.function_call)
                    if function_calls:
                        return self._parse_function_calls(function_calls)
        
        # Handle dict format
        if isinstance(response, dict):
            candidates = response.get("candidates", [])
            if candidates:
                candidate = candidates[0]
                content = candidate.get("content", {})
                parts = content.get("parts", [])
                function_calls = []
                for part in parts:
                    if "function_call" in part:
                        function_calls.append(part["function_call"])
                if function_calls:
                    return self._parse_dict_function_calls(function_calls)
        
        # Handle list of function calls directly
        if isinstance(response, list):
            return self._parse_function_calls(response)
        
        return tool_calls

    def _parse_dict_function_calls(self, function_calls: list[dict]) -> list[dict]:
        """Parse function calls from dict format to FRIDAY format.
        
        Args:
            function_calls: List of function call dicts from Gemini
            
        Returns:
            List of tool calls in FRIDAY format
        """
        tool_calls = []
        
        for idx, fc in enumerate(function_calls):
            if not isinstance(fc, dict):
                continue
                
            name = fc.get("name", "")
            args = fc.get("args", {})
            
            if not isinstance(args, dict):
                args = {}
            
            tool_calls.append({
                "id": f"call_{idx}_{name}",
                "function": {
                    "name": name,
                    "arguments": args,
                }
            })
        
        return tool_calls


    def get_available_models(self) -> list[dict[str, Any]]:
        """Get list of available Gemini models.
        
        Returns information about supported models including context window,
        capabilities, and pricing.
        
        Returns:
            List of ModelInfo-like dicts with model specifications
            
        Requirement: 4.2
        """
        models = []
        
        for model_id, spec in GEMINI_MODELS.items():
            models.append({
                "id": model_id,
                "name": spec["name"],
                "provider": ProviderType.GEMINI.value,
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
        
        # Try to extract message from Gemini API errors
        if hasattr(error, 'message'):
            return error.message
        
        return error_str

    def _create_provider_error(self, error: Exception) -> ProviderError:
        """Create a ProviderError from an exception.
        
        Handles Gemini-specific error types with proper classification.
        
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

        
        # Check for rate limit errors (429 status)
        if "429" in str(error) or "resource_exhausted" in error_str or "quota" in error_str:
            error_type = "rate_limit"
            retry_after = self._extract_retry_after(error)
            is_retryable = True
            
        # Check for authentication errors (401/403 status)
        elif "401" in str(error) or "403" in str(error) or "invalid" in error_str and "key" in error_str:
            error_type = "auth"
            is_retryable = False
            
        # Check for permission errors
        elif "permission" in error_str or "forbidden" in error_str:
            error_type = "auth"
            is_retryable = False
            
        # Check for timeout errors
        elif "timeout" in error_str or "deadline" in error_str:
            error_type = "timeout"
            is_retryable = True
            
        # Check for connection errors
        elif "connection" in error_str or "network" in error_str or "unreachable" in error_str:
            error_type = "connection"
            is_retryable = True
            
        # Check for server errors (5xx status)
        elif "500" in str(error) or "502" in str(error) or "503" in str(error) or "internal" in error_str:
            error_type = "server"
            is_retryable = True
            
        # Check for content safety errors
        elif "safety" in error_str or "blocked" in error_str:
            error_type = "content_filter"
            is_retryable = False
            
        # Check for invalid request errors
        elif "invalid" in error_str and "argument" in error_str:
            error_type = "bad_request"
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
        error_str = str(error)
        
        # Try to extract from error message
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
