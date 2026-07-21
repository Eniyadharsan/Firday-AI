# Implementation Plan: Tool Calling Routing

## Overview

This implementation plan refactors FRIDAY's intent routing system from regex-based pattern matching to LLM-native tool/function calling via the Cerebras API. The implementation follows a bottom-up approach: first building the foundational components (Tool_Registry, enhanced Cerebras_Client), then the routing logic (Intent_Router, Fallback_Router), and finally integrating with the existing `/chat` endpoint while preserving backward compatibility.

## Tasks

- [x] 1. Set up project structure and core data models
  - [x] 1.1 Create the tool calling module structure and data models
    - Create `friday/modules/tool_calling/` directory
    - Create `friday/modules/tool_calling/__init__.py` with exports
    - Create `friday/modules/tool_calling/models.py` with dataclasses:
      - `ToolDefinition` (name, description, parameters, handler_name)
      - `ToolRegistrationError` (field, message)
      - `ToolCall` (id, function_name, arguments)
      - `ToolSelectionResult` (tool_calls, assistant_content, error)
      - `RoutingResult` (response, handler_used, is_fallback, latency_ms)
      - `FallbackResult` (handler_name, parameters, trigger_reason)
      - `RoutingMetrics` (total_requests, successful_selections, fallback_count, total_latency_ms)
    - _Requirements: 1.1, 1.2, 2.2, 3.2, 5.1_

  - [ ]* 1.2 Write unit tests for data models
    - Test dataclass instantiation and field access
    - Test computed properties on `RoutingMetrics` (success_rate, fallback_rate, average_latency_ms)
    - Test edge cases (zero divisions, empty values)
    - _Requirements: 1.1, 10.4_

- [x] 2. Implement Tool_Registry component
  - [x] 2.1 Create the Tool_Registry singleton with validation
    - Create `friday/modules/tool_calling/registry.py`
    - Implement `ToolRegistry` class with singleton pattern via `get_instance()`
    - Implement `register()` method with validation:
      - Name must be 1-64 characters
      - Description must be 1-1024 characters
      - Parameters must be dict with `type: "object"`
    - Implement `get_tool()`, `get_all_tools()`, `get_openai_format()` methods
    - _Requirements: 1.1, 1.2, 1.3_

  - [ ]* 2.2 Write property test for tool definition validation round-trip
    - **Property 1: Tool Definition Validation Round-Trip**
    - **Validates: Requirements 1.1, 1.2**
    - Use Hypothesis to generate valid names (1-64 chars), descriptions (1-1024 chars), valid JSON Schema parameters
    - Assert registration succeeds and retrieval returns identical values

  - [ ]* 2.3 Write property test for tool definition rejection
    - **Property 2: Tool Definition Rejection with Specific Errors**
    - **Validates: Requirements 1.2, 1.3**
    - Use Hypothesis to generate invalid tool definitions (empty name, >64 char name, empty description, >1024 char description, missing type:object)
    - Assert registration fails with correct error field

  - [x] 2.4 Load default tool definitions for all existing capabilities
    - Implement `_load_default_tools()` method in `ToolRegistry`
    - Add tool definitions for: music_play, music_control, map_view, directions, image_generate, video_generate, research, web_search, news, weather, stock
    - Each definition must include distinguishing keywords per Requirement 1.4
    - _Requirements: 1.4, 1.5_

  - [ ]* 2.5 Write unit tests for Tool_Registry
    - Test singleton behavior (same instance returned)
    - Test default tools loaded at startup
    - Test `get_openai_format()` returns correct structure
    - _Requirements: 1.1, 1.5_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Enhance Cerebras_Client with tool calling support
  - [x] 4.1 Extend the Cerebras_Client with select_tools method
    - Modify `friday/modules/llm.py` to add `select_tools()` method to the module
    - Implement tool selection request with:
      - `tools` parameter containing tool definitions in OpenAI format
      - `tool_choice` parameter ("auto", "none", or specific tool name)
      - 3-second timeout for tool selection
    - Parse response into `ToolSelectionResult`:
      - Extract `tool_calls` array if present
      - Extract `assistant_content` if no tools selected
      - Capture errors for connection failures, HTTP errors, parse failures
    - Reuse existing `requests.Session` for connection pooling
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 9.3_

  - [ ]* 4.2 Write property test for tool call parsing preserves structure
    - **Property 3: Tool Call Parsing Preserves Structure**
    - **Validates: Requirements 2.2**
    - Use Hypothesis to generate valid API response structures with tool_calls
    - Assert parsed ToolCall objects match original id, function.name, function.arguments

  - [ ]* 4.3 Write property test for tool choice parameter inclusion
    - **Property 6: Tool Choice Parameter Inclusion**
    - **Validates: Requirements 2.5**
    - Use Hypothesis to generate "auto", "none", and specific tool names
    - Assert tool_choice parameter included in request payload with exact value

  - [ ]* 4.4 Write unit tests for Cerebras_Client tool calling
    - Test request formatting with tools parameter
    - Test timeout handling (3-second limit)
    - Test HTTP error handling (4xx, 5xx)
    - Test parse error handling (invalid JSON, malformed tool_calls)
    - _Requirements: 2.1, 2.4, 2.6_

