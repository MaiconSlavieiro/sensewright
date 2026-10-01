"""LLM provider chain with fallback and circuit breaker."""

from __future__ import annotations

import logging
from typing import Any

from ..config import Settings
from .base import AllProvidersFailed, LLMError, LLMProvider, LLMResponse
from .limits import ProviderRateLimiter
from .providers import PROVIDER_CLASSES

logger = logging.getLogger(__name__)


class ProviderChain:
    """Ordered provider chain with circuit breaker.

    Tries providers in the configured chain order (filtered to available).
    On failure, increases per-provider failure count; at 3 failures,
    marks provider cold for 60s and skips it until the window elapses.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._providers: list[LLMProvider] = []
        self._provider_map: dict[str, LLMProvider] = {}
        self._chain_order: list[str] = []
        self._limiters: dict[str, ProviderRateLimiter] = {}
        self._build_chain()

    def _build_chain(self) -> None:
        self._providers = []
        self._provider_map = {}
        self._chain_order = []
        self._limiters = {}

        llm_config = self.settings.llm
        for name in llm_config.chain:
            provider_config = llm_config.providers.get(name)
            if not provider_config:
                logger.debug(f"Provider {name} in chain but not configured, skipping")
                continue

            # v0.5 follow-up A5: an explicit ``type`` lets a block use a generic
            # OpenAI-compatible endpoint (Groq/Cerebras/Ollama/...) without a
            # dedicated name. Falls back to the block name.
            provider_type = provider_config.type or name
            provider_class = PROVIDER_CLASSES.get(provider_type)
            if not provider_class:
                logger.warning(f"Unknown provider type: {provider_type} (block: {name})")
                continue

            provider = provider_class(provider_config)
            # v0.5 follow-up A5: a generic provider shares one class across block
            # names; key it (limiter/config/status) by its configured block name
            # instead of the class default.
            provider.name = name
            if provider.available:
                # v0.5 R2: purpose routing + auto-swap are provider-level knobs
                # fed from the shared ``[llm]`` config.
                try:
                    provider.task_models = dict(llm_config.task_models or {})
                    provider.auto_swap_models = bool(llm_config.auto_swap_models)
                except Exception:
                    pass
                self._providers.append(provider)
                self._provider_map[name] = provider
                self._chain_order.append(name)
                self._limiters[name] = ProviderRateLimiter(
                    rpm=provider_config.rpm or 0,
                    rpd=provider_config.rpd or 0,
                )
                logger.info(f"Provider {name} added to chain (model: {provider_config.model or provider_config.models})")
            else:
                logger.info(f"Provider {name} not available (disabled or no API key)")

    def rebuild(self, settings: Settings) -> None:
        """Rebuild the chain with new settings."""
        # Close old providers
        for provider in self._providers:
            if hasattr(provider, "close"):
                import asyncio
                try:
                    asyncio.create_task(provider.close())
                except Exception:
                    pass
        self.settings = settings
        self._build_chain()

    def get_provider(self, name: str) -> LLMProvider | None:
        return self._provider_map.get(name)

    def available_providers(self) -> list[LLMProvider]:
        return [p for p in self._providers if p.available and not self._is_cold(p)]

    def _is_cold(self, provider: LLMProvider) -> bool:
        if hasattr(provider, "_is_cold"):
            return provider._is_cold()
        return False

    def health(self) -> dict[str, Any]:
        """Chain health snapshot used by the scheduler backpressure (v0.5 R3)."""
        total = len(self._providers)
        warm = [p for p in self._providers if p.available and not self._is_cold(p)]
        return {
            "providers_total": total,
            "providers_warm": len(warm),
            "ratio": (len(warm) / total) if total else 0.0,
        }

    def backpressure_factor(self) -> float:
        """Idle-impulse throttle: ``1.0`` healthy, lower as providers cool.

        Returns ``0.0`` when no provider is warm, so the agency loop stops
        spending idle calls while the free tier is down (social keeps its
        reserve and is not throttled by this factor).
        """
        health = self.health()
        if health["providers_total"] == 0:
            return 1.0
        return float(health["ratio"])

    def set_discovered_models(self, name: str, models: list[str]) -> None:
        provider = self._provider_map.get(name)
        if provider is not None and hasattr(provider, "set_discovered_models"):
            provider.set_discovered_models(models)

    def model_pool(self) -> dict[str, list[str]]:
        """Configured + discovered model ids per provider (v0.5 R2 status)."""
        pool: dict[str, list[str]] = {}
        for name, provider in self._provider_map.items():
            config = self.settings.llm.providers.get(name)
            models: list[str] = []
            if config:
                if config.model:
                    models.append(config.model)
                for model in config.models:
                    if model and model not in models:
                        models.append(model)
            for model in getattr(provider, "discovered_models", []) or []:
                if model and model not in models:
                    models.append(model)
            pool[name] = models
        return pool

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        lang: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        prefer: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        reasoning_effort: str | None = None,
        purpose: str | None = None,
    ) -> LLMResponse:
        """Complete using the provider chain with fallback.

        Args:
            messages: Chat messages.
            lang: Target language (BCP-47).
            temperature: Sampling temperature.
            max_tokens: Max output tokens.
            prefer: Preferred provider name to try first.
            tools: Optional OpenAI-style tool schemas to expose to the model.
            reasoning_effort: Optional hidden-reasoning budget hint
                (none|minimal|low|medium|high).
            purpose: Task kind (``social``/``summary``/``chat``/...) used by the
                provider for model routing (v0.5 R2) and attempt logs (R1).

        Returns:
            LLMResponse from the first successful provider.

        Raises:
            AllProvidersFailed: If all providers fail.
        """
        # Determine provider order
        providers_to_try: list[LLMProvider] = []

        if prefer and prefer in self._provider_map:
            preferred = self._provider_map[prefer]
            if preferred.available and not self._is_cold(preferred):
                providers_to_try.append(preferred)

        for provider in self._providers:
            if provider not in providers_to_try and provider.available and not self._is_cold(provider):
                providers_to_try.append(provider)

        if not providers_to_try:
            raise AllProvidersFailed("No available providers in chain", self._chain_order)

        last_error: Exception | None = None
        failed: list[str] = []

        for provider in providers_to_try:
            limiter = self._limiters.get(provider.name)
            # v0.5 follow-up A2: peek (do not consume) before the call, then
            # record the number of *real* requests the provider made (it may try
            # several models per call). Keeps the local meter in step with the
            # provider's own quota.
            if limiter is not None and not limiter.has_capacity():
                last_error = LLMError(
                    f"Provider {provider.name} hit its RPM/RPD limit",
                    provider.name,
                    retryable=True,
                )
                failed.append(provider.name)
                logger.info(f"Provider {provider.name} rate-limited, skipping to next")
                continue
            try:
                logger.debug(f"Trying provider: {provider.name}")
                kwargs: dict[str, Any] = {
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if tools is not None:
                    kwargs["tools"] = tools
                if reasoning_effort is not None:
                    kwargs["reasoning_effort"] = reasoning_effort
                if purpose is not None:
                    kwargs["purpose"] = purpose
                response = await provider.complete(messages, **kwargs)
                logger.info(f"Provider {provider.name} succeeded")
                return response
            except LLMError as e:
                last_error = e
                failed.append(provider.name)
                logger.warning(f"Provider {provider.name} failed: {e}")
                if not e.retryable:
                    # Non-retryable error, don't try other providers for this request
                    break
                continue
            except Exception as e:
                last_error = e
                failed.append(provider.name)
                logger.error(f"Provider {provider.name} unexpected error: {e}")
                continue
            finally:
                if limiter is not None:
                    used = getattr(provider, "requests_last_call", None)
                    count = used if isinstance(used, int) and used > 0 else 1
                    limiter.record(count)

        raise AllProvidersFailed(
            f"All providers failed: {last_error}",
            failed,
        ) from last_error

    def primary_rpm(self) -> int | None:
        """RPM of the first available provider that declares one, else None.

        Used by the agency scheduler to pace background impulses against the
        real free-tier ceiling instead of a hardcoded default.
        """
        for provider in self._providers:
            config = self.settings.llm.providers.get(provider.name)
            if config and config.rpm:
                return int(config.rpm)
        return None

    def status(self) -> dict[str, Any]:
        return {
            "chain_order": self._chain_order,
            "providers": {name: provider.status() for name, provider in self._provider_map.items()},
            "limits": {name: limiter.snapshot() for name, limiter in self._limiters.items()},
            "health": self.health(),
            "pool": self.model_pool(),
        }

    async def close(self) -> None:
        for provider in self._providers:
            if hasattr(provider, "close"):
                await provider.close()


def build_chain(settings: Settings) -> ProviderChain:
    """Factory function to build a provider chain from settings."""
    return ProviderChain(settings)