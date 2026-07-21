"""Intent Router for LLM-based tool selection and execution.

This module implements the IntentRouter class that orchestrates tool selection
via the Cerebras API and routes requests to capability handlers. It replaces
regex-based pattern matching with semantic LLM understanding.

The router follows this flow:
1. Get tool definitions from the registry
2. Send to Cerebras for tool selection (3s timeout)
3. On success: validate parameters and execute tool call(s) and format response
4. On failure: delegate to FallbackRouter

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 10.1, 10.2, 10.3**
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable

from loguru import logger

from friday.modules.tool_calling.models import (
    FallbackResult,
    RoutingResult,
    ToolCall,
    ToolSelectionResult,
)
from friday.modules.tool_calling.registry import ToolRegistry
from friday.modules.tool_calling.fallback import FallbackRouter
from friday.modules import llm


def _get_iso_timestamp() -> str:
    """Return current UTC timestamp in ISO 8601 format for structured logging."""
    return datetime.now(timezone.utc).isoformat()


def _truncate_error_message(message: str, max_length: int = 1000) -> str:
    """Truncate error message to maximum length, preserving useful content.

    Args:
        message: The error message to truncate.
        max_length: Maximum allowed length (default 1000 chars per Requirement 10.3).

    Returns:
        Truncated message with ellipsis if needed.
    """
    if len(message) <= max_length:
        return message
    return message[: max_length - 3] + "..."


def _serialize_arguments(arguments: dict[str, Any]) -> str:
    """Serialize arguments dictionary to a JSON string for logging.

    Args:
        arguments: The arguments dictionary to serialize.

    Returns:
        JSON string representation of arguments.
    """
    try:
        return json.dumps(arguments, default=str)
    except (TypeError, ValueError):
        return str(arguments)


# Maximum number of tool calls to execute per request (Requirement 3.4)
MAX_TOOL_CALLS = 5


class IntentRouter:
    """Routes user messages to capability handlers via LLM tool selection.

    The IntentRouter orchestrates the tool calling workflow:
    1. Retrieves tool definitions from the ToolRegistry
    2. Sends the user message to Cerebras for tool selection
    3. On success: executes tool calls and formats the response
    4. On failure: delegates to the FallbackRouter for regex-based routing

    Attributes:
        _registry: The ToolRegistry containing available tool definitions.
        _client: Reference to the llm module for Cerebras API calls.
        _fallback: The FallbackRouter for backup routing.
        _handlers: Dictionary mapping tool names to capability handlers.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        cerebras_client: Any,  # The llm module
        fallback_router: FallbackRouter,
    ) -> None:
        """Initialize the IntentRouter.

        Args:
            tool_registry: The ToolRegistry instance containing tool definitions.
            cerebras_client: The Cerebras client module (llm) for API calls.
            fallback_router: The FallbackRouter for backup routing.
        """
        self._registry = tool_registry
        self._client = cerebras_client
        self._fallback = fallback_router
        self._handlers: dict[str, Callable] = {}

    def register_handler(self, tool_name: str, handler: Callable) -> None:
        """Register a capability handler for a tool name.

        Args:
            tool_name: The name of the tool (must match a registered tool).
            handler: A callable that processes requests for this tool.
                Should accept keyword arguments matching the tool's parameters.
        """
        self._handlers[tool_name] = handler
        logger.debug(f"Registered handler for tool: {tool_name}")

    def route(
        self,
        message: str,
        session_id: str,
        user_id: str,
    ) -> RoutingResult:
        """Route a user message to the appropriate handler(s).

        Flow:
        1. Get tool definitions from registry
        2. Send to Cerebras for tool selection (3s timeout)
        3. On success: execute tool call(s) and format response
        4. On failure: delegate to FallbackRouter

        Args:
            message: The user's message to route.
            session_id: The session identifier.
            user_id: The user identifier.

        Returns:
            RoutingResult containing the response, handler used, fallback status,
            and latency in milliseconds.

        **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**
        """
        start_time = time.time()

        # Step 1: Get tool definitions from registry (Requirement 3.1)
        tools = self._registry.get_openai_format()

        # Step 2: Send to Cerebras for tool selection with 3s timeout
        selection_result: ToolSelectionResult = self._client.select_tools(
            message=message,
            tools=tools,
            tool_choice="auto",
            timeout=3.0,
        )

        latency_ms = (time.time() - start_time) * 1000

        # Step 3: Handle errors - delegate to FallbackRouter (Requirement 2.4, 5.1, 5.2)
        if selection_result.is_error:
            logger.warning(
                f"Tool selection error: {selection_result.error}, "
                f"delegating to fallback router"
            )
            return self._handle_fallback(
                message=message,
                session_id=session_id,
                user_id=user_id,
                trigger_reason=selection_result.error or "unknown_error",
                latency_ms=latency_ms,
            )

        # Step 4: If no tool calls but has assistant content, return it directly
        # (Requirement 3.5)
        if not selection_result.has_tool_calls:
            logger.info("No tool calls returned, using assistant content")
            return RoutingResult(
                response={
                    "reply": selection_result.assistant_content or "",
                    "sessionId": session_id,
                    "action": "chat",
                },
                handler_used="default_chat",
                is_fallback=False,
                latency_ms=latency_ms,
            )

        # Step 5: Execute tool calls (Requirement 3.2, 3.3, 3.4)
        tool_calls = selection_result.tool_calls

        # Log tool selection completion for each tool (Requirement 10.1)
        for tool_call in tool_calls:
            logger.info(
                "Tool selection completed: "
                f"timestamp={_get_iso_timestamp()} "
                f"tool_name={tool_call.function_name} "
                f"arguments={_serialize_arguments(tool_call.arguments)} "
                f"latency_ms={latency_ms:.2f}"
            )

        results = self._execute_tool_calls(
            tool_calls=tool_calls,
            session_id=session_id,
            user_id=user_id,
        )

        # Step 6: Format and return the response
        # Single tool call - return the result directly
        if len(results) == 1:
            result = results[0]
            if result.get("error"):
                return RoutingResult(
                    response={
                        "reply": result["error"],
                        "sessionId": session_id,
                        "action": "error",
                    },
                    handler_used=result.get("tool", "unknown"),
                    is_fallback=False,
                    latency_ms=latency_ms,
                )
            return RoutingResult(
                response=result.get("result", {}),
                handler_used=result.get("tool", "unknown"),
                is_fallback=False,
                latency_ms=latency_ms,
            )

        # Multiple tool calls - return combined response (Requirement 6.3, 6.4)
        return RoutingResult(
            response={
                "reply": f"Completed {len(results)} actions.",
                "sessionId": session_id,
                "action": "multi_result",
                "results": results,
            },
            handler_used="multi_tool",
            is_fallback=False,
            latency_ms=latency_ms,
        )

    def _validate_parameters(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str | None:
        """Validate extracted parameters against JSON Schema constraints.

        Validates parameters according to the tool's JSON Schema definition:
        - Required parameters must be present and non-empty
        - String parameters must satisfy minLength/maxLength bounds
        - Enum parameters must match one of the declared values

        Args:
            tool_name: The name of the tool to validate parameters for.
            arguments: The extracted arguments from the tool call.

        Returns:
            None if all validations pass, or an error message string
            describing the first validation failure.

        **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7**
        """
        # Get the tool definition from the registry
        tool_def = self._registry.get_tool(tool_name)
        if tool_def is None:
            return f"Unknown tool: {tool_name}"

        parameters_schema = tool_def.parameters
        properties = parameters_schema.get("properties", {})
        required_fields = parameters_schema.get("required", [])

        # Validate required parameters are present and non-empty
        for field_name in required_fields:
            if field_name not in arguments:
                return f"Missing required parameter: {field_name}"

            value = arguments[field_name]
            # Check for empty strings (non-empty requirement)
            if isinstance(value, str) and len(value.strip()) == 0:
                return f"Required parameter '{field_name}' cannot be empty"

        # Validate each provided argument against its schema
        for param_name, param_value in arguments.items():
            if param_name not in properties:
                # Allow unknown parameters (lenient validation)
                continue

            param_schema = properties[param_name]
            param_type = param_schema.get("type")

            # Validate string constraints
            if param_type == "string" and isinstance(param_value, str):
                # Check minLength constraint
                min_length = param_schema.get("minLength")
                if min_length is not None and len(param_value) < min_length:
                    return (
                        f"Parameter '{param_name}' must be at least "
                        f"{min_length} character(s), got {len(param_value)}"
                    )

                # Check maxLength constraint
                max_length = param_schema.get("maxLength")
                if max_length is not None and len(param_value) > max_length:
                    return (
                        f"Parameter '{param_name}' must be at most "
                        f"{max_length} character(s), got {len(param_value)}"
                    )

                # Check enum constraint
                enum_values = param_schema.get("enum")
                if enum_values is not None and param_value not in enum_values:
                    return (
                        f"Parameter '{param_name}' must be one of "
                        f"{enum_values}, got '{param_value}'"
                    )

        return None

    def _execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        session_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """Execute tool calls sequentially (max 5 per request).

        Executes each tool call in order, collecting results. If a tool call
        fails validation or execution, the error is recorded but execution
        continues for remaining tools.

        Args:
            tool_calls: List of ToolCall objects to execute.
            session_id: The session identifier.
            user_id: The user identifier.

        Returns:
            List of result dictionaries, each containing:
            - tool: The tool name
            - success: Boolean indicating if execution succeeded
            - result: The handler result (if successful)
            - error: Error message (if failed)

        **Validates: Requirements 3.4, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 10.3**
        """
        results: list[dict[str, Any]] = []

        # Limit to MAX_TOOL_CALLS (Requirement 3.4)
        calls_to_execute = tool_calls[:MAX_TOOL_CALLS]

        if len(tool_calls) > MAX_TOOL_CALLS:
            logger.warning(
                f"Received {len(tool_calls)} tool calls, "
                f"executing only first {MAX_TOOL_CALLS}"
            )

        for tool_call in calls_to_execute:
            tool_name = tool_call.function_name
            arguments = tool_call.arguments

            logger.info(
                f"Executing tool: tool_name={tool_name} "
                f"arguments={_serialize_arguments(arguments)}"
            )

            # Check if tool name is registered (Requirement 3.7)
            if tool_name not in self._handlers:
                error_msg = f"Unknown capability: {tool_name}"
                # Log tool execution failure (Requirement 10.3)
                logger.error(
                    "Tool execution failed: "
                    f"timestamp={_get_iso_timestamp()} "
                    f"tool_name={tool_name} "
                    f"error_type=unknown_tool "
                    f"error_message={_truncate_error_message(error_msg)}"
                )
                results.append({
                    "tool": tool_name,
                    "success": False,
                    "result": None,
                    "error": error_msg,
                })
                continue

            # Validate parameters before execution (Requirements 7.1-7.7)
            validation_error = self._validate_parameters(tool_name, arguments)
            if validation_error is not None:
                # Log tool execution failure (Requirement 10.3)
                logger.error(
                    "Tool execution failed: "
                    f"timestamp={_get_iso_timestamp()} "
                    f"tool_name={tool_name} "
                    f"error_type=validation_error "
                    f"error_message={_truncate_error_message(validation_error)}"
                )
                results.append({
                    "tool": tool_name,
                    "success": False,
                    "result": None,
                    "error": validation_error,
                })
                continue

            # Execute the handler
            try:
                handler = self._handlers[tool_name]
                result = handler(
                    session_id=session_id,
                    user_id=user_id,
                    **arguments,
                )
                results.append({
                    "tool": tool_name,
                    "success": True,
                    "result": result,
                    "error": None,
                })
                logger.info(f"Tool executed successfully: tool_name={tool_name}")

            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e)
                # Log tool execution failure with structured fields (Requirement 10.3)
                logger.error(
                    "Tool execution failed: "
                    f"timestamp={_get_iso_timestamp()} "
                    f"tool_name={tool_name} "
                    f"error_type={error_type} "
                    f"error_message={_truncate_error_message(error_msg)}"
                )
                results.append({
                    "tool": tool_name,
                    "success": False,
                    "result": None,
                    "error": error_msg[:1000],  # Truncate error message
                })

        return results

    def _handle_fallback(
        self,
        message: str,
        session_id: str,
        user_id: str,
        trigger_reason: str,
        latency_ms: float,
    ) -> RoutingResult:
        """Handle fallback routing when LLM tool selection fails.

        Delegates to the FallbackRouter and executes the resulting handler.

        Args:
            message: The original user message.
            session_id: The session identifier.
            user_id: The user identifier.
            trigger_reason: Why fallback was triggered (timeout, http_4xx, etc.).
            latency_ms: The latency accumulated so far.

        Returns:
            RoutingResult from fallback routing.

        **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 10.2**
        """
        # Get fallback routing decision first to include in log
        fallback_result: FallbackResult = self._fallback.route(
            message=message,
            trigger_reason=trigger_reason,
        )

        # Log the fallback event with structured fields (Requirement 10.2)
        logger.warning(
            "Fallback routing triggered: "
            f"timestamp={_get_iso_timestamp()} "
            f"trigger_reason={trigger_reason} "
            f"fallback_decision={fallback_result.handler_name}"
        )

        handler_name = fallback_result.handler_name
        parameters = fallback_result.parameters

        logger.info(
            f"Fallback routing to: handler={handler_name} params={_serialize_arguments(parameters)}"
        )

        # Handle default_chat case (Requirement 5.5)
        if handler_name == "default_chat":
            return RoutingResult(
                response={
                    "reply": "",  # Will be filled by chat handler
                    "sessionId": session_id,
                    "action": "chat",
                },
                handler_used="default_chat",
                is_fallback=True,
                latency_ms=latency_ms,
            )

        # Check if handler is registered
        if handler_name not in self._handlers:
            error_msg = f"Fallback handler not registered: {handler_name}"
            # Log fallback handler missing as tool execution failure (Requirement 10.3)
            logger.error(
                "Tool execution failed: "
                f"timestamp={_get_iso_timestamp()} "
                f"tool_name={handler_name} "
                f"error_type=handler_not_registered "
                f"error_message={_truncate_error_message(error_msg)}"
            )
            return RoutingResult(
                response={
                    "reply": f"Unable to process request. Handler '{handler_name}' not available.",
                    "sessionId": session_id,
                    "action": "error",
                },
                handler_used=handler_name,
                is_fallback=True,
                latency_ms=latency_ms,
            )

        # Execute the fallback handler
        try:
            handler = self._handlers[handler_name]
            result = handler(
                session_id=session_id,
                user_id=user_id,
                **parameters,
            )
            return RoutingResult(
                response=result,
                handler_used=handler_name,
                is_fallback=True,
                latency_ms=latency_ms,
            )

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            # Log fallback handler execution failure (Requirement 10.3)
            logger.error(
                "Tool execution failed: "
                f"timestamp={_get_iso_timestamp()} "
                f"tool_name={handler_name} "
                f"error_type={error_type} "
                f"error_message={_truncate_error_message(error_msg)}"
            )
            return RoutingResult(
                response={
                    "reply": f"Error executing {handler_name}: {error_msg[:500]}",
                    "sessionId": session_id,
                    "action": "error",
                },
                handler_used=handler_name,
                is_fallback=True,
                latency_ms=latency_ms,
            )
