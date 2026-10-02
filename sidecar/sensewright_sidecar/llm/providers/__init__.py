"""Provider registry and factory."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .base import GeminiProvider, OpenAICompatProvider, Provider

#: Providers that use the OpenAI-compatible endpoint.
_OPENAI_COMPAT = ("openrouter", "opencode", "groq", "deepseek", "ollama")

#: Providers with a bespoke client.
_SPECIAL = {
    "gemini": GeminiProvider,
}


def build_provider(name: str, config: Dict[str, Any]) -> Optional[Provider]:
    """Construct a provider client from a config dict, or None for unknown ids."""
    name = (name or "").lower()
    if name in _SPECIAL:
        provider = _SPECIAL[name](config)
    elif name in _OPENAI_COMPAT:
        provider = OpenAICompatProvider(config)
    else:
        return None
    # Tag the instance so provider-specific request shaping can key off it.
    provider.name = name
    return provider


def available_provider_names() -> tuple:
    return tuple(sorted(set(_OPENAI_COMPAT) | set(_SPECIAL)))
