"""Provider adapters for multi-provider AI integration.

This module contains all concrete Provider_Adapter implementations for
different AI providers (OpenAI, Anthropic, Gemini, etc.).

Each adapter translates FRIDAY's unified message format to the provider's
native API format and handles response parsing back to FRIDAY format.

Available Adapters:
    OpenAI_Adapter - Adapter for OpenAI ChatGPT models (GPT-4o, GPT-4-turbo, GPT-3.5-turbo)
    Anthropic_Adapter - Adapter for Anthropic Claude models (Opus, Sonnet, Haiku)
    Gemini_Adapter - Adapter for Google Gemini models (gemini-1.5-pro, gemini-1.5-flash, gemini-pro)
    Ollama_Adapter - Adapter for local Ollama models (llama3, mistral, etc.)
    Cerebras_Adapter - Adapter for Cerebras models (llama-4-scout, llama3.1, qwen-3)
    DeepSeek_Adapter - Adapter for DeepSeek models (deepseek-chat, deepseek-coder)
    OpenRouter_Adapter - Adapter for OpenRouter multi-model API
    Grok_Adapter - Adapter for xAI Grok models (grok-beta, grok-2, grok-2-mini)
"""

from __future__ import annotations

from friday.modules.providers.adapters.openai_adapter import OpenAI_Adapter
from friday.modules.providers.adapters.anthropic_adapter import Anthropic_Adapter
from friday.modules.providers.adapters.gemini_adapter import Gemini_Adapter
from friday.modules.providers.adapters.ollama_adapter import Ollama_Adapter
from friday.modules.providers.adapters.cerebras_adapter import Cerebras_Adapter
from friday.modules.providers.adapters.deepseek_adapter import DeepSeek_Adapter
from friday.modules.providers.adapters.openrouter_adapter import OpenRouter_Adapter
from friday.modules.providers.adapters.grok_adapter import Grok_Adapter

__all__: list[str] = [
    "OpenAI_Adapter",
    "Anthropic_Adapter",
    "Gemini_Adapter",
    "Ollama_Adapter",
    "Cerebras_Adapter",
    "DeepSeek_Adapter",
    "OpenRouter_Adapter",
    "Grok_Adapter",
]
