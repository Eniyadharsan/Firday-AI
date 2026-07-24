"""Multi-provider AI integration module for FRIDAY.

This module provides a unified abstraction layer for integrating multiple AI providers
into FRIDAY. It enables seamless switching between providers (OpenAI, Anthropic, Gemini,
DeepSeek, Grok, Ollama, OpenRouter, Cerebras) while maintaining a consistent interface.

The module implements an adapter pattern where each provider has its own adapter that
translates FRIDAY's unified message format to the provider's native API format.

Core Components:
    Provider_Adapter - Abstract base class for all provider adapters
    Provider_Registry - Singleton registry managing all provider adapters (to be implemented)
    Unified_AI_Engine - Central engine for AI provider communication (to be implemented)
    Failover_Controller - Automatic failover management (to be implemented)
    API_Key_Store - Secure API key storage (to be implemented)

Data Models:
    ProviderStatus - Provider operational status enum
    ProviderType - Supported AI provider types enum
    ProviderCapabilities - Provider capability description
    GenerateResponse - Unified response format
    ProviderHealth - Health metrics for a provider
    ProviderMetrics - Request tracking metrics
    ProviderConfig - Configuration for a provider
    ModelInfo - Information about an available model
    ActiveProviderState - Current active provider state
    FridayMessage - Internal message format
    ConversationContext - Context for conversations
    StreamChunk - Streaming response chunk
    ToolCallRequest - Parsed tool call
    ProviderError - Provider error with retry info
    ModelManagerResponse - Response for Model Manager UI
    ActiveBadgeResponse - Response for Active Model Badge
    HealthResponse - Extended health response with provider metrics

Utility Functions:
    get_status_color - Map ProviderStatus to display color
"""

from __future__ import annotations

# Data models
from friday.modules.providers.models import (
    ActiveBadgeResponse,
    ActiveProviderState,
    ConversationContext,
    FridayMessage,
    GenerateResponse,
    HealthResponse,
    ModelInfo,
    ModelManagerResponse,
    ProviderCapabilities,
    ProviderConfig,
    ProviderError,
    ProviderHealth,
    ProviderMetrics,
    ProviderStatus,
    ProviderType,
    StreamChunk,
    ToolCallRequest,
    get_status_color,
)

# Core components
from friday.modules.providers.base import Provider_Adapter
from friday.modules.providers.key_store import API_Key_Store
from friday.modules.providers.registry import Provider_Registry
from friday.modules.providers.failover import Failover_Controller
from friday.modules.providers.engine import (
    Unified_AI_Engine,
    ToolSelectionResult,
    StreamingSession,
    StreamingInterruptedError,
    MarkdownPreserver,
    MarkdownState,
    streaming_session,
)

# Conversation history management
from friday.modules.providers.conversation import ConversationHistoryManager

# Provider adapters
from friday.modules.providers.adapters.openai_adapter import OpenAI_Adapter

__all__: list[str] = [
    # Data models
    "ProviderStatus",
    "ProviderType",
    "ProviderCapabilities",
    "GenerateResponse",
    "ProviderHealth",
    "ProviderMetrics",
    "ProviderConfig",
    "ModelInfo",
    "ActiveProviderState",
    "FridayMessage",
    "ConversationContext",
    "StreamChunk",
    "ToolCallRequest",
    "ProviderError",
    "ModelManagerResponse",
    "ActiveBadgeResponse",
    "HealthResponse",
    # Utility functions
    "get_status_color",
    # Core components
    "Provider_Adapter",
    "API_Key_Store",
    "Provider_Registry",
    # Provider adapters
    "OpenAI_Adapter",
    # Failover
    "Failover_Controller",
    # Engine
    "Unified_AI_Engine",
    "ToolSelectionResult",
    # Streaming interruption handling
    "StreamingSession",
    "StreamingInterruptedError",
    "MarkdownPreserver",
    "MarkdownState",
    "streaming_session",
    # Conversation history management
    "ConversationHistoryManager",
]
