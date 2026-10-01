"""LLM provider registry with auto-discovery."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from ..config import Settings
from .base import AllProvidersFailed, LLMProvider, LLMResponse
from .chain import ProviderChain, build_chain
from .providers.openai_compat import _is_free_model

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Registry of LLM providers with chain fallback and auto-discovery."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.chain: ProviderChain = build_chain(settings)
        self._lang = settings.lang
        # v0.5 R2: dynamic free-model discovery state. The first *automatic*
        # refresh waits one interval (so the first user turn never blocks on a
        # ``GET /models``); an on-demand refresh still runs after a failed call.
        self._last_refresh: float = time.monotonic()
        self._refresh_count: int = 0
        self._refresh_lock: asyncio.Lock | None = None
        # v0.5 follow-up A3: last on-demand (failure-triggered) refresh, throttled
        # so a failing chain cannot hammer ``GET /models`` on every request.
        self._last_forced_refresh: float = 0.0

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
        purpose: str | None = None,
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
            purpose: Task kind (``social``/``summary``/``chat``/...) used for
                model routing (v0.5 R2) and attempt logs (R1).

        Returns:
            LLMResponse from the first successful provider.

        Raises:
            AllProvidersFailed: If every provider fails (after one on-demand
                model refresh/retry, v0.5 R2).
        """
        from ..schemas import normalize_lang

        target_lang = normalize_lang(lang or self._lang)
        llm_config = self.settings.llm

        temp = temperature if temperature is not None else llm_config.temperature
        tokens = max_tokens if max_tokens is not None else llm_config.max_tokens
        effort = reasoning_effort if reasoning_effort is not None else llm_config.reasoning_effort

        await self.maybe_refresh()

        kwargs: dict[str, Any] = {
            "lang": target_lang,
            "temperature": temp,
            "max_tokens": tokens,
            "prefer": prefer,
            "tools": tools,
            "reasoning_effort": effort,
            "purpose": purpose,
        }
        try:
            return await self.chain.complete(messages, **kwargs)
        except AllProvidersFailed:
            # v0.5 R2: on-demand discovery when a whole call fails (e.g. every
            # configured model is rate-limited/cooling and a fresh free model
            # may exist). Retried at most once.
            # v0.5 follow-up A3: throttled (``refresh_on_failure_min_seconds``) so
            # a persistently failing chain refreshes the pool at most once per
            # window instead of on every request.
            if not self._failure_refresh_allowed():
                raise
            discovered = await self.refresh_models(force=True)
            if not discovered:
                raise
            logger.info("llm.pool refresh-on-failure discovered=%d; retrying call", discovered)
            return await self.chain.complete(messages, **kwargs)

    def _failure_refresh_allowed(self) -> bool:
        """Rate-limit the failure-triggered refresh (v0.5 follow-up A3)."""
        min_seconds = float(
            getattr(self.settings.llm, "refresh_on_failure_min_seconds", 60.0) or 0.0
        )
        now = time.monotonic()
        if min_seconds > 0 and self._last_forced_refresh and (now - self._last_forced_refresh) < min_seconds:
            logger.info(
                "llm.pool refresh-on-failure throttled (%.0fs since last)",
                now - self._last_forced_refresh,
            )
            return False
        self._last_forced_refresh = now
        return True

    async def _ensure_refresh_lock(self) -> asyncio.Lock:
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        return self._refresh_lock

    async def maybe_refresh(self) -> None:
        """Refresh the free-model pool when the configured interval elapsed."""
        minutes = float(getattr(self.settings.llm, "model_refresh_minutes", 30.0) or 0.0)
        if minutes <= 0:
            return
        now = time.monotonic()
        if self._last_refresh and (now - self._last_refresh) < minutes * 60.0:
            return
        try:
            await self.refresh_models()
        except Exception as exc:  # never let discovery break a completion
            logger.debug("model refresh failed: %s", exc)

    async def refresh_models(self, *, force: bool = False) -> int:
        """Discover free models for every provider; return how many were found.

        Never raises. When ``force`` is set the interval gate is bypassed (used
        for the on-demand retry after an all-providers failure).
        """
        lock = await self._ensure_refresh_lock()
        async with lock:
            self._last_refresh = time.monotonic()
            found = 0
            for name, provider in self.chain._provider_map.items():
                config = self.settings.llm.providers.get(name)
                # v0.5 follow-up A4: honour the per-provider discovery toggle.
                if config is not None and not config.discover_models:
                    continue
                try:
                    models = await self._filter_free_models(
                        name, await self._discover_provider_models(name, provider)
                    )
                except Exception as exc:
                    logger.debug("Auto-discovery failed for %s: %s", name, exc)
                    continue
                if not models:
                    continue
                self.chain.set_discovered_models(name, models)
                self._refresh_count += 1
                found += len(models)
                logger.info("llm.pool provider=%s models=%s", name, models[:8])
            return found

    @staticmethod
    async def _filter_free_models(name: str, models: list[str]) -> list[str]:
        """Keep only free-marked models (the pool is a free pool, v0.5 R2)."""
        if name == "opencode":
            return [m for m in models if m.endswith("-free")]
        if name == "openrouter":
            return [m for m in models if ":free" in m]
        return [m for m in models if _is_free_model(m)]

    def status(self) -> dict[str, Any]:
        """Return health snapshot of all providers and chain."""
        return {
            "lang": self._lang,
            "chain": self.chain.status(),
            "refresh": {
                "last_at": self._last_refresh or None,
                "count": self._refresh_count,
                "interval_minutes": getattr(self.settings.llm, "model_refresh_minutes", 30.0),
            },
        }

    async def auto_discover(self) -> dict[str, Any]:
        """Backwards-compatible discovery entry point used by admin routes."""
        pool = self.chain.model_pool()
        await self.refresh_models(force=True)
        refreshed = self.chain.model_pool()
        discovered = [
            {"provider": name, "models": models}
            for name, models in refreshed.items()
            if models and models != (pool.get(name) or [])
        ]
        return {"discovered": discovered}

    async def _discover_provider_models(self, name: str, provider: LLMProvider) -> list[str]:
        """Discover models for a specific provider."""
        config = self.settings.llm.providers.get(name)
        if not config:
            return []
        # v0.5 follow-up A6: local providers may have no key.
        if not config.api_key and not config.api_key_optional:
            return []
        # v0.5 follow-up A4: per-provider discovery toggle (Zen free tier 403s).
        if not config.discover_models:
            return []

        provider_type = config.type or name

        # OpenAI-compatible providers
        if provider_type == "openai_compat" or name in ("openrouter", "opencode", "deepseek", "openai"):
            base_url = config.base_url
            if name == "openrouter":
                base_url = base_url or "https://openrouter.ai/api/v1"
            elif name == "opencode":
                base_url = base_url or "https://opencode.ai/zen/v1"
            elif name == "deepseek":
                base_url = base_url or "https://api.deepseek.com/v1"
            elif not base_url:
                base_url = "https://api.openai.com/v1"

            if not base_url:
                return []

            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {"Authorization": f"Bearer {config.api_key}"}
                if name == "openrouter":
                    headers.update({"HTTP-Referer": "https://github.com/sims-sense", "X-Title": "Sensewright"})
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