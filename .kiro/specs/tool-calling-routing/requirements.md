# Requirements Document

## Introduction

This document specifies requirements for refactoring FRIDAY's intent routing system from regex-based pattern matching to LLM-native tool/function calling via Cerebras. The current architecture uses multiple `is_X_request()` functions with hardcoded regex patterns to route user messages to different capabilities (music, maps, images, video, research, agents). This approach has inherent limitations in handling ambiguous requests, multi-intent messages, and evolving natural language patterns.

The new architecture will leverage OpenAI-style function calling through the Cerebras API, allowing the LLM to natively select appropriate tools based on semantic understanding rather than keyword matching. This provides more robust routing, enables multi-tool orchestration, and eliminates the maintenance burden of regex patterns.

## Glossary

- **Intent_Router**: The component responsible for analyzing user messages and determining which capability module should handle the request
- **Tool_Definition**: A structured schema describing a callable function, including its name, description, and parameter specifications in JSON Schema format
- **Tool_Call**: The LLM's structured response indicating which tool(s) to invoke and with what arguments
- **Capability_Handler**: A module that processes a specific type of request (e.g., Music_Handler, Maps_Handler, Image_Handler)
- **Cerebras_Client**: The HTTP client that communicates with the Cerebras API for LLM inference
- **Fallback_Router**: A backup routing mechanism used when the LLM tool calling fails or times out
- **Multi_Intent_Request**: A user message that requires invoking multiple capability handlers to fulfill
- **Tool_Registry**: A centralized collection of all available tool definitions that the LLM can select from

## Requirements

### Requirement 1: Tool Definition Schema

**User Story:** As a developer, I want each capability to be defined as a tool with a standardized schema, so that the LLM can understand and select the appropriate handler.

#### Acceptance Criteria

1. THE Tool_Registry SHALL maintain tool definitions conforming to OpenAI function calling schema format with name (1-64 characters), description (1-1024 characters), and parameters fields
2. WHEN a Capability_Handler is registered, THE Tool_Registry SHALL validate that the tool definition includes a name of at least 1 character, a description of at least 1 character, and a parameters object that is a valid JSON Schema object (containing at minimum "type": "object")
3. IF a Capability_Handler registration provides a tool definition that fails validation, THEN THE Tool_Registry SHALL reject the registration and return an error indicating which validation check failed (missing name, missing description, or invalid parameters schema)
4. THE Tool_Definition description field SHALL include the capability's purpose and at least one distinguishing keyword or phrase that differentiates it from related capabilities (e.g., music playback description must reference "play" or "listen"; music_control must reference "pause", "skip", or "volume")
5. FOR ALL existing capabilities (music, music_control, maps, directions, image, video, research, news, weather, stock, web_search), THE Tool_Registry SHALL contain a corresponding tool definition

### Requirement 2: Cerebras Tool Calling Integration

**User Story:** As a developer, I want the Cerebras client to support OpenAI-compatible tool calling, so that routing decisions are made by the LLM semantically.

#### Acceptance Criteria

1. WHEN the Cerebras_Client sends a chat completion request, THE Cerebras_Client SHALL include the tools parameter containing the Tool_Registry definitions formatted as an array of tool objects
2. WHEN the Cerebras API returns a response with tool_calls, THE Cerebras_Client SHALL parse and return structured Tool_Call objects containing id, function name, and arguments fields
3. IF the Cerebras API returns a response without tool_calls, THEN THE Intent_Router SHALL treat the response as a general conversation requiring no capability handler and return the assistant message content directly
4. IF the Cerebras_Client encounters a connection failure, HTTP error status code (4xx or 5xx), request timeout exceeding 3 seconds, or response parsing failure during tool selection, THEN THE Intent_Router SHALL delegate to the Fallback_Router
5. THE Cerebras_Client SHALL support the tool_choice parameter with values "auto", "none", or a specific tool name to control tool selection behavior
6. IF the Cerebras API returns a tool_calls array containing entries with missing or invalid function name or unparseable arguments, THEN THE Cerebras_Client SHALL treat this as a parsing failure and delegate to the Fallback_Router

### Requirement 3: Intent Router Refactor

**User Story:** As a developer, I want to replace regex-based routing with LLM tool selection, so that routing is more accurate and maintainable.

#### Acceptance Criteria