- [x] 5. Implement Fallback_Router component
  - [x] 5.1 Create the Fallback_Router with regex-based routing
    - Create `friday/modules/tool_calling/fallback.py`
    - Implement `FallbackRouter` class with `route()` method
    - Implement priority-ordered regex matching:
      1. `detect_playback_control()` → music_control
      2. `is_research_request()` → research
      3. `is_video_request()` → video
      4. `is_directions_request()` → directions
      5. `is_map_request()` → map_view
      6. `is_music_request()` → music_play
      7. `is_image_request()` → image_generate
      8. default → default_chat
    - Return `FallbackResult` with handler_name, parameters, trigger_reason
    - _Requirements: 5.1, 5.2, 5.4, 5.5, 4.7_

  - [ ]* 5.2 Write property test for fallback default routing
    - **Property 12: Fallback Default Routing**
    - **Validates: Requirements 5.5**
    - Use Hypothesis to generate messages that don't match any regex pattern
    - Assert fallback routes to default_chat handler without error

  - [ ]* 5.3 Write unit tests for Fallback_Router
    - Test each regex pattern matches correctly
    - Test priority ordering (playback control before music)
    - Test parameter extraction for each handler type
    - _Requirements: 5.1, 5.4, 4.7_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement Intent_Router component
  - [x] 7.1 Create the Intent_Router with tool selection and handler execution
    - Create `friday/modules/tool_calling/router.py`
    - Implement `IntentRouter` class with:
      - Constructor accepting `ToolRegistry`, `CerebrasClient`, `FallbackRouter`
      - `register_handler()` method for capability handler registration
      - `route()` method orchestrating tool selection → handler execution → response formatting
    - Implement `_execute_tool_calls()` for sequential execution (max 5 tools)
    - Implement fallback delegation on timeout/error
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [ ]* 7.2 Write property test for no tool call returns assistant content
    - **Property 4: No Tool Call Returns Assistant Content**
    - **Validates: Requirements 2.3, 3.5**
    - Use Hypothesis to generate responses without tool_calls but with assistant content
    - Assert assistant content returned without invoking any handler

  - [ ]* 7.3 Write property test for error conditions trigger fallback
    - **Property 5: Error Conditions Trigger Fallback**
    - **Validates: Requirements 2.4, 2.6, 5.1, 5.2**
    - Use Hypothesis to generate timeout, HTTP 4xx/5xx, parse failures
    - Assert each error type triggers fallback routing

  - [ ]* 7.4 Write property test for tool call routes to matching handler
    - **Property 7: Tool Call Routes to Matching Handler**
    - **Validates: Requirements 3.2, 3.3**
    - Use Hypothesis to generate tool calls for all registered tools
    - Assert correct handler invoked with unchanged arguments

  - [ ]* 7.5 Write property test for unknown tool returns error
    - **Property 8: Unknown Tool Returns Error**
    - **Validates: Requirements 3.7**
    - Use Hypothesis to generate tool calls with unregistered names
    - Assert error response returned without invoking any handler

  - [ ]* 7.6 Write property test for multi-tool sequential execution with limit
    - **Property 9: Multi-Tool Sequential Execution with Limit**
    - **Validates: Requirements 3.4, 6.1, 6.2**
    - Use Hypothesis to generate 1-10 tool calls
    - Assert max 5 executed in order, remaining ignored

  - [ ]* 7.7 Write property test for multi-tool response aggregation
    - **Property 10: Multi-Tool Response Aggregation**
    - **Validates: Requirements 6.3, 6.4**
    - Use Hypothesis to generate multi-tool executions with success/failure mix
    - Assert combined response contains all results with correct status

