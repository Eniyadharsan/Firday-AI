"""Tests for the ToolRegistry class.

This module tests the Tool_Registry singleton, validation logic, and
retrieval methods.

**Validates: Requirements 1.1, 1.2, 1.3**
"""

import pytest
from friday.modules.tool_calling.models import ToolDefinition, ToolRegistrationError
from friday.modules.tool_calling.registry import ToolRegistry


class TestToolRegistrySingleton:
    """Tests for singleton pattern implementation."""

    def setup_method(self):
        """Reset the singleton before each test."""
        ToolRegistry.reset_instance()

    def teardown_method(self):
        """Clean up after each test."""
        ToolRegistry.reset_instance()

    def test_get_instance_returns_same_instance(self):
        """get_instance() should return the same instance on multiple calls."""
        instance1 = ToolRegistry.get_instance()
        instance2 = ToolRegistry.get_instance()
        assert instance1 is instance2

    def test_reset_instance_creates_new_instance(self):
        """reset_instance() should allow creating a new instance."""
        instance1 = ToolRegistry.get_instance()
        ToolRegistry.reset_instance()
        instance2 = ToolRegistry.get_instance()
        assert instance1 is not instance2


class TestToolRegistration:
    """Tests for tool registration and validation."""

    def setup_method(self):
        """Reset and get a fresh registry instance."""
        ToolRegistry.reset_instance()
        self.registry = ToolRegistry.get_instance()

    def teardown_method(self):
        """Clean up after each test."""
        ToolRegistry.reset_instance()

    def test_register_valid_tool_succeeds(self):
        """Valid tool definition should register successfully."""
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool for unit testing",
            parameters={"type": "object", "properties": {}},
            handler_name="test_handler",
        )
        result = self.registry.register(tool)
        assert result is None  # No error
        assert "test_tool" in self.registry

    def test_register_tool_is_retrievable(self):
        """Registered tool should be retrievable with identical values."""
        tool = ToolDefinition(
            name="music_play",
            description="Play music tracks",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler_name="music",
        )
        self.registry.register(tool)
        retrieved = self.registry.get_tool("music_play")
        
        assert retrieved is not None
        assert retrieved.name == tool.name
        assert retrieved.description == tool.description
        assert retrieved.parameters == tool.parameters
        assert retrieved.handler_name == tool.handler_name

    def test_register_empty_name_fails(self):
        """Empty name should fail validation."""
        tool = ToolDefinition(
            name="",
            description="A valid description",
            parameters={"type": "object"},
            handler_name="handler",
        )
        result = self.registry.register(tool)
        assert result is not None
        assert isinstance(result, ToolRegistrationError)
        assert result.field == "name"

    def test_register_name_too_long_fails(self):
        """Name over 64 characters should fail validation."""
        tool = ToolDefinition(
            name="x" * 65,
            description="A valid description",
            parameters={"type": "object"},
            handler_name="handler",
        )
        result = self.registry.register(tool)
        assert result is not None
        assert result.field == "name"
        assert "1-64" in result.message

    def test_register_name_at_boundary_succeeds(self):
        """Name of exactly 64 characters should succeed."""
        tool = ToolDefinition(
            name="x" * 64,
            description="A valid description",
            parameters={"type": "object"},
            handler_name="handler",
        )
        result = self.registry.register(tool)
        assert result is None

    def test_register_empty_description_fails(self):
        """Empty description should fail validation."""
        tool = ToolDefinition(
            name="valid_name",
            description="",
            parameters={"type": "object"},
            handler_name="handler",
        )
        result = self.registry.register(tool)
        assert result is not None
        assert result.field == "description"

    def test_register_description_too_long_fails(self):
        """Description over 1024 characters should fail validation."""
        tool = ToolDefinition(
            name="valid_name",
            description="x" * 1025,
            parameters={"type": "object"},
            handler_name="handler",
        )
        result = self.registry.register(tool)
        assert result is not None
        assert result.field == "description"
        assert "1-1024" in result.message

    def test_register_description_at_boundary_succeeds(self):
        """Description of exactly 1024 characters should succeed."""
        tool = ToolDefinition(
            name="valid_name",
            description="x" * 1024,
            parameters={"type": "object"},
            handler_name="handler",
        )
        result = self.registry.register(tool)
        assert result is None

    def test_register_parameters_not_dict_fails(self):
        """Parameters that is not a dict should fail validation."""
        # Create a ToolDefinition with invalid parameters type
        # Note: ToolDefinition accepts Any for parameters, so we can pass a list
        tool = ToolDefinition(
            name="valid_name",
            description="A valid description",
            parameters=["not", "a", "dict"],  # type: ignore
            handler_name="handler",
        )
        result = self.registry.register(tool)
        assert result is not None
        assert result.field == "parameters"
        assert "JSON Schema object" in result.message

    def test_register_parameters_missing_type_object_fails(self):
        """Parameters without type: object should fail validation."""
        tool = ToolDefinition(
            name="valid_name",
            description="A valid description",
            parameters={"type": "array"},  # Wrong type
            handler_name="handler",
        )
        result = self.registry.register(tool)
        assert result is not None
        assert result.field == "parameters"
        assert 'type: "object"' in result.message

    def test_register_parameters_empty_dict_no_type_fails(self):
        """Empty parameters dict without type should fail."""
        tool = ToolDefinition(
            name="valid_name",
            description="A valid description",
            parameters={},
            handler_name="handler",
        )
        result = self.registry.register(tool)
        assert result is not None
        assert result.field == "parameters"