1. WHEN a user message is received, THE Intent_Router SHALL send the message to the Cerebras_Client with the registered tool definitions and await a response within 10 seconds
2. WHEN the Cerebras_Client returns a Tool_Call, THE Intent_Router SHALL route the request to the Capability_Handler matching the Tool_Call function name
3. WHEN routing to a Capability_Handler, THE Intent_Router SHALL pass the Tool_Call arguments directly as structured parameters
4. WHEN the LLM selects multiple tools in a single response, THE Intent_Router SHALL execute each Tool_Call sequentially up to a maximum of 5 tools per request and concatenate the responses in execution order
5. IF no Tool_Call is returned and the response contains assistant content, THEN THE Intent_Router SHALL return the content as a general conversational response
6. IF the Cerebras_Client returns a malformed response or the response cannot be parsed, THEN THE Intent_Router SHALL return an error response indicating a routing failure
7. IF the Tool_Call function name does not match any registered Capability_Handler, THEN THE Intent_Router SHALL return an error response indicating an unknown capability

### Requirement 4: Backward Compatibility

**User Story:** As a user, I want existing requests to continue working after the refactor, so that my workflows are not disrupted.

#### Acceptance Criteria

1. WHEN a request matches patterns defined by is_music_request() (including "play [query]", "put on [query]", "queue [query]", "listen to [query]", or music-related keywords with intent verbs), THE Intent_Router SHALL route to Music_Handler and return the same response structure as the original implementation
2. WHEN a request matches patterns defined by is_map_request() or is_directions_request() (including "map of [location]", "directions to [destination]", "navigate to [destination]", "where is [location]", or "from [origin] to [destination]" routing requests), THE Intent_Router SHALL route to Maps_Handler and return the same response structure as the original implementation
3. WHEN a request matches patterns defined by is_image_request() (including "generate/create/make [image type]", "show me [visual subject]", or explicit image/picture/photo keywords with action verbs), THE Intent_Router SHALL route to Image_Handler and return the same response structure as the original implementation
4. WHEN a request matches patterns defined by is_video_request() (including "generate/create/make [video/clip/animation]" with video-related keywords), THE Intent_Router SHALL route to Video_Handler and return the same response structure as the original implementation
5. WHEN a request matches patterns defined by is_research_request() (including "research", "deep dive", "investigate", "comprehensive", "detailed analysis", or "report on" keywords), THE Intent_Router SHALL route to Research_Handler and return the same response structure as the original implementation
6. WHEN a request matches patterns defined by detect_playback_control() (including "pause", "stop", "next", "skip", "previous", or "resume" playback commands), THE Intent_Router SHALL route to Music_Control_Handler and return the corresponding control action (pause, stop, next, previous, or resume)
7. IF a request matches multiple handler patterns simultaneously, THEN THE Intent_Router SHALL apply the same pattern matching priority order as the original implementation (playback control checked before music request, directions checked before general map request)
8. IF a request does not match any defined handler pattern, THEN THE Intent_Router SHALL route to the default handler without error

### Requirement 5: Fallback Routing

**User Story:** As a user, I want my requests to be handled even when the LLM tool selection fails, so that the system remains reliable.

#### Acceptance Criteria

1. IF the Cerebras API times out within 3 seconds during tool selection, THEN THE Fallback_Router SHALL use the regex-based is_X_request() functions (is_music_request, is_image_request, is_video_request, is_map_request, is_research_request) to determine routing
2. IF the Cerebras API returns an HTTP 4xx or 5xx status code during tool selection, THEN THE Fallback_Router SHALL use the regex-based is_X_request() functions to determine routing
3. WHEN the Fallback_Router handles a request, THE Intent_Router SHALL log the fallback event at warning severity including: the original error type (timeout or HTTP status code), the timestamp, and the fallback routing decision
4. THE Fallback_Router SHALL preserve the regex-based is_X_request() functions as a backup mechanism that remains callable independently of the LLM routing path
5. IF the regex-based fallback routing matches no known request pattern, THEN THE Fallback_Router SHALL route the request to the default LLM chat handler

### Requirement 6: Multi-Intent Handling

**User Story:** As a user, I want to make requests that involve multiple capabilities in one message, so that I can accomplish more with fewer interactions.

#### Acceptance Criteria

1. WHEN the LLM returns multiple Tool_Calls in parallel_tool_calls mode, THE Intent_Router SHALL execute all specified tools up to a maximum of 10 Tool_Calls per request
2. WHEN executing multiple Tool_Calls, THE Intent_Router SHALL execute them sequentially in the order returned by the LLM
3. WHEN all Tool_Calls in a multi-intent request complete, THE Intent_Router SHALL combine responses into a single response object containing an array of individual tool results, where each result includes the tool name and its output
4. IF a Tool_Call in a multi-intent request fails due to an exception or error response from the Capability_Handler, THEN THE Intent_Router SHALL continue executing remaining Tool_Calls and return a combined response where failed tools are marked with an error indicator and successful tools include their results

