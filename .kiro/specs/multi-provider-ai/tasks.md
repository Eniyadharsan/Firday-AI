# Implementation Plan: Multi-Provider AI Integration

## Overview

This implementation plan covers integrating multiple AI providers into FRIDAY through a unified provider abstraction layer. The system will support OpenAI ChatGPT, Anthropic Claude, Google Gemini, DeepSeek, Grok, Ollama, OpenRouter, and the existing Cerebras provider. Implementation follows an adapter pattern with a central registry, unified AI engine, and automatic failover capabilities.

## Tasks

- [x] 1. Set up core infrastructure and interfaces
  - [x] 1.1 Create provider module directory structure
    - Create `friday/modules/providers/` directory
    - Create `friday/modules/providers/__init__.py` with module exports
    - Create `friday/modules/providers/models.py` for data models
    - _Requirements: 1.1, 1.2_

  - [x] 1.2 Implement core data models and enums
    - Implement `ProviderStatus` enum (OPERATIONAL, DEGRADED, UNAVAILABLE, NOT_CONFIGURED)
    - Implement `ProviderType` enum for all supported providers
    - Implement `ProviderCapabilities`, `GenerateResponse`, `ProviderHealth`, `ProviderMetrics` dataclasses
    - Implement `FridayMessage`, `ConversationContext`, `StreamChunk`, `ToolCallRequest`, `ProviderError` dataclasses
    - _Requirements: 1.1, 8.3, 16.1, 16.2_

  - [x]* 1.3 Write property test for status color mapping
    - **Property 8: Status Color Mapping**
    - **Validates: Requirements 8.3**

  - [x] 1.4 Implement Provider_Adapter abstract base class
    - Create `friday/modules/providers/base.py`
    - Define abstract interface with all required methods: `generate`, `stream_generate`, `translate_tools`, `parse_tool_calls`, `get_available_models`, `get_health`, `is_configured`, `validate_config`
    - Define abstract properties: `provider_name`, `capabilities`
    - _Requirements: 1.1, 1.2, 1.4_

  - [x]* 1.5 Write property test for interface validation on registration
    - **Property 3: Interface Validation on Registration**
    - **Validates: Requirements 1.4**

- [x] 2. Implement API Key Store
  - [x] 2.1 Create API_Key_Store class
    - Create `friday/modules/providers/key_store.py`
    - Implement `load_from_env()` for environment variable loading
    - Implement `load_from_encrypted_file()` with Fernet encryption
    - Implement `get_key()`, `set_key()`, `is_configured()`, `validate_key()` methods
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x]* 2.2 Write property test for environment variable key loading
    - **Property 13: Environment Variable Key Loading**
    - **Validates: Requirements 10.2**

  - [x]* 2.3 Write property test for encrypted storage round-trip
    - **Property 14: Encrypted Storage Round-Trip**
    - **Validates: Requirements 10.3**

  - [x]* 2.4 Write unit tests for API_Key_Store
    - Test environment variable loading
    - Test encryption/decryption failure handling
    - Test key validation makes test API call
    - _Requirements: 10.2, 10.3, 10.6_

- [x] 3. Implement Provider Registry
  - [x] 3.1 Create Provider_Registry singleton class
    - Create `friday/modules/providers/registry.py`
    - Implement singleton pattern with `get_instance()`
    - Implement `register()` with interface method validation
    - Implement `get_adapter()`, `get_active_adapter()`, `set_active()`, `get_all_providers()`
    - _Requirements: 1.3, 1.4, 7.2_

  - [x]* 3.2 Write property test for provider registration tracking
    - **Property 2: Provider Registration Tracking**
    - **Validates: Requirements 1.3**

  - [x] 3.3 Implement health metrics tracking in Provider_Registry
    - Implement `record_request()` for latency and success/error tracking
    - Implement `get_health_metrics()`, `get_degraded_providers()`, `get_unavailable_providers()`
    - Implement status transitions based on error thresholds (50% error rate → DEGRADED, 5 consecutive failures → UNAVAILABLE)
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_

  - [x]* 3.4 Write property test for success and error rate calculation
    - **Property 23: Success and Error Rate Calculation**
    - **Validates: Requirements 16.2**

  - [x]* 3.5 Write property test for degraded status threshold
    - **Property 24: Degraded Status Threshold**
    - **Validates: Requirements 16.4**

  - [x]* 3.6 Write property test for unavailable status threshold
    - **Property 25: Unavailable Status Threshold**
    - **Validates: Requirements 16.5**

  - [x]* 3.7 Write unit tests for Provider_Registry
    - Test valid adapter registration
    - Test incomplete adapter rejection
    - Test active provider state updates
    - Test health metrics updates
    - _Requirements: 1.3, 1.4, 7.2, 16.1_