class TestToolRetrieval:
    """Tests for tool retrieval methods."""

    def setup_method(self):
        """Set up registry with some test tools."""
        ToolRegistry.reset_instance()
        self.registry = ToolRegistry.get_instance()
        
        # Clear the default tools to start fresh for these tests
        self.registry.clear()
        
        # Register some test tools
        self.tool1 = ToolDefinition(
            name="music_play",
            description="Play music and songs",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler_name="music",
        )
        self.tool2 = ToolDefinition(
            name="map_view",
            description="Show map of a location",
            parameters={"type": "object", "properties": {"place": {"type": "string"}}},
            handler_name="maps",
        )
        self.registry.register(self.tool1)
        self.registry.register(self.tool2)

    def teardown_method(self):
        """Clean up after each test."""
        ToolRegistry.reset_instance()

    def test_get_tool_existing(self):
        """get_tool should return the tool for existing name."""
        tool = self.registry.get_tool("music_play")
        assert tool is not None
        assert tool.name == "music_play"

    def test_get_tool_nonexistent(self):
        """get_tool should return None for nonexistent name."""
        tool = self.registry.get_tool("nonexistent")
        assert tool is None

    def test_get_all_tools(self):
        """get_all_tools should return all registered tools."""
        tools = self.registry.get_all_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"music_play", "map_view"}

    def test_get_all_tools_empty_registry(self):
        """get_all_tools should return empty list for empty registry."""
        self.registry.clear()
        tools = self.registry.get_all_tools()
        assert tools == []

    def test_len_returns_tool_count(self):
        """len() should return the number of registered tools."""
        assert len(self.registry) == 2

    def test_contains_existing_tool(self):
        """in operator should return True for existing tool."""
        assert "music_play" in self.registry
        assert "map_view" in self.registry

    def test_contains_nonexistent_tool(self):
        """in operator should return False for nonexistent tool."""
        assert "nonexistent" not in self.registry


class TestOpenAIFormat:
    """Tests for OpenAI format conversion."""

    def setup_method(self):
        """Set up registry with test tools."""
        ToolRegistry.reset_instance()
        self.registry = ToolRegistry.get_instance()
        
        # Clear the default tools to start fresh for these tests
        self.registry.clear()
        
        self.tool = ToolDefinition(
            name="image_generate",
            description="Generate an image from a prompt",
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Image description"}
                },
                "required": ["prompt"],
            },
            handler_name="image",
        )
        self.registry.register(self.tool)

    def teardown_method(self):
        """Clean up after each test."""
        ToolRegistry.reset_instance()

    def test_get_openai_format_structure(self):
        """OpenAI format should have correct structure."""
        openai_tools = self.registry.get_openai_format()
        
        assert len(openai_tools) == 1
        tool = openai_tools[0]
        
        assert tool["type"] == "function"
        assert "function" in tool
        assert tool["function"]["name"] == "image_generate"
        assert tool["function"]["description"] == "Generate an image from a prompt"
        assert tool["function"]["parameters"]["type"] == "object"

    def test_get_openai_format_empty_registry(self):
        """OpenAI format should return empty list for empty registry."""
        self.registry.clear()
        openai_tools = self.registry.get_openai_format()
        assert openai_tools == []

    def test_get_openai_format_multiple_tools(self):
        """OpenAI format should include all registered tools."""
        # Add another tool
        tool2 = ToolDefinition(
            name="web_search",
            description="Search the web",
            parameters={"type": "object", "properties": {}},
            handler_name="search",
        )
        self.registry.register(tool2)
        
        openai_tools = self.registry.get_openai_format()
        assert len(openai_tools) == 2
        
        names = {t["function"]["name"] for t in openai_tools}
        assert names == {"image_generate", "web_search"}


