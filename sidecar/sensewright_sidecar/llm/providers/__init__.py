"""LLM provider implementations."""

from __future__ import annotations

from .deepseek import DeepSeekProvider
from .gemini import GeminiProvider
from .openai_compat import OpenAICompatProvider, OpenCodeZenProvider
from .openrouter import OpenRouterProvider

PROVIDER_CLASSES: dict[str, type] = {
    "gemini": GeminiProvider,
    "openrouter": OpenRouterProvider,
    "opencode": OpenCodeZenProvider,
    "deepseek": DeepSeekProvider,
    "openai": OpenAICompatProvider,
    "openai_compat": OpenAICompatProvider,
}

__all__ = [
    "PROVIDER_CLASSES",
    "DeepSeekProvider",
    "GeminiProvider",
    "OpenAICompatProvider",
    "OpenCodeZenProvider",
    "OpenRouterProvider",
]