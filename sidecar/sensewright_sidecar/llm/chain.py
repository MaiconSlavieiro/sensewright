"""ProviderChain — resilient multi-provider execution.

Implements REQ-LLM-01/02: triple rate limiting (RPM/RPD/TPM), circuit breaker
(cold for 60s after 3 consecutive failures) and per-model cooldown (120s after
2 failures) with automatic swap to the next candidate. On success the limiter's
TPM estimate is reconciled with the provider's reported ``usage.total_tokens``.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Tuple

from ..config import Config
from ..observability.logging import get_logger
from .base import (
    LLMError, LLMRateLimited, LLMResult, ProviderResponse,
)
from .limits import ProviderRateLimiter, estimate_tokens
from .providers import build_provider
from .providers.base import Provider
from .router import ModelRouter, RouteCandidate

logger = get_logger("llm.chain")

CIRCUIT_BREAK_FAILURES = 3
CIRCUIT_COOLDOWN_SECONDS = 60.0
MODEL_COOLDOWN_FAILURES = 2
MODEL_COOLDOWN_SECONDS = 120.0


class ProviderChain:
    """Executes a routed purpose across a chain of providers with failover."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._router = ModelRouter(config)
        self._lock = threading.Lock()
        self._limiters: Dict[str, ProviderRateLimiter] = {}
        self._clients: Dict[str, Provider] = {}
        self._consecutive_failures: Dict[str, int] = {}
        self._circuit_cold_until: Dict[str, float] = {}
        self._model_cooldown_until: Dict[Tuple[str, str], float] = {}

    # ── helpers ──────────────────────────────────────────────────────────
    def _limiter(self, name: str) -> ProviderRateLimiter:
        if name not in self._limiters:
            cfg = self._config.provider(name)
            self._limiters[name] = ProviderRateLimiter(
                rpm=cfg.get("rpm", 0), rpd=cfg.get("rpd", 0), tpm=cfg.get("tpm", 0),
            )
        return self._limiters[name]

    def _client(self, name: str) -> Optional[Provider]:
        if name not in self._clients:
            self._clients[name] = build_provider(name, self._config.provider(name))
        return self._clients[name]

    def _is_cold(self, name: str) -> bool:
        until = self._circuit_cold_until.get(name, 0.0)
        return time.time() < until

    def _model_cooling(self, name: str, model: str) -> bool:
        until = self._model_cooldown_until.get((name, model), 0.0)
        return time.time() < until

    def _record_failure(self, name: str, model: str) -> None:
        with self._lock:
            self._consecutive_failures[name] = self._consecutive_failures.get(name, 0) + 1
            if self._consecutive_failures[name] >= CIRCUIT_BREAK_FAILURES:
                self._circuit_cold_until[name] = time.time() + CIRCUIT_COOLDOWN_SECONDS
                self._consecutive_failures[name] = 0
                logger.warning("circuit breaker opened for provider %s (60s)", name)

    def _record_success(self, name: str) -> None:
        with self._lock:
            self._consecutive_failures[name] = 0
            self._circuit_cold_until.pop(name, None)

    def run(
        self,
        purpose_id: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> Tuple[Optional[ProviderResponse], Optional[str], Optional[str]]:
        """Attempt each candidate route in order; return (response, provider, model).

        Returns ``(None, None, None)`` when every candidate fails or is skipped.
        """
        candidates = self._router.plan(purpose_id)
        last_error: Optional[str] = None

        for candidate in candidates:
            name, model = candidate.provider, candidate.model
            if self._is_cold(name):
                last_error = "provider {} circuit-open".format(name)
                continue
            if self._model_cooling(name, model):
                last_error = "model {}/{} cooling".format(name, model)
                continue

            client = self._client(name)
            if client is None:
                last_error = "unknown provider {}".format(name)
                continue

            limiter = self._limiter(name)
            prompt_text = self._messages_to_text(messages)
            est_tokens = estimate_tokens(prompt_text) + max_tokens
            if not limiter.can_accept(est_tokens):
                last_error = "provider {} rate-limited (RPM/RPD/TPM)".format(name)
                continue

            # Dispatch.
            limiter.record_request()
            try:
                response = client.complete(
                    messages, model, max_tokens=max_tokens,
                    temperature=temperature, timeout=timeout,
                )
            except LLMRateLimited as exc:
                last_error = str(exc)
                self._record_failure(name, model)
                continue
            except LLMError as exc:
                last_error = str(exc)
                self._record_failure(name, model)
                continue
            except Exception as exc:  # noqa: BLE001 - defensive: never crash the chain
                last_error = "unexpected error from {}: {}".format(name, exc)
                logger.exception("chain unexpected error")
                self._record_failure(name, model)
                continue

            # Success: reconcile tokens and reset failures.
            limiter.record_tokens(response.total_tokens or est_tokens)
            self._record_success(name)
            return response, name, model

        logger.warning("purpose %s: all routes failed (%s)", purpose_id, last_error)
        return None, None, None

    @staticmethod
    def _messages_to_text(messages: List[Dict[str, str]]) -> str:
        return "\n".join(m.get("content", "") for m in messages)

    def status(self) -> Dict[str, object]:
        """Snapshot of limiter states for the Web Studio."""
        return {
            name: limiter.snapshot() for name, limiter in self._limiters.items()
        }
