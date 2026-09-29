"""LLM provider registry with auto-discovery."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import Settings
from .base import LLMProvider, LLMResponse
from .chain import ProviderChain, build_chain

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Registry of LLM providers with chain fallback and auto-discovery."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.chain: ProviderChain = build_chain(settings)
        self._lang = settings.lang

    def configure(self, settings: Settings) -> None:
        """Reconfigure the registry with new settings."""
        self.settings = settings
        self._lang = settings.lang
        self.chain.rebuild(settings)

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        lang: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        prefer: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        """Complete a chat using the provider chain.

        Args:
            messages: Chat messages.
            lang: Target language (BCP-47). Uses registry default if not provided.
            temperature: Sampling temperature.
            max_tokens: Max output tokens.
            prefer: Preferred provider name.
            tools: Optional OpenAI-style tool schemas to expose to the model.
            reasoning_effort: Hidden-reasoning budget hint
                (none|minimal|low|medium|high). Falls back to
                ``[llm] reasoning_effort`` when omitted.

        Returns:
            LLMResponse from the first successful provider.
        """
        from ..schemas import normalize_lang

        target_lang = normalize_lang(lang or self._lang)
        llm_config = self.settings.llm

        temp = temperature if temperature is not None else llm_config.temperature
        tokens = max_tokens if max_tokens is not None else llm_config.max_tokens
        effort = reasoning_effort if reasoning_effort is not None else llm_config.reasoning_effort

        return await self.chain.complete(
            messages,
            lang=target_lang,
            temperature=temp,
            max_tokens=tokens,
            prefer=prefer,
            tools=tools,
            reasoning_effort=effort,
        )

    def status(self) -> dict[str, Any]:
        """Return health snapshot of all providers and chain."""
        return {
            "lang": self._lang,
            "chain": self.chain.status(),
        }

    async def auto_discover(self) -> dict[str, Any]:
        """Best-effort model discovery via GET /models endpoints.

        Never raises; returns empty list on any error.
        """
        discovered: list[dict[str, Any]] = []

        for name, provider in self.chain._provider_map.items():
            try:
                models = await self._discover_provider_models(name, provider)
                if models:
                    discovered.append({"provider": name, "models": models})
            except Exception as e:
                logger.debug(f"Auto-discovery failed for {name}: {e}")

        return {"discovered": discovered}

    async def _discover_provider_models(self, name: str, provider: LLMProvider) -> list[str]:
        """Discover models for a specific provider."""
        config = self.settings.llm.providers.get(name)
        if not config or not config.api_key:
            return []

        # OpenAI-compatible providers
        if name in ("openrouter", "opencode", "deepseek", "openai", "openai_compat"):
            base_url = config.base_url
            if name == "openrouter":
                base_url = base_url or "https://openrouter.ai/api/v1"
            elif name == "opencode":
                base_url = base_url or "https://opencode.ai/zen/v1"
            elif name == "deepseek":
                base_url = base_url or "https://api.deepseek.com/v1"
            elif name in ("openai", "openai_compat"):
                base_url = base_url or "https://api.openai.com/v1"

            if not base_url:
                return []

            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {"Authorization": f"Bearer {config.api_key}"}
                if name == "openrouter":
                    headers.update({"HTTP-Referer": "https://github.com/sims-sense", "X-Title": "SimsSense"})
                resp = await client.get(f"{base_url.rstrip('/')}/models", headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

        # Gemini (key in header so it never appears in request logs)
        if name == "gemini":
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    headers={"x-goog-api-key": config.api_key},
                )
                resp.raise_for_status()
                data = resp.json()
                return [m.get("name", "").replace("models/", "") for m in data.get("models", []) if m.get("name")]

        return []

    async def close(self) -> None:
        await self.chain.close()


def build_registry(settings: Settings) -> ProviderRegistry:
    """Factory function to build a provider registry from settings."""
    return ProviderRegistry(settings)