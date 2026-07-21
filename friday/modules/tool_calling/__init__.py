"""Tool calling module for LLM-native intent routing.

This module provides the components for routing user messages to capability
handlers via Cerebras tool/function calling instead of regex-based pattern
matching. It includes data models, registry, routing components, and formatters.

Exports:
    Data Models:
        ToolDefinition - Schema for a callable tool
        ToolRegistrationError - Validation error for tool registration
        ToolCall - Parsed tool call from LLM response
        ToolSelectionResult - Result of tool selection request
        RoutingResult - Result of intent routing
        FallbackResult - Result of fallback routing
        RoutingMetrics - Metrics for observability

    Components:
        ToolRegistry - Centralized tool definition registry
        FallbackRouter - Regex-based fallback routing
        IntentRouter - LLM-based intent routing
        MetricsCollector - Routing metrics collection with rolling 5-minute window

    Formatters:
        format_music_response - Format music playback response
        format_music_control_response - Format music control response
        format_map_view_response - Format map view response
        format_directions_response - Format directions response
        format_image_response - Format image generation response
        format_video_response - Format video generation response
        format_research_response - Format research report response
        format_multi_result_response - Format multi-tool execution response
        format_error_response - Format error response
        format_conversational_response - Format general chat response
"""

from friday.modules.tool_calling.models import (
    ToolDefinition,
    ToolRegistrationError,
    ToolCall,
    ToolSelectionResult,
    RoutingResult,
    FallbackResult,
    RoutingMetrics,
)
from friday.modules.tool_calling.registry import ToolRegistry
from friday.modules.tool_calling.fallback import FallbackRouter
from friday.modules.tool_calling.router import IntentRouter
from friday.modules.tool_calling.metrics import MetricsCollector
from friday.modules.tool_calling.formatters import (
    format_music_response,
    format_music_control_response,
    format_map_view_response,
    format_directions_response,
    format_image_response,
    format_video_response,
    format_research_response,
    format_multi_result_response,
    format_error_response,
    format_conversational_response,
)

__all__ = [
    # Data Models
    "ToolDefinition",
    "ToolRegistrationError",
    "ToolCall",
    "ToolSelectionResult",
    "RoutingResult",
    "FallbackResult",
    "RoutingMetrics",
    # Components
    "ToolRegistry",
    "FallbackRouter",
    "IntentRouter",
    "MetricsCollector",
    # Formatters
    "format_music_response",
    "format_music_control_response",
    "format_map_view_response",
    "format_directions_response",
    "format_image_response",
    "format_video_response",
    "format_research_response",
    "format_multi_result_response",
    "format_error_response",
    "format_conversational_response",
]
