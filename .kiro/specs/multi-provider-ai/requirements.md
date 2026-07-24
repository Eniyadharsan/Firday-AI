# Requirements Document

## Introduction

This document specifies requirements for integrating multiple AI providers into FRIDAY as first-class capabilities. The system will support OpenAI ChatGPT, Anthropic Claude, Google Gemini, DeepSeek, Grok, Ollama, OpenRouter, and the existing Cerebras provider through a unified provider abstraction layer. Users will be able to seamlessly switch between providers without changing the UI, while FRIDAY preserves its existing holographic interface, orb animations, and overall visual identity.

## Glossary

- **Unified_AI_Engine**: The core abstraction layer that routes prompts to the configured AI provider while presenting a consistent interface to the rest of FRIDAY
- **Provider_Adapter**: A standardized interface implementation for a specific AI provider (OpenAI, Claude, Gemini, etc.) that translates FRIDAY requests into provider-specific API calls
- **Provider_Registry**: The component that maintains the list of available providers, their configurations, and connection status
- **Model_Manager**: The user-facing component for selecting providers, configuring API keys, viewing status, and monitoring usage metrics
- **Active_Model_Badge**: The header UI element displaying the current provider, model name, and operational status
- **Failover_Controller**: The component responsible for detecting provider failures and automatically switching to backup providers
- **API_Key_Store**: The secure backend storage system for provider API keys using environment variables or encrypted storage
- **Provider_Status**: An enumeration of provider states: Operational, Degraded, Unavailable, Not_Configured
- **Context_Window**: The maximum number of tokens a model can process in a single request
- **Streaming_Response**: A response delivered incrementally as tokens are generated rather than waiting for completion

## Requirements

### Requirement 1: Provider Abstraction Layer

**User Story:** As a developer, I want a unified interface for all AI providers, so that I can add new providers without modifying core FRIDAY logic.

#### Acceptance Criteria

1. THE Unified_AI_Engine SHALL expose a consistent interface for sending prompts and receiving responses regardless of the underlying provider
2. WHEN a new provider is added, THE Provider_Adapter interface SHALL require only implementation of provider-specific API translation without changes to FRIDAY core
3. THE Provider_Registry SHALL maintain a list of all registered Provider_Adapters with their configuration and status
4. WHEN a Provider_Adapter is registered, THE Provider_Registry SHALL validate that the adapter implements all required interface methods
5. THE Unified_AI_Engine SHALL support both synchronous and streaming response modes through the same interface

### Requirement 2: OpenAI ChatGPT Integration

**User Story:** As a user, I want to use ChatGPT through FRIDAY, so that I can access GPT models while keeping the FRIDAY experience.

#### Acceptance Criteria

1. THE Provider_Adapter for OpenAI SHALL connect to the OpenAI API using the configured API key
2. WHEN an OpenAI API key is configured, THE Provider_Adapter SHALL support GPT-4o, GPT-4-turbo, and GPT-3.5-turbo models
3. THE Provider_Adapter for OpenAI SHALL translate FRIDAY message formats to OpenAI chat completion format
4. WHEN streaming is enabled, THE Provider_Adapter for OpenAI SHALL yield tokens incrementally using OpenAI's streaming API
5. THE Provider_Adapter for OpenAI SHALL support function calling using OpenAI's tools format
6. IF the OpenAI API returns a rate limit error, THEN THE Provider_Adapter SHALL propagate the error with retry-after information

### Requirement 3: Anthropic Claude Integration

**User Story:** As a user, I want to use Claude through FRIDAY, so that I can access Anthropic models for complex reasoning tasks.

#### Acceptance Criteria

1. THE Provider_Adapter for Anthropic SHALL connect to the Anthropic API using the configured API key
2. WHEN an Anthropic API key is configured, THE Provider_Adapter SHALL support Claude Opus, Sonnet, and Haiku models
3. THE Provider_Adapter for Anthropic SHALL translate FRIDAY message formats to Anthropic's messages API format
4. WHEN streaming is enabled, THE Provider_Adapter for Anthropic SHALL yield tokens incrementally using Anthropic's streaming events
5. THE Provider_Adapter for Anthropic SHALL support tool use using Anthropic's tool_use format
6. IF the Anthropic API returns an overloaded error, THEN THE Provider_Adapter SHALL propagate the error for failover handling

### Requirement 4: Google Gemini Integration

**User Story:** As a user, I want to use Gemini through FRIDAY, so that I can access Google's multimodal AI capabilities.

