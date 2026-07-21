"""Tests for the IntentRouter parameter validation.

This module tests the _validate_parameters() method of the IntentRouter class,
ensuring that parameters are validated against JSON Schema constraints.

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7**
"""

import pytest
from unittest.mock import MagicMock, Mock

from friday.modules.tool_calling.models import ToolDefinition
from friday.modules.tool_calling.registry import ToolRegistry
from friday.modules.tool_calling.router import IntentRouter
from friday.modules.tool_calling.fallback import FallbackRouter


class TestParameterValidation:
    """Tests for parameter validation in IntentRouter."""

    def setup_method(self):
        """Reset and set up router with mock dependencies."""
        ToolRegistry.reset_instance()
        self.registry = ToolRegistry.get_instance()
        self.mock_client = MagicMock()
        self.fallback = FallbackRouter()
        self.router = IntentRouter(
            tool_registry=self.registry,
            cerebras_client=self.mock_client,
            fallback_router=self.fallback,
        )

    def teardown_method(self):
        """Clean up after each test."""
        ToolRegistry.reset_instance()

    # ==========================================================================
    # Tests for Required Parameters (Requirements 7.1-7.6)
    # ==========================================================================

    def test_validate_missing_required_parameter_fails(self):
        """Missing required parameter should return error."""
        # music_play requires song_query
        result = self.router._validate_parameters("music_play", {})
        
        assert result is not None
        assert "Missing required parameter" in result
        assert "song_query" in result

    def test_validate_empty_required_string_parameter_fails(self):
        """Empty string for required parameter should return error."""
        # music_play requires non-empty song_query
        result = self.router._validate_parameters("music_play", {"song_query": ""})
        
        assert result is not None
        assert "cannot be empty" in result
        assert "song_query" in result

    def test_validate_whitespace_only_required_string_fails(self):
        """Whitespace-only string for required parameter should return error."""
        result = self.router._validate_parameters("music_play", {"song_query": "   "})
        
        assert result is not None
        assert "cannot be empty" in result

    def test_validate_valid_required_parameter_succeeds(self):
        """Valid required parameter should pass validation."""
        result = self.router._validate_parameters("music_play", {"song_query": "Beatles"})
        
        assert result is None

    # ==========================================================================
    # Tests for minLength Constraint (Requirement 7.1, 7.2)
    # ==========================================================================

    def test_validate_string_below_min_length_fails(self):
        """String below minLength should return error."""
        # song_query has minLength: 1
        # Since empty string is also caught by required check, we test with
        # a tool that has minLength > 1 if available, otherwise just verify
        # the mechanism works
        
        # Register a custom tool with minLength: 5 for testing
        self.registry.clear()
        custom_tool = ToolDefinition(
            name="custom_tool",
            description="A custom tool for testing minLength",
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "minLength": 5,
                        "maxLength": 100,
                    }
                },
                "required": ["text"],
            },
            handler_name="custom",
        )
        self.registry.register(custom_tool)
        
        # Test with string shorter than minLength
        result = self.router._validate_parameters("custom_tool", {"text": "abc"})
        
        assert result is not None
        assert "at least 5 character(s)" in result
        assert "got 3" in result

    def test_validate_string_at_min_length_succeeds(self):
        """String exactly at minLength should pass."""
        # song_query has minLength: 1
        result = self.router._validate_parameters("music_play", {"song_query": "a"})
        
        assert result is None

    # ==========================================================================
    # Tests for maxLength Constraint (Requirement 7.1, 7.2)
    # ==========================================================================

    def test_validate_string_exceeds_max_length_fails(self):
        """String exceeding maxLength should return error."""
        # song_query has maxLength: 500
        long_query = "x" * 501
        result = self.router._validate_parameters("music_play", {"song_query": long_query})
        
        assert result is not None
        assert "at most 500 character(s)" in result
        assert "got 501" in result

    def test_validate_string_at_max_length_succeeds(self):
        """String exactly at maxLength should pass."""
        # song_query has maxLength: 500
        exact_length_query = "x" * 500
        result = self.router._validate_parameters("music_play", {"song_query": exact_length_query})
        
        assert result is None

    def test_validate_string_below_max_length_succeeds(self):
        """String below maxLength should pass."""
        result = self.router._validate_parameters("music_play", {"song_query": "Hello"})
        
        assert result is None

    # ==========================================================================
    # Tests for Enum Constraint (music_control)
    # ==========================================================================

    def test_validate_enum_value_valid_pause_succeeds(self):
        """Valid enum value 'pause' should pass."""
        result = self.router._validate_parameters("music_control", {"action": "pause"})
        
        assert result is None

    def test_validate_enum_value_valid_resume_succeeds(self):
        """Valid enum value 'resume' should pass."""
        result = self.router._validate_parameters("music_control", {"action": "resume"})
        
        assert result is None

    def test_validate_enum_value_valid_stop_succeeds(self):
        """Valid enum value 'stop' should pass."""
        result = self.router._validate_parameters("music_control", {"action": "stop"})
        
        assert result is None

    def test_validate_enum_value_valid_next_succeeds(self):
        """Valid enum value 'next' should pass."""
        result = self.router._validate_parameters("music_control", {"action": "next"})
        
        assert result is None

    def test_validate_enum_value_valid_previous_succeeds(self):
        """Valid enum value 'previous' should pass."""
        result = self.router._validate_parameters("music_control", {"action": "previous"})
        
        assert result is None

    def test_validate_enum_value_invalid_fails(self):
        """Invalid enum value should return error."""
        result = self.router._validate_parameters("music_control", {"action": "fast_forward"})
        
        assert result is not None
        assert "must be one of" in result
        assert "pause" in result
        assert "fast_forward" in result

    def test_validate_enum_case_sensitive(self):
        """Enum validation should be case-sensitive."""
        # 'PAUSE' is not the same as 'pause'
        result = self.router._validate_parameters("music_control", {"action": "PAUSE"})
        
        assert result is not None
        assert "must be one of" in result

    # ==========================================================================
    # Tests for Different Tools
    # ==========================================================================

    def test_validate_map_view_place_parameter(self):
        """map_view place parameter validation."""
        # Valid case
        result = self.router._validate_parameters("map_view", {"place": "New York"})
        assert result is None
        
        # Exceeds maxLength (200)
        long_place = "x" * 201
        result = self.router._validate_parameters("map_view", {"place": long_place})
        assert result is not None
        assert "at most 200 character(s)" in result

    def test_validate_directions_parameters(self):
        """directions tool parameter validation."""
        # Valid with both origin and destination
        result = self.router._validate_parameters("directions", {
            "destination": "Los Angeles",
            "origin": "San Francisco",
        })
        assert result is None
        
        # Valid with only destination (origin is optional)
        result = self.router._validate_parameters("directions", {
            "destination": "Chicago",
        })
        assert result is None
        
        # Missing required destination
        result = self.router._validate_parameters("directions", {"origin": "Boston"})
        assert result is not None
        assert "Missing required parameter" in result

    def test_validate_image_generate_prompt(self):
        """image_generate prompt parameter validation."""
        # Valid prompt
        result = self.router._validate_parameters("image_generate", {"prompt": "A sunset"})
        assert result is None
        
        # Exceeds maxLength (1000)
        long_prompt = "x" * 1001
        result = self.router._validate_parameters("image_generate", {"prompt": long_prompt})
        assert result is not None
        assert "at most 1000 character(s)" in result

    def test_validate_video_generate_prompt(self):
        """video_generate prompt parameter validation."""
        # Valid prompt
        result = self.router._validate_parameters("video_generate", {"prompt": "A flying bird"})
        assert result is None
        
        # Exceeds maxLength (1000)
        long_prompt = "x" * 1001
        result = self.router._validate_parameters("video_generate", {"prompt": long_prompt})
        assert result is not None
        assert "at most 1000 character(s)" in result

    def test_validate_research_topic(self):
        """research topic parameter validation."""
        # Valid topic
        result = self.router._validate_parameters("research", {"topic": "Climate change"})
        assert result is None
        
        # Exceeds maxLength (500)
        long_topic = "x" * 501
        result = self.router._validate_parameters("research", {"topic": long_topic})
        assert result is not None
        assert "at most 500 character(s)" in result

    def test_validate_web_search_query(self):
        """web_search query parameter validation."""
        # Valid query
        result = self.router._validate_parameters("web_search", {"query": "best restaurants"})
        assert result is None
        
        # Missing required query
        result = self.router._validate_parameters("web_search", {})
        assert result is not None
        assert "Missing required parameter" in result

    def test_validate_weather_location(self):
        """weather location parameter validation."""
        # Valid location
        result = self.router._validate_parameters("weather", {"location": "Seattle"})
        assert result is None
        
        # Exceeds maxLength (200)
        long_location = "x" * 201
        result = self.router._validate_parameters("weather", {"location": long_location})
        assert result is not None
        assert "at most 200 character(s)" in result

    def test_validate_stock_symbol(self):
        """stock symbol parameter validation."""
        # Valid symbol
        result = self.router._validate_parameters("stock", {"symbol": "AAPL"})
        assert result is None
        
        # Exceeds maxLength (50)
        long_symbol = "x" * 51
        result = self.router._validate_parameters("stock", {"symbol": long_symbol})
        assert result is not None
        assert "at most 50 character(s)" in result

    def test_validate_news_topic_optional(self):
        """news topic parameter is optional."""
        # Valid with topic
        result = self.router._validate_parameters("news", {"topic": "technology"})
        assert result is None
        
        # Valid without topic (not required)
        result = self.router._validate_parameters("news", {})
        assert result is None

    # ==========================================================================
    # Tests for Unknown Tool
    # ==========================================================================

    def test_validate_unknown_tool_returns_error(self):
        """Unknown tool should return error message."""
        result = self.router._validate_parameters("nonexistent_tool", {"param": "value"})
        
        assert result is not None
        assert "Unknown tool" in result
        assert "nonexistent_tool" in result

    # ==========================================================================
    # Tests for Extra Parameters (lenient validation)
    # ==========================================================================

    def test_validate_extra_parameters_allowed(self):
        """Extra parameters not in schema should be allowed (lenient validation)."""
        result = self.router._validate_parameters("music_play", {
            "song_query": "Beatles",
            "extra_param": "ignored",
        })
        
        assert result is None