### Requirement 7: Tool Parameter Extraction

**User Story:** As a developer, I want the LLM to extract structured parameters from user messages, so that capability handlers receive clean, typed inputs.

#### Acceptance Criteria

1. WHEN the LLM selects the music_play tool, THE Tool_Call arguments SHALL include the extracted song_query parameter as a non-empty string of 1 to 500 characters
2. WHEN the LLM selects the map_view tool, THE Tool_Call arguments SHALL include the extracted place parameter as a non-empty string of 1 to 200 characters
3. WHEN the LLM selects the directions tool, THE Tool_Call arguments SHALL include origin and destination parameters, where destination is a non-empty string of 1 to 200 characters and origin is a string of 0 to 200 characters
4. WHEN the LLM selects the image_generate tool, THE Tool_Call arguments SHALL include the extracted prompt parameter as a non-empty string of 1 to 1000 characters
5. WHEN the LLM selects the video_generate tool, THE Tool_Call arguments SHALL include the extracted prompt parameter as a non-empty string of 1 to 1000 characters
6. WHEN the LLM selects the web_search tool, THE Tool_Call arguments SHALL include the extracted query parameter as a non-empty string of 1 to 500 characters
7. IF the LLM cannot extract a required parameter for a selected tool, THEN THE System SHALL return an error response indicating the missing parameter without invoking the tool handler

### Requirement 8: Response Format Preservation

**User Story:** As a frontend developer, I want the API response format to remain unchanged, so that frontend code continues to work without modification.

#### Acceptance Criteria

1. WHEN a music request is processed successfully, THE Intent_Router SHALL return a JSON response containing: reply (string), sessionId (string), action set to "play_music_embed", and track (object with video_id, title, artist, and thumbnail_url fields)
2. WHEN a map view request is processed, THE Intent_Router SHALL return a JSON response containing: reply (string), sessionId (string), action set to "show_map", mode set to "view", and place (string indicating the location to display)
3. WHEN a map directions request is processed, THE Intent_Router SHALL return a JSON response containing: reply (string), sessionId (string), action set to "show_map", mode set to "directions", destination (string), and origin (string, which may be empty if not specified by the user)
4. WHEN an image request is processed, THE Intent_Router SHALL return a JSON response containing: reply (string), sessionId (string), action set to "show_image", imageUrl (string containing the generated image URL), and imagePrompt (string containing the original request)
5. WHEN a video request is processed, THE Intent_Router SHALL return a JSON response containing: reply (string), sessionId (string), action set to "show_video", videoUrl (string containing the generated video URL), and videoPrompt (string containing the original request)
6. WHEN a research request is processed, THE Intent_Router SHALL return a JSON response containing: reply (string), sessionId (string), action set to "show_report", report (string containing the full report text), topic (string), and meta (object with sources, news, and time fields indicating counts and duration)

### Requirement 9: Latency Optimization

**User Story:** As a user, I want routing decisions to be fast, so that response times remain acceptable.

#### Acceptance Criteria

1. THE Intent_Router SHALL complete tool selection within 2 seconds for 95% of requests when handling up to 50 concurrent routing requests
2. WHEN tool selection exceeds the 3-second timeout, THE Intent_Router SHALL delegate to Fallback_Router within 100 milliseconds and cancel the pending Cerebras API request
3. THE Cerebras_Client SHALL reuse HTTP connections via connection pooling to minimize connection overhead
4. THE Tool_Registry SHALL be loaded once at application startup and cached in memory

### Requirement 10: Observability

**User Story:** As a developer, I want to monitor the tool calling system, so that I can identify and resolve issues quickly.

#### Acceptance Criteria

1. WHEN tool selection completes, THE Intent_Router SHALL log a timestamped entry containing the selected tool name, extracted arguments, and selection latency in milliseconds
2. WHEN a fallback occurs, THE Intent_Router SHALL log a timestamped entry containing the fallback trigger reason and the fallback routing decision
3. WHEN tool execution fails, THE Intent_Router SHALL log a timestamped entry containing the tool name, error type, and error message truncated to a maximum of 1000 characters
4. THE Intent_Router SHALL expose metrics via the health endpoint including tool selection success rate as a percentage, fallback rate as a percentage, and average selection latency in milliseconds, calculated over a rolling 5-minute window