#### Acceptance Criteria

1. THE Provider_Adapter for Gemini SHALL connect to the Google AI API using the configured API key
2. WHEN a Gemini API key is configured, THE Provider_Adapter SHALL support Gemini Pro, Gemini Flash, and Gemini Ultra models
3. THE Provider_Adapter for Gemini SHALL translate FRIDAY message formats to Gemini's generateContent format
4. WHEN streaming is enabled, THE Provider_Adapter for Gemini SHALL yield tokens incrementally using Gemini's streaming API
5. THE Provider_Adapter for Gemini SHALL support function calling using Gemini's function declarations format

### Requirement 5: Local Ollama Integration

**User Story:** As a user, I want to use local Ollama models through FRIDAY, so that I can run AI privately without sending data to external services.

#### Acceptance Criteria

1. THE Provider_Adapter for Ollama SHALL connect to the local Ollama server at the configured host address
2. WHEN Ollama is configured, THE Provider_Adapter SHALL query available models from the Ollama API
3. THE Provider_Adapter for Ollama SHALL translate FRIDAY message formats to Ollama's chat completion format
4. WHEN streaming is enabled, THE Provider_Adapter for Ollama SHALL yield tokens incrementally using Ollama's streaming response
5. IF the Ollama server is unreachable, THEN THE Provider_Adapter SHALL report status as Unavailable within 3 seconds

### Requirement 6: Additional Provider Support

**User Story:** As a user, I want access to DeepSeek, Grok, and OpenRouter, so that I can choose the best model for each task.

#### Acceptance Criteria

1. THE Provider_Adapter for DeepSeek SHALL connect to the DeepSeek API using the configured API key
2. THE Provider_Adapter for Grok SHALL connect to the xAI API using the configured API key
3. THE Provider_Adapter for OpenRouter SHALL connect to the OpenRouter API using the configured API key
4. WHEN using OpenRouter, THE Provider_Adapter SHALL allow selection of any model available through OpenRouter's catalog
5. THE Provider_Adapter for existing Cerebras integration SHALL be refactored to implement the Provider_Adapter interface

### Requirement 7: Model Manager UI

**User Story:** As a user, I want a settings panel to manage AI providers, so that I can configure and switch between them easily.

#### Acceptance Criteria

1. THE Model_Manager SHALL display all registered providers with their configuration status
2. THE Model_Manager SHALL allow users to select the active provider and model
3. THE Model_Manager SHALL provide secure input fields for API keys that mask the key value
4. WHEN an API key is entered, THE Model_Manager SHALL validate the key by making a test API call
5. THE Model_Manager SHALL display connection latency for each configured provider
6. THE Model_Manager SHALL display token usage statistics for the current session
7. THE Model_Manager SHALL display the context window size for each available model
8. WHILE the Model_Manager is open, THE Model_Manager SHALL refresh provider status every 30 seconds

### Requirement 8: Active Model Badge

**User Story:** As a user, I want to see which AI model is currently active, so that I know which provider is answering my questions.

#### Acceptance Criteria

1. THE Active_Model_Badge SHALL display in the FRIDAY header area
2. THE Active_Model_Badge SHALL show the current model name in abbreviated form (e.g., "GPT-4o", "Claude-3", "Gemini-Pro")
3. THE Active_Model_Badge SHALL show the Provider_Status using a color-coded indicator (green for Operational, yellow for Degraded, red for Unavailable)
4. WHEN the provider status changes, THE Active_Model_Badge SHALL update within 2 seconds
5. WHEN the user clicks the Active_Model_Badge, THE Model_Manager SHALL open

### Requirement 9: Automatic Failover

**User Story:** As a user, I want FRIDAY to automatically switch providers when one fails, so that I can continue working without interruption.

#### Acceptance Criteria

1. THE Failover_Controller SHALL maintain an ordered list of backup providers
2. WHEN the active provider returns an error, THE Failover_Controller SHALL attempt the request with the next available backup provider
3. WHEN failover occurs, THE Active_Model_Badge SHALL display the new active provider
4. IF all configured providers fail, THEN THE Unified_AI_Engine SHALL return an error message indicating all providers are unavailable
5. THE Failover_Controller SHALL attempt to restore the primary provider every 60 seconds after failover
6. WHEN the primary provider becomes available again, THE Failover_Controller SHALL notify the user but not automatically switch back

### Requirement 10: Secure API Key Storage

