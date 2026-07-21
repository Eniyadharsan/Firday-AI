"""Data models for the tool calling routing system.

This module defines the core data structures used across the tool calling
components: tool registry, Cerebras client, intent router, and fallback router.
All models are immutable dataclasses designed for type safety and clarity.

**Validates: Requirements 1.1, 1.2, 2.2, 3.2, 5.1**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    """A single tool definition conforming to OpenAI function calling schema.

    Attributes:
        name: Tool identifier, must be 1-64 characters.
        description: Human-readable description explaining when to use this tool,
            must be 1-1024 characters. Should include distinguishing keywords.
        parameters: JSON Schema object defining the tool's parameters.
            Must contain "type": "object" at minimum.
        handler_name: Maps to the capability handler module that processes
            requests for this tool (e.g., "music", "maps", "image").
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler_name: str

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format.

        Returns:
            Dictionary in the format expected by OpenAI-compatible APIs:
            {
                "type": "function",
                "function": {
                    "name": ...,
                    "description": ...,
                    "parameters": ...
                }
            }
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolRegistrationError:
    """Error returned when tool registration fails validation.

    Attributes:
        field: The field that failed validation ("name", "description", or "parameters").
        message: Human-readable description of the validation failure.
    """

    field: str
    message: str


@dataclass(frozen=True)
class ToolCall:
    """Parsed tool call from LLM response.

    Represents a single tool invocation request extracted from the Cerebras API
    response. Used by the Intent_Router to dispatch to capability handlers.

    Attributes:
        id: Unique identifier for this tool call from the API response.
        function_name: Name of the tool to invoke, must match a registered tool.
        arguments: Extracted parameters to pass to the tool handler.
    """

    id: str
    function_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolSelectionResult:
    """Result of tool selection request to Cerebras API.

    Contains either tool calls, assistant content, or an error. At most one
    of tool_calls (non-empty), assistant_content, or error will be meaningful.

    Attributes:
        tool_calls: List of tool calls if the LLM selected tools, empty list otherwise.
        assistant_content: Assistant's response text if no tools were selected,
            None if tools were selected or an error occurred.
        error: Error message if the request failed, None on success.
    """

    tool_calls: list[ToolCall] = field(default_factory=list)
    assistant_content: str | None = None
    error: str | None = None

    @property
    def has_tool_calls(self) -> bool:
        """Return True if tool calls were returned."""
        return len(self.tool_calls) > 0

    @property
    def is_error(self) -> bool:
        """Return True if an error occurred."""
        return self.error is not None


@dataclass(frozen=True)
class RoutingResult:
    """Result of intent routing.

    Contains the final response to return to the client along with metadata
    about how the request was processed.

    Attributes:
        response: JSON-serializable response to return to the client.
        handler_used: Name of the handler that processed the request
            (e.g., "music", "maps", "default_chat").
        is_fallback: True if fallback routing was used due to LLM failure.
        latency_ms: Tool selection latency in milliseconds.
    """

    response: dict[str, Any]
    handler_used: str
    is_fallback: bool
    latency_ms: float


@dataclass(frozen=True)
class FallbackResult:
    """Result of fallback routing using regex patterns.

    Returned by the Fallback_Router when LLM tool selection fails or times out.
    Contains the handler to route to and extracted parameters.

    Attributes:
        handler_name: Name of the handler to route to (e.g., "music", "maps",
            "image", "video", "research", "default_chat").
        parameters: Extracted parameters from regex matching, may be empty.
        trigger_reason: Why fallback was triggered ("timeout", "http_4xx",
            "http_5xx", "parse_error", "connection_error").
    """

    handler_name: str
    parameters: dict[str, Any]
    trigger_reason: str


@dataclass
class RoutingMetrics:
    """Rolling metrics over a 5-minute window for observability.

    Mutable dataclass used by the Metrics_Collector to track routing statistics.
    Exposed via the health endpoint for monitoring.

    Attributes:
        total_requests: Total number of routing requests in the window.
        successful_selections: Number of successful LLM tool selections.
        fallback_count: Number of requests that fell back to regex routing.
        total_latency_ms: Sum of selection latencies for calculating average.
    """

    total_requests: int = 0
    successful_selections: int = 0
    fallback_count: int = 0
    total_latency_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        """Tool selection success rate as a percentage (0-100).

        Returns 100.0 if no requests have been made yet.
        """
        if self.total_requests == 0:
            return 100.0
        return (self.successful_selections / self.total_requests) * 100

    @property
    def fallback_rate(self) -> float:
        """Fallback rate as a percentage (0-100).

        Returns 0.0 if no requests have been made yet.
        """
        if self.total_requests == 0:
            return 0.0
        return (self.fallback_count / self.total_requests) * 100

    @property
    def average_latency_ms(self) -> float:
        """Average selection latency in milliseconds.

        Returns 0.0 if no successful selections have been made.
        """
        if self.successful_selections == 0:
            return 0.0
        return self.total_latency_ms / self.successful_selections

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with all metrics including computed properties.
        """
        return {
            "total_requests": self.total_requests,
            "successful_selections": self.successful_selections,
            "fallback_count": self.fallback_count,
            "total_latency_ms": self.total_latency_ms,
            "success_rate": round(self.success_rate, 2),
            "fallback_rate": round(self.fallback_rate, 2),
            "average_latency_ms": round(self.average_latency_ms, 2),
        }