- [x] 8. Implement parameter extraction and validation
  - [x] 8.1 Add parameter constraint validation to Intent_Router
    - Validate extracted parameters against JSON Schema constraints:
      - String length bounds (minLength, maxLength)
      - Required parameters present and non-empty
      - Enum values match declared options
    - Return error response for missing/invalid required parameters
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [ ]* 8.2 Write property test for parameter extraction constraints
    - **Property 13: Parameter Extraction Constraints**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7**
    - Use Hypothesis to generate tool calls with various parameter values
    - Assert constraints satisfied (string lengths, required present, enum values valid)

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Implement response formatters for backward compatibility
  - [x] 10.1 Create response formatters for each capability type
    - Create `friday/modules/tool_calling/formatters.py`
    - Implement formatters preserving existing response structures:
      - `format_music_response()` → reply, sessionId, action="play_music_embed", track
      - `format_music_control_response()` → reply, sessionId, action="control_music", control
      - `format_map_view_response()` → reply, sessionId, action="show_map", mode="view", place
      - `format_directions_response()` → reply, sessionId, action="show_map", mode="directions", origin, destination
      - `format_image_response()` → reply, sessionId, action="show_image", imageUrl, imagePrompt
      - `format_video_response()` → reply, sessionId, action="show_video", videoUrl, videoPrompt
      - `format_research_response()` → reply, sessionId, action="show_report", report, topic, meta
      - `format_multi_result_response()` → reply, sessionId, action="multi_result", results
      - `format_error_response()` → reply, sessionId, action="error", error
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ]* 10.2 Write property test for music response format invariants
    - **Property 14: Music Response Format Invariants**
    - **Validates: Requirements 8.1**
    - Use Hypothesis to generate successful music_play executions
    - Assert response contains reply, sessionId, action="play_music_embed", track with all required fields

  - [ ]* 10.3 Write property test for map response format invariants
    - **Property 15: Map Response Format Invariants**
    - **Validates: Requirements 8.2, 8.3**
    - Use Hypothesis to generate successful map_view and directions executions
    - Assert map_view has mode="view", place; directions has mode="directions", origin, destination

  - [ ]* 10.4 Write property test for media generation response format invariants
    - **Property 16: Media Generation Response Format Invariants**
    - **Validates: Requirements 8.4, 8.5**
    - Use Hypothesis to generate successful image_generate and video_generate executions
    - Assert image has imageUrl, imagePrompt; video has videoUrl, videoPrompt

  - [ ]* 10.5 Write property test for research response format invariants
    - **Property 17: Research Response Format Invariants**
    - **Validates: Requirements 8.6**
    - Use Hypothesis to generate successful research executions
    - Assert response contains report, topic, meta with sources/news/time fields

  - [ ]* 10.6 Write unit tests for response formatters
    - Test each formatter produces correct structure
    - Test edge cases (empty strings, special characters, long values)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [x] 11. Implement backward compatibility routing
  - [x] 11.1 Create backward compatibility test suite using existing regex patterns
    - Create `tests/property/test_backward_compatibility.py`
    - Collect test messages that match existing regex patterns
    - Verify LLM tool selection produces same routing decisions
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [ ]* 11.2 Write property test for backward compatibility routing equivalence
    - **Property 11: Backward Compatibility Routing Equivalence**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8**
    - Use Hypothesis to generate messages matching existing regex patterns
    - Assert LLM tool selection routes to same handler as regex routing