**User Story:** As a user, I want my API keys stored securely, so that they are never exposed to the frontend or unauthorized access.

#### Acceptance Criteria

1. THE API_Key_Store SHALL store API keys only on the backend server
2. THE API_Key_Store SHALL support loading API keys from environment variables
3. THE API_Key_Store SHALL support loading API keys from encrypted file storage
4. THE API_Key_Store SHALL never transmit API keys to the frontend client
5. WHEN an API key is updated through the Model_Manager, THE API_Key_Store SHALL validate and store it on the backend only
6. IF an API key decryption fails, THEN THE API_Key_Store SHALL log the error and mark the provider as Not_Configured

### Requirement 11: Streaming Response Preservation

**User Story:** As a user, I want streaming responses to work the same regardless of provider, so that I get fast, incremental output.

#### Acceptance Criteria

1. THE Unified_AI_Engine SHALL convert all provider-specific streaming formats to a common token stream format
2. WHEN streaming is active, THE Unified_AI_Engine SHALL yield tokens to the frontend as they arrive without buffering
3. IF a streaming connection is interrupted, THEN THE Unified_AI_Engine SHALL attempt to resume or fail gracefully with partial content
4. THE Unified_AI_Engine SHALL preserve markdown formatting in streamed content across all providers

### Requirement 12: Tool Calling Compatibility

**User Story:** As a user, I want FRIDAY's tools to work with all providers, so that I can use music, maps, and other features with any model.

#### Acceptance Criteria

1. THE Unified_AI_Engine SHALL translate FRIDAY's tool definitions to each provider's native format
2. WHEN a provider returns a tool call, THE Unified_AI_Engine SHALL parse it into FRIDAY's standard ToolCall format
3. IF a provider does not support tool calling, THEN THE Unified_AI_Engine SHALL use prompt-based tool extraction as fallback
4. THE Unified_AI_Engine SHALL support tool calling for OpenAI, Anthropic, Gemini, and OpenRouter providers
5. WHEN using Ollama, THE Unified_AI_Engine SHALL check model capabilities before attempting tool calls

### Requirement 13: Memory and RAG Integration

**User Story:** As a user, I want my memories and documents to work with all providers, so that context is preserved regardless of which model I use.

#### Acceptance Criteria

1. THE Unified_AI_Engine SHALL inject long-term memory context into prompts for all providers
2. THE Unified_AI_Engine SHALL inject RAG document context into prompts for all providers
3. WHEN switching providers mid-conversation, THE Unified_AI_Engine SHALL maintain the conversation history
4. THE Unified_AI_Engine SHALL respect each provider's context window limit when injecting memory and RAG context

### Requirement 14: Unified Conversation Interface

**User Story:** As a user, I want one conversation that can span multiple providers, so that I can switch models without losing context.

#### Acceptance Criteria

1. THE Unified_AI_Engine SHALL maintain a single conversation history regardless of provider switches
2. WHEN a provider switch occurs, THE Unified_AI_Engine SHALL include relevant conversation history in the new provider's context
3. THE Unified_AI_Engine SHALL tag each message in history with the provider and model that generated it
4. THE Unified_AI_Engine SHALL allow users to view which model generated each response in the conversation

### Requirement 15: UI Preservation

**User Story:** As a user, I want FRIDAY to look and feel exactly the same after adding new providers, so that the experience remains consistent.

#### Acceptance Criteria

1. THE FRIDAY_UI SHALL preserve the existing orb animation and visual effects
2. THE FRIDAY_UI SHALL preserve the existing holographic styling and color scheme
3. THE FRIDAY_UI SHALL preserve the existing mobile and desktop responsive layouts
4. THE Active_Model_Badge SHALL integrate seamlessly with the existing header design
5. THE Model_Manager SHALL use the same holographic styling as existing FRIDAY panels
6. THE FRIDAY_UI SHALL preserve all existing animations, transitions, and visual feedback

### Requirement 16: Provider Health Monitoring

**User Story:** As a developer, I want to monitor provider health and performance, so that I can ensure reliable service.

#### Acceptance Criteria

1. THE Provider_Registry SHALL track request latency for each provider
2. THE Provider_Registry SHALL track success and error rates for each provider
3. THE Provider_Registry SHALL expose health metrics through the existing /health endpoint
4. WHEN a provider's error rate exceeds 50% over 10 requests, THE Provider_Registry SHALL mark it as Degraded
5. WHEN a provider fails 5 consecutive requests, THE Provider_Registry SHALL mark it as Unavailable