class TestParameterValidationIntegration:
    """Integration tests for parameter validation in tool execution."""

    def setup_method(self):
        """Reset and set up router with mock dependencies."""
        ToolRegistry.reset_instance()
        self.registry = ToolRegistry.get_instance()
        self.mock_client = MagicMock()
        self.fallback = FallbackRouter()
        self.router = IntentRouter(
            tool_registry=self.registry,
            cerebras_client=self.mock_client,
            fallback_router=self.fallback,
        )
        
        # Register a mock handler
        self.mock_handler = MagicMock(return_value={"reply": "success"})
        self.router.register_handler("music_play", self.mock_handler)
        self.router.register_handler("music_control", self.mock_handler)

    def teardown_method(self):
        """Clean up after each test."""
        ToolRegistry.reset_instance()

    def test_execute_tool_with_valid_params_calls_handler(self):
        """Tool execution with valid parameters should call the handler."""
        from friday.modules.tool_calling.models import ToolCall
        
        tool_call = ToolCall(
            id="call_1",
            function_name="music_play",
            arguments={"song_query": "Hello by Adele"},
        )
        
        results = self.router._execute_tool_calls(
            tool_calls=[tool_call],
            session_id="session_1",
            user_id="user_1",
        )
        
        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["error"] is None
        self.mock_handler.assert_called_once()

    def test_execute_tool_with_invalid_params_skips_handler(self):
        """Tool execution with invalid parameters should not call the handler."""
        from friday.modules.tool_calling.models import ToolCall
        
        tool_call = ToolCall(
            id="call_1",
            function_name="music_play",
            arguments={"song_query": ""},  # Empty string - invalid
        )
        
        results = self.router._execute_tool_calls(
            tool_calls=[tool_call],
            session_id="session_1",
            user_id="user_1",
        )
        
        assert len(results) == 1
        assert results[0]["success"] is False
        assert "cannot be empty" in results[0]["error"]
        self.mock_handler.assert_not_called()

    def test_execute_tool_with_invalid_enum_skips_handler(self):
        """Tool execution with invalid enum value should not call the handler."""
        from friday.modules.tool_calling.models import ToolCall
        
        tool_call = ToolCall(
            id="call_1",
            function_name="music_control",
            arguments={"action": "invalid_action"},
        )
        
        results = self.router._execute_tool_calls(
            tool_calls=[tool_call],
            session_id="session_1",
            user_id="user_1",
        )
        
        assert len(results) == 1
        assert results[0]["success"] is False
        assert "must be one of" in results[0]["error"]
        self.mock_handler.assert_not_called()

    def test_execute_multiple_tools_mixed_validity(self):
        """Multiple tool execution should validate each independently."""
        from friday.modules.tool_calling.models import ToolCall
        
        tool_calls = [
            ToolCall(
                id="call_1",
                function_name="music_play",
                arguments={"song_query": ""},  # Invalid
            ),
            ToolCall(
                id="call_2",
                function_name="music_play",
                arguments={"song_query": "Valid song"},  # Valid
            ),
        ]
        
        results = self.router._execute_tool_calls(
            tool_calls=tool_calls,
            session_id="session_1",
            user_id="user_1",
        )
        
        assert len(results) == 2
        
        # First call failed validation
        assert results[0]["success"] is False
        assert results[0]["error"] is not None
        
        # Second call succeeded
        assert results[1]["success"] is True
        assert results[1]["error"] is None
        
        # Handler called only once (for the valid call)
        self.mock_handler.assert_called_once()