- [x] 4. Checkpoint - Core infrastructure complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement OpenAI Provider Adapter
  - [x] 5.1 Create OpenAI_Adapter class
    - Create `friday/modules/providers/adapters/openai_adapter.py`
    - Implement `generate()` for chat completions
    - Implement `stream_generate()` for streaming responses
    - Implement message translation to OpenAI chat format
    - Support GPT-4o, GPT-4-turbo, GPT-3.5-turbo models
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 5.2 Implement tool calling for OpenAI
    - Implement `translate_tools()` to OpenAI functions format
    - Implement `parse_tool_calls()` from OpenAI response
    - _Requirements: 2.5, 12.1, 12.2_

  - [x] 5.3 Implement error handling for OpenAI
    - Map rate limit errors with retry-after extraction
    - Map authentication and server errors
    - _Requirements: 2.6_

  - [x]* 5.4 Write property test for OpenAI message format translation
    - **Property 4: Message Format Translation (OpenAI)**
    - **Validates: Requirements 2.3**

  - [x]* 5.5 Write property test for OpenAI tool definition translation
    - **Property 5: Tool Definition Translation (OpenAI)**
    - **Validates: Requirements 2.5, 12.1**

  - [x]* 5.6 Write unit tests for OpenAI_Adapter
    - Test configuration validation
    - Test streaming yields tokens
    - Test rate limit error mapping
    - _Requirements: 2.1, 2.4, 2.6_

- [x] 6. Implement Anthropic Provider Adapter
  - [x] 6.1 Create Anthropic_Adapter class
    - Create `friday/modules/providers/adapters/anthropic_adapter.py`
    - Implement `generate()` for messages API
    - Implement `stream_generate()` using streaming events
    - Implement message translation to Anthropic format
    - Support Claude Opus, Sonnet, Haiku models
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 6.2 Implement tool calling for Anthropic
    - Implement `translate_tools()` to Anthropic tool_use format
    - Implement `parse_tool_calls()` from Anthropic response
    - _Requirements: 3.5, 12.1, 12.2_

  - [x] 6.3 Implement error handling for Anthropic
    - Map overloaded errors for failover handling
    - Map authentication and server errors
    - _Requirements: 3.6_

  - [x]* 6.4 Write property test for Anthropic message format translation
    - **Property 4: Message Format Translation (Anthropic)**
    - **Validates: Requirements 3.3**

  - [x]* 6.5 Write unit tests for Anthropic_Adapter
    - Test configuration validation
    - Test streaming event handling
    - Test overloaded error mapping
    - _Requirements: 3.1, 3.4, 3.6_

- [x] 7. Implement Google Gemini Provider Adapter
  - [x] 7.1 Create Gemini_Adapter class
    - Create `friday/modules/providers/adapters/gemini_adapter.py`
    - Implement `generate()` for generateContent API
    - Implement `stream_generate()` for streaming responses
    - Implement message translation to Gemini format
    - Support Gemini Pro, Flash, Ultra models
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 7.2 Implement tool calling for Gemini
    - Implement `translate_tools()` to Gemini function declarations format
    - Implement `parse_tool_calls()` from Gemini response
    - _Requirements: 4.5, 12.1, 12.2_

  - [x]* 7.3 Write property test for Gemini message format translation
    - **Property 4: Message Format Translation (Gemini)**
    - **Validates: Requirements 4.3**

  - [x]* 7.4 Write unit tests for Gemini_Adapter
    - Test configuration validation
    - Test streaming response handling
    - Test function declaration translation
    - _Requirements: 4.1, 4.4, 4.5_

- [x] 8. Implement Ollama Provider Adapter
  - [x] 8.1 Create Ollama_Adapter class
    - Create `friday/modules/providers/adapters/ollama_adapter.py`
    - Implement `generate()` for chat completions
    - Implement `stream_generate()` for streaming responses
    - Implement message translation to Ollama format
    - Implement `get_available_models()` to query Ollama API
    - Implement 3-second timeout for unreachable server detection
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 8.2 Implement tool capability checking for Ollama
    - Check model capabilities before attempting tool calls
    - Implement prompt-based fallback for models without tool support
    - _Requirements: 12.3, 12.5_

  - [x]* 8.3 Write property test for Ollama tool capability check
    - **Property 30: Ollama Tool Capability Check**
    - **Validates: Requirements 12.5**

  - [x]* 8.4 Write property test for Ollama message format translation
    - **Property 4: Message Format Translation (Ollama)**
    - **Validates: Requirements 5.3**

  - [x]* 8.5 Write unit tests for Ollama_Adapter
    - Test local server connection
    - Test model listing
    - Test unavailable status on timeout
    - _Requirements: 5.1, 5.2, 5.5_

