"""Tool Registry for managing tool definitions.

This module implements the centralized Tool_Registry that maintains OpenAI-compatible
tool definitions for LLM tool calling. It provides validation, registration, and
retrieval of tool definitions.

**Validates: Requirements 1.1, 1.2, 1.3**
"""

from __future__ import annotations

from typing import Any

from friday.modules.tool_calling.models import ToolDefinition, ToolRegistrationError


class ToolRegistry:
    """Centralized registry of tool definitions for LLM tool calling.

    This class implements a singleton pattern via `get_instance()` to ensure
    a single registry is shared across the application. Tool definitions are
    validated on registration and stored in memory for fast retrieval.

    Attributes:
        _instance: Class-level singleton instance.
        _tools: Dictionary mapping tool names to their definitions.
    """

    _instance: ToolRegistry | None = None

    def __init__(self) -> None:
        """Initialize an empty tool registry.

        Note: Use `get_instance()` instead of direct instantiation to ensure
        singleton behavior.
        """
        self._tools: dict[str, ToolDefinition] = {}

    @classmethod
    def get_instance(cls) -> ToolRegistry:
        """Return the singleton instance of the ToolRegistry.

        Creates a new instance on first call, returns the existing instance
        on subsequent calls. The registry is loaded once at application startup
        and cached in memory per Requirement 9.4.

        Returns:
            The singleton ToolRegistry instance.
        """
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._load_default_tools()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (primarily for testing).

        This method clears the singleton instance, allowing a fresh registry
        to be created on the next `get_instance()` call.
        """
        cls._instance = None

    def register(self, tool: ToolDefinition) -> ToolRegistrationError | None:
        """Register a tool definition with validation.

        Validates the tool definition according to the OpenAI function calling
        schema requirements:
        - Name must be 1-64 characters
        - Description must be 1-1024 characters
        - Parameters must be a dict with "type": "object"

        Args:
            tool: The ToolDefinition to register.

        Returns:
            None if registration succeeds, or a ToolRegistrationError indicating
            which validation check failed.

        **Validates: Requirements 1.2, 1.3**
        """
        # Validate name (1-64 characters)
        if not tool.name or len(tool.name) < 1 or len(tool.name) > 64:
            return ToolRegistrationError(
                field="name",
                message="Name must be 1-64 characters",
            )

        # Validate description (1-1024 characters)
        if not tool.description or len(tool.description) < 1 or len(tool.description) > 1024:
            return ToolRegistrationError(
                field="description",
                message="Description must be 1-1024 characters",
            )

        # Validate parameters (must be dict with "type": "object")
        if not isinstance(tool.parameters, dict):
            return ToolRegistrationError(
                field="parameters",
                message="Parameters must be a JSON Schema object",
            )

        if tool.parameters.get("type") != "object":
            return ToolRegistrationError(
                field="parameters",
                message='Parameters schema must have type: "object"',
            )

        # Registration successful - store the tool
        self._tools[tool.name] = tool
        return None

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name.

        Args:
            name: The name of the tool to retrieve.

        Returns:
            The ToolDefinition if found, None otherwise.
        """
        return self._tools.get(name)

    def get_all_tools(self) -> list[ToolDefinition]:
        """Get all registered tool definitions.

        Returns:
            A list of all registered ToolDefinition objects.
        """
        return list(self._tools.values())

    def get_openai_format(self) -> list[dict[str, Any]]:
        """Return tools in OpenAI function calling format.

        Converts all registered tools to the format expected by OpenAI-compatible
        APIs for the `tools` parameter in chat completion requests.

        Returns:
            List of tool definitions in OpenAI format:
            [
                {
                    "type": "function",
                    "function": {
                        "name": ...,
                        "description": ...,
                        "parameters": ...
                    }
                },
                ...
            ]

        **Validates: Requirement 2.1**
        """
        return [tool.to_openai_format() for tool in self._tools.values()]

    def clear(self) -> None:
        """Remove all registered tools (primarily for testing)."""
        self._tools.clear()

    def __len__(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """Check if a tool with the given name is registered."""
        return name in self._tools

    def _load_default_tools(self) -> None:
        """Load default tool definitions for all existing capabilities.

        Registers all 11 default tools with their schemas and distinguishing keywords
        as specified in Requirement 1.4 and 1.5. Each tool definition includes:
        - A unique name (1-64 characters)
        - A description with distinguishing keywords
        - JSON Schema parameters with type: "object"
        - A handler_name mapping to the capability handler

        **Validates: Requirements 1.4, 1.5**
        """
        default_tools = [
            ToolDefinition(
                name="music_play",
                description="Play music, songs, or audio tracks. Use when user wants to listen to, play, or queue music.",
                parameters={
                    "type": "object",
                    "properties": {
                        "song_query": {
                            "type": "string",
                            "description": "The song, artist, or music query to search for",
                            "minLength": 1,
                            "maxLength": 500,
                        }
                    },
                    "required": ["song_query"],
                },
                handler_name="music",
            ),
            ToolDefinition(
                name="music_control",
                description="Control music playback - pause, resume, stop, skip to next track, or go to previous track.",
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["pause", "resume", "stop", "next", "previous"],
                            "description": "The playback control action to perform",
                        }
                    },
                    "required": ["action"],
                },
                handler_name="music_control",
            ),
            ToolDefinition(
                name="map_view",
                description="Display a map of a location or place. Use for 'show map of X', 'where is X', or location viewing.",
                parameters={
                    "type": "object",
                    "properties": {
                        "place": {
                            "type": "string",
                            "description": "The location, city, or place to show on the map",
                            "minLength": 1,
                            "maxLength": 200,
                        }
                    },
                    "required": ["place"],
                },
                handler_name="maps",
            ),
            ToolDefinition(
                name="directions",
                description="Get directions or navigation route between locations. Use for 'directions to X', 'how to get to X', or 'from A to B'.",
                parameters={
                    "type": "object",
                    "properties": {
                        "destination": {
                            "type": "string",
                            "description": "The destination location",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                        "origin": {
                            "type": "string",
                            "description": "The starting location (optional, current location if not specified)",
                            "maxLength": 200,
                            "default": "",
                        },
                    },
                    "required": ["destination"],
                },
                handler_name="maps",
            ),
            ToolDefinition(
                name="image_generate",
                description="Generate an image from a text description. Use for creating pictures, artwork, illustrations, or visual content.",
                parameters={
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "Description of the image to generate",
                            "minLength": 1,
                            "maxLength": 1000,
                        }
                    },
                    "required": ["prompt"],
                },
                handler_name="image",
            ),
            ToolDefinition(
                name="video_generate",
                description="Generate a video or animation from a text description. Use for creating video clips, animations, or motion content.",
                parameters={
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "Description of the video to generate",
                            "minLength": 1,
                            "maxLength": 1000,
                        }
                    },
                    "required": ["prompt"],
                },
                handler_name="video",
            ),
            ToolDefinition(
                name="research",
                description="Conduct deep research on a topic with multiple sources. Use for comprehensive analysis, detailed reports, or thorough investigation.",
                parameters={
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "The topic to research",
                            "minLength": 1,
                            "maxLength": 500,
                        }
                    },
                    "required": ["topic"],
                },
                handler_name="research",
            ),
            ToolDefinition(
                name="web_search",
                description="Search the web for current information, news, facts, or general queries.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query",
                            "minLength": 1,
                            "maxLength": 500,
                        }
                    },
                    "required": ["query"],
                },
                handler_name="search",
            ),
            ToolDefinition(
                name="news",
                description="Get latest news and headlines on a topic or category.",
                parameters={
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "News topic or category (world, tech, business, or specific subject)",
                            "maxLength": 200,
                        }
                    },
                    "required": [],
                },
                handler_name="news",
            ),
            ToolDefinition(
                name="weather",
                description="Get current weather or forecast for a location.",
                parameters={
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The location to get weather for",
                            "minLength": 1,
                            "maxLength": 200,
                        }
                    },
                    "required": ["location"],
                },
                handler_name="weather",
            ),
            ToolDefinition(
                name="stock",
                description="Get stock price, market data, or cryptocurrency information.",
                parameters={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Stock ticker symbol or cryptocurrency name",
                            "minLength": 1,
                            "maxLength": 50,
                        }
                    },
                    "required": ["symbol"],
                },
                handler_name="stock",
            ),
        ]

        for tool in default_tools:
            self.register(tool)
