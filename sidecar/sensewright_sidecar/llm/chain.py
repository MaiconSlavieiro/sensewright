"""ProviderChain — resilient multi-provider execution.

Implements REQ-LLM-01/02: triple rate limiting (RPM/RPD/TPM), circuit breaker
(cold for 60s after 3 consecutive failures) and per-model cooldown (120s after
2 failures) with automatic swap to the next candidate. On success the limiter's
TPM estimate is reconciled with the provider's reported ``usage.total_tokens``.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

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
#: A model that answers HTTP 200 with unusable output (e.g. a reasoning model
#: that spends its whole token budget "thinking" and never emits the requested
#: JSON) is benched so we stop paying for the same wasted call every pulse.
#: Configurable via ``llm.invalid_output_cooldown_seconds`` (4.4).
INVALID_OUTPUT_COOLDOWN_SECONDS = 120.0
#: When every route for a purpose fails, back that purpose off to the
#: deterministic fallback for this long instead of retrying every tick (4.4).
PURPOSE_COOLDOWN_SECONDS = 120.0


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
        self._model_failures: Dict[Tuple[str, str], int] = {}
        self._model_cooldown_until: Dict[Tuple[str, str], float] = {}
        self._invalid_cooldown_until: Dict[Tuple[str, str], float] = {}
        self._purpose_cold_until: Dict[str, float] = {}
        llm_cfg = config.raw().get("llm", {}) if hasattr(config, "raw") else {}
        try:
            self._invalid_cooldown_seconds = float(
                llm_cfg.get("invalid_output_cooldown_seconds", INVALID_OUTPUT_COOLDOWN_SECONDS)
            )
        except (TypeError, ValueError):
            self._invalid_cooldown_seconds = INVALID_OUTPUT_COOLDOWN_SECONDS
        try:
            self._purpose_cooldown_seconds = float(
                llm_cfg.get("purpose_cooldown_seconds", PURPOSE_COOLDOWN_SECONDS)
            )
        except (TypeError, ValueError):
            self._purpose_cooldown_seconds = PURPOSE_COOLDOWN_SECONDS
        #: Per-model cooldown after repeated failures (configurable, S-H04).
        try:
            self._model_cooldown_seconds = float(
                llm_cfg.get("model_cooldown_seconds", MODEL_COOLDOWN_SECONDS)
            )
        except (TypeError, ValueError):
            self._model_cooldown_seconds = MODEL_COOLDOWN_SECONDS

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

    def reload_provider(self, name: str) -> None:
        """Drop cached client/limiter/circuit state so new credentials apply (4.2)."""
        with self._lock:
            self._clients.pop(name, None)
            self._limiters.pop(name, None)
            self._consecutive_failures.pop(name, None)
            self._circuit_cold_until.pop(name, None)
            # Also clear per-model state keyed by (provider, model), otherwise a
            # benched/unusable model stays benched after credentials are edited
            # (S-H04).
            for key in [k for k in self._model_failures if k[0] == name]:
                self._model_failures.pop(key, None)
            for key in [k for k in self._model_cooldown_until if k[0] == name]:
                self._model_cooldown_until.pop(key, None)
            for key in [k for k in self._invalid_cooldown_until if k[0] == name]:
                self._invalid_cooldown_until.pop(key, None)

    def _is_cold(self, name: str) -> bool:
        with self._lock:
            until = self._circuit_cold_until.get(name, 0.0)
            return time.time() < until

    def _model_cooling(self, name: str, model: str) -> bool:
        with self._lock:
            until = self._model_cooldown_until.get((name, model), 0.0)
            return time.time() < until

    def _invalid_cooling(self, name: str, model: str) -> bool:
        with self._lock:
            until = self._invalid_cooldown_until.get((name, model), 0.0)
            return time.time() < until

    def _purpose_cooling(self, purpose_id: str) -> bool:
        with self._lock:
            return time.time() < self._purpose_cold_until.get(purpose_id, 0.0)

    def _record_purpose_failure(self, purpose_id: str) -> None:
        with self._lock:
            self._purpose_cold_until[purpose_id] = time.time() + self._purpose_cooldown_seconds

    def _record_purpose_success(self, purpose_id: str) -> None:
        with self._lock:
            self._purpose_cold_until.pop(purpose_id, None)

    def _record_invalid(self, name: str, model: str) -> None:
        with self._lock:
            self._invalid_cooldown_until[(name, model)] = (
                time.time() + self._invalid_cooldown_seconds
            )

    def _record_failure(self, name: str, model: str) -> None:
        with self._lock:
            self._consecutive_failures[name] = self._consecutive_failures.get(name, 0) + 1
            if self._consecutive_failures[name] >= CIRCUIT_BREAK_FAILURES:
                self._circuit_cold_until[name] = time.time() + CIRCUIT_COOLDOWN_SECONDS
                self._consecutive_failures[name] = 0
                logger.warning("circuit breaker opened for provider %s (60s)", name)

            # Per-model cooldown after repeated failures (REQ-LLM-02).
            key = (name, model)
            self._model_failures[key] = self._model_failures.get(key, 0) + 1
            if self._model_failures[key] >= MODEL_COOLDOWN_FAILURES:
                self._model_cooldown_until[key] = time.time() + self._model_cooldown_seconds
                self._model_failures[key] = 0
                logger.warning(
                    "model %s/%s cooling for %.0fs", name, model, self._model_cooldown_seconds,
                )

    def _record_success(self, name: str, model: Optional[str] = None) -> None:
        with self._lock:
            self._consecutive_failures[name] = 0
            self._circuit_cold_until.pop(name, None)
            if model is not None:
                self._model_failures.pop((name, model), None)
                self._model_cooldown_until.pop((name, model), None)

    def run(
        self,
        purpose_id: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        timeout: float,
        validator: Optional[Callable[[ProviderResponse], bool]] = None,
    ) -> Tuple[Optional[ProviderResponse], Optional[str], Optional[str]]:
        """Attempt each candidate route in order; return (response, provider, model).

        Returns ``(None, None, None)`` when every candidate fails or is skipped.

        ``validator`` (optional) is applied to a 200 response; when it returns
        False the candidate is benched and the next route is tried. This lets the
        caller reject HTTP-successful-but-unusable generations (e.g. a reasoning
        model that never emits JSON) instead of silently accepting them.
        """
        # Per-purpose breaker: after every route failed, skip the whole chain for
        # a cooldown instead of re-paying the same failing calls every tick (4.4).
        if self._purpose_cooling(purpose_id):
            logger.info("purpose %s cooling; using fallback", purpose_id)
            return None, None, None

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
            if self._invalid_cooling(name, model):
                last_error = "model {}/{} benched (unusable output)".format(name, model)
                continue

            client = self._client(name)
            if client is None:
                last_error = "unknown provider {}".format(name)
                continue

            limiter = self._limiter(name)
            prompt_text = self._messages_to_text(messages)
            est_tokens = estimate_tokens(prompt_text) + max_tokens
            # Atomic check-and-record: concurrent HTTP threads must not both pass
            # the capacity check before either records (3.6).
            if not limiter.try_accept_and_record(est_tokens):
                last_error = "provider {} rate-limited (RPM/RPD/TPM)".format(name)
                continue

            # Dispatch.
            try:
                response = client.complete(
                    messages, model, max_tokens=max_tokens,
                    temperature=temperature, timeout=timeout,
                )
            except LLMRateLimited as exc:
                last_error = str(exc)
                limiter.release_reservation(est_tokens)
                self._record_failure(name, model)
                continue
            except LLMError as exc:
                last_error = str(exc)
                limiter.release_reservation(est_tokens)
                self._record_failure(name, model)
                continue
            except Exception as exc:  # noqa: BLE001 - defensive: never crash the chain
                last_error = "unexpected error from {}: {}".format(name, exc)
                logger.exception("chain unexpected error")
                limiter.release_reservation(est_tokens)
                self._record_failure(name, model)
                continue

            # Success: reconcile tokens and reset failures.
            limiter.settle_reservation(est_tokens, response.total_tokens or est_tokens)
            self._record_success(name, model)
            if validator is not None and not validator(response):
                self._record_invalid(name, model)
                last_error = "provider {} model {} returned unusable output".format(name, model)
                logger.warning(
                    "route rejected provider=%s model=%s (unusable output; benched %.0fs)",
                    name, model, self._invalid_cooldown_seconds,
                )
                continue
            self._record_purpose_success(purpose_id)
            return response, name, model

        logger.warning("purpose %s: all routes failed (%s)", purpose_id, last_error)
        self._record_purpose_failure(purpose_id)
        return None, None, None

    @staticmethod
    def _messages_to_text(messages: List[Dict[str, str]]) -> str:
        return "\n".join(m.get("content", "") for m in messages)

    def status(self) -> Dict[str, object]:
        """Snapshot of limiter states for the Web Studio."""
        with self._lock:
            now = time.time()
            cooling_purposes = [
                purpose for purpose, until in self._purpose_cold_until.items() if until > now
            ]
        return {
            "limiters": {
                name: limiter.snapshot() for name, limiter in self._limiters.items()
            },
            "purpose_cooldowns": cooling_purposes,
            "invalid_output_cooldown_seconds": self._invalid_cooldown_seconds,
            "purpose_cooldown_seconds": self._purpose_cooldown_seconds,
        }