- [x] 9. Checkpoint - Provider adapters for major providers complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Implement Additional Provider Adapters
  - [x] 10.1 Create DeepSeek_Adapter class
    - Create `friday/modules/providers/adapters/deepseek_adapter.py`
    - Implement full Provider_Adapter interface
    - _Requirements: 6.1_

  - [x] 10.2 Create Grok_Adapter class
    - Create `friday/modules/providers/adapters/grok_adapter.py`
    - Implement full Provider_Adapter interface for xAI API
    - _Requirements: 6.2_

  - [x] 10.3 Create OpenRouter_Adapter class
    - Create `friday/modules/providers/adapters/openrouter_adapter.py`
    - Implement full Provider_Adapter interface
    - Implement model catalog selection from OpenRouter
    - _Requirements: 6.3, 6.4_

  - [x] 10.4 Refactor existing Cerebras integration
    - Move existing Cerebras code to `friday/modules/providers/adapters/cerebras_adapter.py`
    - Refactor to implement Provider_Adapter interface
    - _Requirements: 6.5_

  - [x]* 10.5 Write unit tests for additional adapters
    - Test DeepSeek configuration and generation
    - Test Grok configuration and generation
    - Test OpenRouter model catalog
    - Test Cerebras adapter refactoring
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 11. Implement Failover Controller
  - [x] 11.1 Create Failover_Controller class
    - Create `friday/modules/providers/failover.py`
    - Implement `set_backup_order()` for ordered backup list
    - Implement `handle_failure()` to select next available backup
    - Implement `get_failover_status()` for UI display
    - _Requirements: 9.1, 9.2, 9.4_

  - [x]* 11.2 Write property test for backup order maintenance
    - **Property 9: Backup Order Maintenance**
    - **Validates: Requirements 9.1**

  - [x]* 11.3 Write property test for failover on provider error
    - **Property 10: Failover on Provider Error**
    - **Validates: Requirements 9.2**

  - [x] 11.4 Implement primary provider restoration
    - Implement `attempt_restore()` to check primary every 60 seconds
    - Emit notification without automatic switch back
    - _Requirements: 9.5, 9.6_

  - [x]* 11.5 Write property test for active provider state after failover
    - **Property 11: Active Provider State After Failover**
    - **Validates: Requirements 9.3**

  - [x]* 11.6 Write property test for primary restore notification
    - **Property 12: Primary Restore Notification Without Auto-Switch**
    - **Validates: Requirements 9.6**

  - [x]* 11.7 Write unit tests for Failover_Controller
    - Test backup order preservation
    - Test first backup selection
    - Test skipping unavailable backups
    - Test restore notification behavior
    - _Requirements: 9.1, 9.2, 9.5, 9.6_

