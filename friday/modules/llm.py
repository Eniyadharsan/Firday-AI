"""LLM module — communicates with Cerebras AI.

Optimized for low latency:
- Persistent HTTP session with connection pooling
- Reduced timeout (12s instead of 20s) for faster fallback
- json import at module level (not per-chunk in streaming)
"""

from __future__ import annotations

import json
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger
from friday.config import CEREBRAS_API_KEY, LLM_MODELS, LLM_MAX_TOKENS, LLM_TEMPERATURE
from friday.modules.tool_calling.models import ToolCall, ToolSelectionResult

API_URL = "https://api.cerebras.ai/v1/chat/completions"

# Connection pool — reuse TCP/TLS connections
_session = requests.Session()
_session.headers.update({
    "Authorization": f"Bearer {CEREBRAS_API_KEY}",
    "Content-Type": "application/json",
})
_adapter = HTTPAdapter(
    pool_connections=5,
    pool_maxsize=10,
    max_retries=Retry(total=1, backoff_factor=0.3, status_forcelist=[502, 503, 504]),
)
_session.mount("https://", _adapter)


def _resolve_temperature(temperature) -> float:
    """Clamp a requested temperature to a safe range, falling back to default."""
    if temperature is None:
        return LLM_TEMPERATURE
    try:
        return max(0.0, min(1.5, float(temperature)))
    except (TypeError, ValueError):
        return LLM_TEMPERATURE


def _resolve_models(model) -> list[str]:
    """Build the model fallback order, honoring a valid requested model first.

    Only models present in the configured LLM_MODELS allowlist are accepted;
    unknown/invalid requests are ignored and the default order is used.
    """
    if model and isinstance(model, str) and model in LLM_MODELS:
        return [model] + [m for m in LLM_MODELS if m != model]
    return list(LLM_MODELS)


def generate(messages: list[dict[str, str]], max_tokens: int = None,
             model: str = None, temperature: float = None) -> str:
    """Generate a response from the LLM with model fallback.

    Args:
        messages: Chat messages in OpenAI format
        max_tokens: Override default max_tokens (useful for short replies)
        model: Preferred model id (must be in LLM_MODELS, else ignored)
        temperature: Sampling temperature 0-1.5 (clamped; None uses default)
    """
    if not CEREBRAS_API_KEY:
        return "FRIDAY needs CEREBRAS_API_KEY to function."
    if CEREBRAS_API_KEY == "your-cerebras-api-key":
        return "FRIDAY needs a valid CEREBRAS_API_KEY. Get one from cloud.cerebras.ai"

    tokens = max_tokens or LLM_MAX_TOKENS
    temp = _resolve_temperature(temperature)

    for model in _resolve_models(model):
        try:
            response = _session.post(
                API_URL,
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": tokens,
                    "temperature": temp,
                },
                timeout=8,
            )
            if response.status_code == 429:
                logger.warning(f"Rate limited on {model}, trying fallback...")
                continue
            if response.status_code == 401:
                logger.error("Invalid API key")
                return "API key error. Check CEREBRAS_API_KEY."
            if response.status_code >= 500:
                logger.error(f"Server error on {model}: {response.status_code}")
                continue
            response.raise_for_status()
            data = response.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "No response.")
        except requests.Timeout:
            logger.warning(f"Timeout on {model}")
            continue
        except Exception as e:
            logger.error(f"LLM error on {model}: {e}")
            continue

    return "AI temporarily unavailable. Try again in a moment."


def stream_generate(messages: list[dict[str, str]], model: str = None, temperature: float = None):
    """Stream tokens from LLM (generator). Lower perceived latency."""
    if not CEREBRAS_API_KEY:
        yield "FRIDAY needs CEREBRAS_API_KEY."
        return

    model = _resolve_models(model)[0]
    temp = _resolve_temperature(temperature)
    try:
        response = _session.post(
            API_URL,
            json={
                "model": model,
                "messages": messages,
                "max_tokens": LLM_MAX_TOKENS,
                "temperature": temp,
                "stream": True,
            },
            timeout=30,
            stream=True,
        )
        response.raise_for_status()
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
    except Exception as e:
        logger.error(f"Stream error: {e}")
        yield "Error generating response."