- [x] 12. Implement MetricsCollector for observability
  - [x] 12.1 Create the MetricsCollector with rolling window
    - Create `friday/modules/tool_calling/metrics.py`
    - Implement `MetricsCollector` class with:
      - `record_selection()` method for recording tool selection events
      - `get_metrics()` method returning `RoutingMetrics`
      - Rolling 5-minute window for metric calculation
    - _Requirements: 10.4_

  - [x] 12.2 Add logging to Intent_Router for observability
    - Log tool selection completion with tool name, arguments, latency_ms
    - Log fallback events with trigger_reason, timestamp, fallback_decision
    - Log tool execution failures with tool_name, error_type, error_message (truncated to 1000 chars)
    - _Requirements: 10.1, 10.2, 10.3_

  - [ ]* 12.3 Write unit tests for MetricsCollector
    - Test metric recording and retrieval
    - Test rolling window behavior (entries expire after 5 minutes)
    - Test computed metrics (success_rate, fallback_rate, average_latency)
    - _Requirements: 10.4_

- [x] 13. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Integrate with /chat endpoint
  - [x] 14.1 Refactor /chat endpoint to use Intent_Router
    - Modify `app.py` to initialize Intent_Router at startup
    - Register all capability handlers with Intent_Router
    - Replace regex-based routing cascade with Intent_Router.route()
    - Preserve existing response structure for backward compatibility
    - _Requirements: 3.1, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [x] 14.2 Add metrics endpoint to health check
    - Extend `/health` endpoint to include routing metrics
    - Expose: tool_selection_success_rate, fallback_rate, average_latency_ms
    - _Requirements: 10.4_

  - [ ]* 14.3 Write integration tests for end-to-end routing
    - Test music request through LLM tool selection
    - Test map/directions request through LLM tool selection
    - Test image/video request through LLM tool selection
    - Test multi-intent request (e.g., "Play music and show a map")
    - Test fallback scenario with simulated timeout
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 6.1, 6.2, 6.3_

- [x] 15. Performance optimization
  - [x] 15.1 Implement latency optimization for tool selection
    - Ensure Tool_Registry is loaded once at startup and cached
    - Verify connection pooling in Cerebras_Client
    - Implement 3-second timeout with immediate fallback delegation
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ]* 15.2 Write performance tests for latency requirements
    - Test tool selection completes within 2 seconds for 95% of requests
    - Test fallback delegation within 100ms after timeout
    - _Requirements: 9.1, 9.2_

- [x] 16. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation preserves existing regex patterns as fallback, ensuring zero disruption to current functionality
- All property-based tests use the Hypothesis library which is already configured in the project

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4"] },
    { "id": 3, "tasks": ["2.5", "4.1", "5.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4", "5.2", "5.3"] },
    { "id": 5, "tasks": ["7.1"] },
    { "id": 6, "tasks": ["7.2", "7.3", "7.4", "7.5", "7.6", "7.7", "8.1"] },
    { "id": 7, "tasks": ["8.2", "10.1"] },
    { "id": 8, "tasks": ["10.2", "10.3", "10.4", "10.5", "10.6", "11.1"] },
    { "id": 9, "tasks": ["11.2", "12.1"] },
    { "id": 10, "tasks": ["12.2", "12.3"] },
    { "id": 11, "tasks": ["14.1"] },
    { "id": 12, "tasks": ["14.2", "14.3", "15.1"] },
    { "id": 13, "tasks": ["15.2"] }
  ]
}
```