class TestClearAndReset:
    """Tests for clearing the registry."""

    def setup_method(self):
        """Set up registry with test tools."""
        ToolRegistry.reset_instance()
        self.registry = ToolRegistry.get_instance()
        
        # Clear the default tools to start fresh for these tests
        self.registry.clear()
        
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object"},
            handler_name="test",
        )
        self.registry.register(tool)

    def teardown_method(self):
        """Clean up after each test."""
        ToolRegistry.reset_instance()

    def test_clear_removes_all_tools(self):
        """clear() should remove all registered tools."""
        assert len(self.registry) == 1
        self.registry.clear()
        assert len(self.registry) == 0
        assert self.registry.get_tool("test_tool") is None


class TestDefaultToolsLoading:
    """Tests for default tools loading at startup.
    
    **Validates: Requirements 1.4, 1.5**
    """

    def setup_method(self):
        """Reset and get a fresh registry instance with default tools."""
        ToolRegistry.reset_instance()
        self.registry = ToolRegistry.get_instance()

    def teardown_method(self):
        """Clean up after each test."""
        ToolRegistry.reset_instance()

    def test_all_eleven_default_tools_loaded(self):
        """All 11 default tools should be loaded at startup per Requirement 1.5."""
        expected_tools = [
            "music_play",
            "music_control", 
            "map_view",
            "directions",
            "image_generate",
            "video_generate",
            "research",
            "web_search",
            "news",
            "weather",
            "stock",
        ]
        
        assert len(self.registry) == 11
        
        for tool_name in expected_tools:
            assert tool_name in self.registry, f"Missing default tool: {tool_name}"

    def test_music_play_has_distinguishing_keywords(self):
        """music_play description should contain 'play' or 'listen' per Requirement 1.4."""
        tool = self.registry.get_tool("music_play")
        description_lower = tool.description.lower()
        assert "play" in description_lower or "listen" in description_lower

    def test_music_control_has_distinguishing_keywords(self):
        """music_control description should contain 'pause', 'skip', or 'volume' per Requirement 1.4."""
        tool = self.registry.get_tool("music_control")
        description_lower = tool.description.lower()
        assert "pause" in description_lower or "skip" in description_lower or "volume" in description_lower

    def test_default_tools_have_valid_handler_names(self):
        """All default tools should have valid handler_name mappings."""
        expected_handlers = {
            "music_play": "music",
            "music_control": "music_control",
            "map_view": "maps",
            "directions": "maps",
            "image_generate": "image",
            "video_generate": "video",
            "research": "research",
            "web_search": "search",
            "news": "news",
            "weather": "weather",
            "stock": "stock",
        }
        
        for tool_name, expected_handler in expected_handlers.items():
            tool = self.registry.get_tool(tool_name)
            assert tool is not None, f"Tool {tool_name} not found"
            assert tool.handler_name == expected_handler, f"{tool_name} handler_name mismatch"

    def test_default_tools_have_valid_parameters_schema(self):
        """All default tools should have valid JSON Schema parameters with type: object."""
        tools = self.registry.get_all_tools()
        
        for tool in tools:
            assert isinstance(tool.parameters, dict), f"{tool.name} parameters is not a dict"
            assert tool.parameters.get("type") == "object", f"{tool.name} parameters missing type: object"

    def test_default_tools_conform_to_openai_format(self):
        """Default tools should be convertible to OpenAI format."""
        openai_format = self.registry.get_openai_format()
        
        assert len(openai_format) == 11
        
        for tool_def in openai_format:
            assert tool_def["type"] == "function"
            assert "function" in tool_def
            func = tool_def["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert 1 <= len(func["name"]) <= 64
            assert 1 <= len(func["description"]) <= 1024