- [x] 12. Implement Unified AI Engine
  - [x] 12.1 Create Unified_AI_Engine class
    - Create `friday/modules/providers/engine.py`
    - Implement `generate()` with context enrichment and provider routing
    - Implement `stream_generate()` with unified streaming format
    - Implement `select_tools()` for tool selection
    - _Requirements: 1.1, 1.5, 11.1, 11.2_

  - [x]* 12.2 Write property test for unified response format consistency
    - **Property 1: Unified Response Format Consistency**
    - **Validates: Requirements 1.1**

  - [x]* 12.3 Write property test for streaming format normalization
    - **Property 15: Streaming Format Normalization**
    - **Validates: Requirements 11.1**

  - [x] 12.4 Implement memory and RAG context injection
    - Inject long-term memory context into prompts
    - Inject RAG document context into prompts
    - Respect context window limits when injecting
    - _Requirements: 13.1, 13.2, 13.4_

  - [x]* 12.5 Write property test for context injection
    - **Property 17: Context Injection**
    - **Validates: Requirements 13.1, 13.2**

  - [x]* 12.6 Write property test for context window limit enforcement
    - **Property 18: Context Window Limit Enforcement**
    - **Validates: Requirements 13.4**

  - [x] 12.7 Implement conversation history management
    - Maintain single conversation history across provider switches
    - Include relevant history in new provider context
    - Tag messages with provider and model metadata
    - _Requirements: 13.3, 14.1, 14.2, 14.3, 14.4_

  - [x]* 12.8 Write property test for conversation history preservation
    - **Property 19: Conversation History Preservation Across Provider Switches**
    - **Validates: Requirements 13.3**

  - [x]* 12.9 Write property test for history inclusion on provider switch
    - **Property 20: History Inclusion on Provider Switch**
    - **Validates: Requirements 14.2**

  - [x]* 12.10 Write property test for message provider metadata
    - **Property 21: Message Provider Metadata**
    - **Validates: Requirements 14.3, 14.4**

  - [x] 12.11 Implement tool calling compatibility layer
    - Translate FRIDAY tool definitions to provider native format
    - Parse tool calls to FRIDAY ToolCall format
    - Implement prompt-based fallback for unsupported providers
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [x]* 12.12 Write property test for tool call parsing
    - **Property 6: Tool Call Parsing**
    - **Validates: Requirements 12.2**

  - [x] 12.13 Implement streaming interruption handling
    - Handle interrupted streaming connections gracefully
    - Return partial content on interruption
    - Preserve markdown formatting in streamed content
    - _Requirements: 11.3, 11.4_

  - [x]* 12.14 Write property test for markdown preservation in streaming
    - **Property 16: Markdown Preservation in Streaming**
    - **Validates: Requirements 11.4**

  - [x]* 12.15 Write unit tests for Unified_AI_Engine
    - Test memory context injection
    - Test RAG context injection
    - Test context window limit enforcement
    - Test conversation history preservation
    - Test streaming normalization
    - _Requirements: 1.1, 11.1, 13.1, 13.2, 13.4, 14.1_

- [x] 13. Checkpoint - Backend core complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Implement Backend API Routes
  - [x] 14.1 Create provider management API routes
    - Add `/api/providers` GET endpoint for provider list with status
    - Add `/api/providers/active` GET/PUT endpoints for active provider
    - Add `/api/providers/<provider>/validate` POST endpoint for key validation
    - Add `/api/providers/<provider>/models` GET endpoint for model list
    - _Requirements: 7.1, 7.2, 7.4, 7.7_

  - [x] 14.2 Add provider metrics to health endpoint
    - Extend existing `/health` endpoint with provider health metrics
    - Include latency and success/error rates per provider
    - _Requirements: 16.3_

  - [x] 14.3 Integrate Unified_AI_Engine with existing chat route
    - Replace direct Cerebras calls with Unified_AI_Engine
    - Preserve existing chat functionality
    - Add provider/model metadata to responses
    - _Requirements: 1.1, 14.3, 14.4_

  - [x]* 14.4 Write unit tests for API routes
    - Test provider list endpoint
    - Test active provider endpoints
    - Test key validation endpoint
    - Test health endpoint with metrics
    - _Requirements: 7.1, 7.2, 7.4, 16.3_

- [x] 15. Implement Frontend UI Components
  - [x] 15.1 Create Active Model Badge component
    - Create badge component displaying current model name (abbreviated)
    - Implement color-coded status indicator (green/yellow/red)
    - Implement 2-second status update on change
    - Add click handler to open Model Manager
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x]* 15.2 Write property test for model name abbreviation
    - **Property 7: Model Name Abbreviation**
    - **Validates: Requirements 8.2**

  - [x] 15.3 Create Model Manager panel
    - Display all providers with configuration status
    - Implement provider/model selection UI
    - Create secure API key input fields with masking
    - Display connection latency per provider
    - Display token usage statistics for session
    - Display context window size per model
    - Implement 30-second status refresh
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 7.6, 7.7, 7.8_

  - [x] 15.4 Apply holographic styling to UI components
    - Apply existing FRIDAY holographic styles to Active Model Badge
    - Apply existing FRIDAY holographic styles to Model Manager panel
    - Ensure seamless integration with existing header design
    - _Requirements: 8.4, 15.4, 15.5_

  - [x]* 15.5 Write unit tests for frontend components
    - Test badge status indicator colors
    - Test badge click opens manager
    - Test provider list display
    - Test API key masking
    - _Requirements: 8.2, 8.3, 8.5, 7.3_