def select_tools(
    message: str,
    tools: list[dict[str, Any]],
    tool_choice: str = "auto",
    timeout: float = 3.0,
) -> ToolSelectionResult:
    """Send message to Cerebras with tool definitions and return tool selection.

    Uses the existing connection pool (_session) for HTTP requests to minimize
    connection overhead. Implements a 3-second timeout for tool selection with
    error handling for connection failures, HTTP errors, and parse failures.

    Args:
        message: User message to route
        tools: Tool definitions in OpenAI format (list of tool objects with
            type="function" and function={name, description, parameters})
        tool_choice: Control tool selection behavior:
            - "auto": LLM decides whether to call tools (default)
            - "none": LLM will not call any tools
            - specific tool name: Force the LLM to call that tool
        timeout: Request timeout in seconds (default: 3.0)

    Returns:
        ToolSelectionResult containing:
        - tool_calls: List of ToolCall objects if tools were selected
        - assistant_content: Response text if no tools were selected
        - error: Error message if request failed

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 9.3**
    """
    # Check API key availability
    if not CEREBRAS_API_KEY:
        return ToolSelectionResult(error="CEREBRAS_API_KEY not configured")
    if CEREBRAS_API_KEY == "your-cerebras-api-key":
        return ToolSelectionResult(error="Invalid CEREBRAS_API_KEY")

    # Build the request payload
    # Requirement 2.1: Include tools parameter with Tool_Registry definitions
    # Requirement 2.5: Support tool_choice parameter
    payload: dict[str, Any] = {
        "model": _resolve_models(None)[0],  # Use default model
        "messages": [{"role": "user", "content": message}],
        "tools": tools,
        "tool_choice": tool_choice,
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": _resolve_temperature(None),
    }

    try:
        # Requirement 9.3: Reuse HTTP connections via connection pooling
        response = _session.post(
            API_URL,
            json=payload,
            timeout=timeout,  # 3-second timeout for tool selection
        )

        # Requirement 2.4: Handle HTTP error status codes (4xx or 5xx)
        if response.status_code >= 400:
            error_msg = f"HTTP {response.status_code}"
            if response.status_code >= 500:
                error_msg = f"http_{response.status_code}"
            elif response.status_code >= 400:
                error_msg = f"http_{response.status_code}"
            logger.warning(f"Tool selection HTTP error: {error_msg}")
            return ToolSelectionResult(error=error_msg)

        # Parse the JSON response
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            logger.error(f"Tool selection parse error: {e}")
            return ToolSelectionResult(error="parse_error")

        # Extract the message from the response
        choices = data.get("choices", [])
        if not choices:
            return ToolSelectionResult(error="parse_error")

        message_data = choices[0].get("message", {})

        # Requirement 2.2: Parse tool_calls if present
        raw_tool_calls = message_data.get("tool_calls")

        if raw_tool_calls:
            # Parse each tool call
            parsed_calls: list[ToolCall] = []
            for tc in raw_tool_calls:
                try:
                    # Requirement 2.6: Validate tool_calls have required fields
                    tc_id = tc.get("id")
                    function_data = tc.get("function", {})
                    function_name = function_data.get("name")
                    arguments_str = function_data.get("arguments", "{}")

                    # Check for missing or invalid function name
                    if not function_name or not isinstance(function_name, str):
                        logger.error(f"Tool call missing or invalid function name: {tc}")
                        return ToolSelectionResult(error="parse_error")

                    # Check for missing id
                    if not tc_id:
                        logger.error(f"Tool call missing id: {tc}")
                        return ToolSelectionResult(error="parse_error")

                    # Parse arguments JSON
                    try:
                        arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
                        if not isinstance(arguments, dict):
                            arguments = {}
                    except json.JSONDecodeError:
                        logger.error(f"Tool call unparseable arguments: {arguments_str}")
                        return ToolSelectionResult(error="parse_error")

                    parsed_calls.append(ToolCall(
                        id=tc_id,
                        function_name=function_name,
                        arguments=arguments,
                    ))

                except Exception as e:
                    # Requirement 2.6: Malformed tool_calls treated as parse failure
                    logger.error(f"Error parsing tool call: {e}")
                    return ToolSelectionResult(error="parse_error")

            return ToolSelectionResult(tool_calls=parsed_calls)

        # Requirement 2.3: If no tool_calls, return assistant content
        assistant_content = message_data.get("content")
        return ToolSelectionResult(assistant_content=assistant_content)

    except requests.Timeout:
        # Requirement 2.4: Handle request timeout exceeding 3 seconds
        logger.warning(f"Tool selection timeout after {timeout}s")
        return ToolSelectionResult(error="timeout")

    except requests.ConnectionError as e:
        # Requirement 2.4: Handle connection failures
        logger.error(f"Tool selection connection error: {e}")
        return ToolSelectionResult(error="connection_error")

    except requests.RequestException as e:
        # General request errors
        logger.error(f"Tool selection request error: {e}")
        return ToolSelectionResult(error="connection_error")

    except Exception as e:
        # Catch-all for unexpected errors
        logger.error(f"Tool selection unexpected error: {e}")
        return ToolSelectionResult(error="parse_error")