- [x] 16. Implement Failover UI Integration
  - [x] 16.1 Update Active Model Badge for failover
    - Display new provider after failover
    - Show failover indicator/message
    - _Requirements: 9.3_

  - [x] 16.2 Implement primary restore notification
    - Display notification when primary becomes available
    - Provide option to switch back manually
    - _Requirements: 9.6_

  - [x]* 16.3 Write unit tests for failover UI
    - Test badge updates on failover
    - Test restore notification display
    - _Requirements: 9.3, 9.6_

- [x] 17. Implement Database Schema Extensions
  - [x] 17.1 Create database migrations
    - Add `provider_configs` table
    - Add `provider_metrics` table
    - Add `provider` and `model` columns to conversations table
    - Add `user_provider_prefs` table
    - _Requirements: 7.2, 14.3, 16.1_

  - [x]* 17.2 Write unit tests for database operations
    - Test provider config CRUD
    - Test metrics recording
    - Test user preferences
    - _Requirements: 7.2, 16.1_

- [x] 18. Checkpoint - Feature implementation complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 19. Integration and UI Preservation Verification
  - [x] 19.1 Verify UI preservation
    - Verify orb animation and visual effects preserved
    - Verify holographic styling and color scheme preserved
    - Verify mobile and desktop responsive layouts preserved
    - Verify all existing animations and transitions preserved
    - _Requirements: 15.1, 15.2, 15.3, 15.6_

  - [x]* 19.2 Write integration tests for provider switching
    - Test switching between providers mid-conversation
    - Test conversation history preservation
    - Test failover scenario
    - _Requirements: 13.3, 14.1, 14.2, 9.2_

  - [x]* 19.3 Write property test for provider selection state update
    - **Property 26: Provider Selection State Update**
    - **Validates: Requirements 7.2**

  - [x]* 19.4 Write property test for request latency tracking
    - **Property 22: Request Latency Tracking**
    - **Validates: Requirements 16.1**

  - [x]* 19.5 Write property test for latency data availability
    - **Property 27: Latency Data Availability**
    - **Validates: Requirements 7.5**

  - [x]* 19.6 Write property test for session token usage tracking
    - **Property 28: Session Token Usage Tracking**
    - **Validates: Requirements 7.6**

  - [x]* 19.7 Write property test for context window information
    - **Property 29: Context Window Information**
    - **Validates: Requirements 7.7**

- [x] 20. Final checkpoint - All tests passing
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The existing Cerebras integration will be refactored to use the new Provider_Adapter interface
- All provider adapters follow the same abstract interface pattern for consistency
- API keys are never exposed to the frontend - all key operations happen on the backend

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.4"] },
    { "id": 2, "tasks": ["1.3", "1.5", "2.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "2.4", "3.1"] },
    { "id": 4, "tasks": ["3.2", "3.3"] },
    { "id": 5, "tasks": ["3.4", "3.5", "3.6", "3.7"] },
    { "id": 6, "tasks": ["5.1", "6.1", "7.1", "8.1"] },
    { "id": 7, "tasks": ["5.2", "5.3", "6.2", "6.3", "7.2", "8.2"] },
    { "id": 8, "tasks": ["5.4", "5.5", "5.6", "6.4", "6.5", "7.3", "7.4", "8.3", "8.4", "8.5"] },
    { "id": 9, "tasks": ["10.1", "10.2", "10.3", "10.4"] },
    { "id": 10, "tasks": ["10.5", "11.1"] },
    { "id": 11, "tasks": ["11.2", "11.3", "11.4"] },
    { "id": 12, "tasks": ["11.5", "11.6", "11.7", "12.1"] },
    { "id": 13, "tasks": ["12.2", "12.3", "12.4"] },
    { "id": 14, "tasks": ["12.5", "12.6", "12.7"] },
    { "id": 15, "tasks": ["12.8", "12.9", "12.10", "12.11"] },
    { "id": 16, "tasks": ["12.12", "12.13"] },
    { "id": 17, "tasks": ["12.14", "12.15"] },
    { "id": 18, "tasks": ["14.1", "14.2", "14.3", "17.1"] },
    { "id": 19, "tasks": ["14.4", "17.2", "15.1"] },
    { "id": 20, "tasks": ["15.2", "15.3"] },
    { "id": 21, "tasks": ["15.4", "15.5", "16.1"] },
    { "id": 22, "tasks": ["16.2", "16.3"] },
    { "id": 23, "tasks": ["19.1"] },
    { "id": 24, "tasks": ["19.2", "19.3", "19.4", "19.5", "19.6", "19.7"] }
  ]
}
```
