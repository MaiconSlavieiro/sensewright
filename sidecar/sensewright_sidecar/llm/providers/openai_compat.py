"""OpenAI-compatible chat completions provider base class."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from ...config import ProviderConfig
from ..base import LLMError, LLMResponse, LLMToolCall, normalize_reasoning_effort

logger = logging.getLogger(__name__)

# v0.5 R2: purposes whose reply is short (one line / one summary). For these,
# fast, cheap models are tried before heavy reasoning models, which would
# otherwise burn the tiny output budget. Never removes a model — only reorders.
SHORT_TASK_PURPOSES = frozenset({"social", "summary"})
_FAST_MODEL_TOKENS = ("flash", "lightning", "mimo", "mini", "8b")
# Heavy models are pushed after the others for short tasks (but kept usable).
_SLOW_MODEL_TOKENS = ("ultra", "super", "550b", "550")


def _is_free_model(model: str) -> bool:
    """True when a model id marks itself as free (``:free`` or ``-free``).

    OpenRouter uses the ``:free`` suffix; OpenCode Zen uses ``-free``. This is
    the billing guard used by the ``free_only`` filter.
    """
    text = str(model or "").lower()
    return ":free" in text or text.endswith("-free")


def _is_fast_model(model: str) -> bool:
    text = str(model or "").lower()
    return any(token in text for token in _FAST_MODEL_TOKENS)


def _is_slow_model(model: str) -> bool:
    text = str(model or "").lower()
    return any(token in text for token in _SLOW_MODEL_TOKENS)


def _is_auth_error(error: LLMError) -> bool:
    """True only for key-level auth failures (401).

    A 403 is treated as model-level (e.g. a per-model access policy) so the
    provider still tries its next model instead of aborting the whole provider.
    """
    return getattr(error, "status", None) == 401


class OpenAICompatProvider:
    """Base class for OpenAI-compatible API providers.

    Implements the standard chat completions endpoint:
    POST {base_url}/chat/completions
    Authorization: Bearer {api_key}
    """

    name: str = "openai_compat"
    _client: httpx.AsyncClient | None = None

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._failure_count = 0
        self._cold_until: float = 0.0
        # v0.5 R1: per-model consecutive failures + cool-down deadlines.
        self._model_failures: dict[str, int] = {}
        self._model_cold_until: dict[str, float] = {}
        # v0.5 R2: populated by the chain/registry (purpose routing + discovery).
        self.task_models: dict[str, list[str]] = {}
        self.auto_swap_models: bool = True
        self.discovered_models: list[str] = list(config.discovered_models or [])
        # v0.5 follow-up A2: number of real HTTP requests made during the last
        # ``complete`` call (one per model attempt), read by the chain to meter
        # the provider quota accurately.
        self._requests_last_call: int = 0

    @property
    def available(self) -> bool:
        # v0.5 follow-up A6: a local endpoint (Ollama, LM Studio, ...) may run
        # without any API key; ``api_key_optional`` makes it available.
        if not self.config.enabled:
            return False
        return bool(self.config.api_key) or bool(self.config.api_key_optional)

    @property
    def requests_last_call(self) -> int:
        return self._requests_last_call

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            base_url = self.config.base_url or "https://api.openai.com/v1"
            headers: dict[str, str] = {}
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _is_cold(self) -> bool:
        import time
        return time.time() < self._cold_until

    def _mark_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= 3:
            import time
            self._cold_until = time.time() + 60.0
            logger.warning(f"Provider {self.name} marked cold for 60s after {self._failure_count} failures")

    def _mark_success(self) -> None:
        self._failure_count = 0
        self._cold_until = 0.0

    # ── v0.5 R1: per-model cool-down ──────────────────────────────────
    def _model_is_cold(self, model: str) -> bool:
        return time.time() < self._model_cold_until.get(model, 0.0)

    def _mark_model_failure(self, model: str) -> None:
        """Count a consecutive model failure; retire the model past the threshold."""
        count = self._model_failures.get(model, 0) + 1
        self._model_failures[model] = count
        threshold = max(1, int(getattr(self.config, "model_failure_threshold", 2) or 2))
        if count >= threshold:
            cooldown = max(0.0, float(getattr(self.config, "model_cooldown_seconds", 120.0) or 0.0))
            if cooldown > 0:
                self._model_cold_until[model] = time.time() + cooldown
            logger.warning(
                "llm.model_cooldown provider=%s model=%s failures=%d cooldown_s=%.0f",
                self.name,
                model,
                count,
                cooldown,
            )

    def _mark_model_success(self, model: str) -> None:
        self._model_failures.pop(model, None)
        self._model_cold_until.pop(model, None)

    def model_cooldowns(self) -> dict[str, float]:
        """Remaining cool-down seconds per retired model (only live ones)."""
        now = time.time()
        out: dict[str, float] = {}
        for model, until in self._model_cold_until.items():
            remaining = until - now
            if remaining > 0:
                out[model] = round(remaining, 1)
        return out

    def model_status(self) -> dict[str, Any]:
        return {
            "cooling": sorted(self.model_cooldowns().keys()),
            "cooldowns": self.model_cooldowns(),
            "failures": dict(self._model_failures),
            "discovered": list(self.discovered_models),
        }

    def set_discovered_models(self, models: list[str]) -> None:
        """Replace the dynamically-discovered free model pool (v0.5 R2)."""
        self.discovered_models = [model for model in (models or []) if model]

    def _candidate_models(self, purpose: str | None = None) -> list[str]:
        """Ordered model list: explicit ``model``, ``models``, then discovered.

        Trying several models within one provider keeps a reply coming when a
        single free model is rate-limited or briefly unavailable, before the
        chain has to fall back to the next provider.

        When ``free_only`` is set, any model not marked free (``:free`` /
        ``-free``) is dropped, so a misconfigured list can never trigger billing.

        v0.5 R2: models are reordered for short purposes (``social``/``summary``)
        with fast models first, unless an explicit ``[llm.task_models]`` override
        exists for the purpose. Models are never removed by the heuristic.
        """
        models: list[str] = []
        if self.config.model:
            models.append(self.config.model)
        for model in self.config.models:
            if model and model not in models:
                models.append(model)
        for model in self.discovered_models:
            if model and model not in models:
                models.append(model)
        if self.config.free_only:
            models = [model for model in models if _is_free_model(model)]
        if not models:
            return [] if self.config.free_only else ["gpt-3.5-turbo"]
        return self._order_for_purpose(models, purpose)

    def _order_for_purpose(self, models: list[str], purpose: str | None) -> list[str]:
        if not purpose:
            return models
        override = list((self.task_models or {}).get(purpose) or [])
        if override:
            head = [model for model in models if model in override]
            rest = [model for model in models if model not in head]
            return head + rest
        if purpose in SHORT_TASK_PURPOSES:
            fast = [model for model in models if _is_fast_model(model) and not _is_slow_model(model)]
            fast_set = set(fast)
            others = [model for model in models if model not in fast_set]
            return fast + others
        return models

    def _select_models(self, purpose: str | None) -> list[str]:
        """Candidates minus cooled models, with an optional auto-swap log."""
        candidates = self._candidate_models(purpose)
        usable = [model for model in candidates if not self._model_is_cold(model)]
        if len(usable) == len(candidates):
            return candidates
        cooled = [model for model in candidates if self._model_is_cold(model)]
        if self.auto_swap_models:
            discovered = [
                model
                for model in self.discovered_models
                if model in usable and model not in self.config.models
            ]
            if discovered and cooled:
                logger.info(
                    "llm.model_swap provider=%s from=%s to=%s",
                    self.name,
                    cooled[0],
                    discovered[0],
                )
        # Never go fully silent: if every model is cooled, use the list anyway.
        return usable or candidates

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        reasoning_effort: str | None = None,
        purpose: str | None = None,
    ) -> LLMResponse:
        self._requests_last_call = 0
        if not self.available:
            raise LLMError(f"Provider {self.name} not available (disabled or no API key)", self.name, retryable=False)

        if self._is_cold():
            raise LLMError(f"Provider {self.name} is in cool-down", self.name, retryable=True)

        models = self._select_models(purpose)
        if not models:
            raise LLMError(
                f"Provider {self.name} has no usable models (free_only guard)",
                self.name,
                retryable=True,
            )
        last_error: LLMError | None = None

        for index, model in enumerate(models):
            try:
                response = await self._complete_with_model(
                    model,
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                    reasoning_effort=reasoning_effort,
                    purpose=purpose,
                    attempt=index + 1,
                    total=len(models),
                )
                self._mark_model_success(model)
                return response
            except LLMError as e:
                last_error = e
                if _is_auth_error(e):
                    # A bad/expired key or missing permission is provider-wide;
                    # another model on the same key cannot fix it.
                    self._mark_failure()
                    raise
                self._mark_model_failure(model)
                if index < len(models) - 1:
                    logger.warning(f"Provider {self.name} model {model} failed: {e}; trying next model")

        self._mark_failure()
        if last_error is not None:
            raise last_error
        raise LLMError(f"Provider {self.name} produced no response", self.name)

    @staticmethod
    def _log_attempt(
        purpose: str | None,
        provider: str,
        model: str,
        attempt: int,
        total: int,
        outcome: str,
        latency_ms: float,
        finish: str | None = None,
    ) -> None:
        logger.info(
            "llm.attempt purpose=%s provider=%s model=%s attempt=%d/%d outcome=%s latency_ms=%.0f finish=%s",
            purpose or "-",
            provider,
            model,
            attempt,
            total,
            outcome,
            latency_ms,
            finish or "-",
        )

    async def _complete_with_model(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        reasoning_effort: str | None = None,
        purpose: str | None = None,
        attempt: int = 1,
        total: int = 1,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        # Merge any extra parameters. ``extra_body`` is the explicit v0.4 P2
        # passthrough and wins over the legacy ``extra`` on conflicts.
        if self.config.extra:
            payload.update(self.config.extra)
        if self.config.extra_body:
            payload.update(self.config.extra_body)

        # Forward the per-request reasoning effort, but only to providers that
        # accept it (otherwise a strict API would 400). Merges into any reasoning
        # hints already configured via ``extra``.
        effort = normalize_reasoning_effort(reasoning_effort)
        if effort and self.config.supports_reasoning:
            reasoning = dict(payload.get("reasoning") or {})
            reasoning["effort"] = effort
            payload["reasoning"] = reasoning

        client = self._get_client()
        started = time.monotonic()
        finish_reason: str | None = None
        try:
            self._requests_last_call += 1
            resp = await client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()

            # Extract text from OpenAI-compatible response
            choices = data.get("choices", [])
            if not choices:
                raise LLMError(f"No choices in response from {self.name}", self.name)

            message = choices[0].get("message", {})
            text = message.get("content", "") or ""

            tool_calls = self._parse_tool_calls(message.get("tool_calls"))
            finish_reason = choices[0].get("finish_reason")

            # A reasoning model can burn the whole output budget on hidden
            # reasoning and return ``finish_reason=length`` with no tool call,
            # leaving an acting agent silent: treat it as a model-level failure.
            # v0.5 R1 also treats *empty* content with no tool call as a silent
            # failure for every task, so the provider tries the next model and
            # the chain the next provider instead of falling back to a template
            # with no log.
            truncated = (
                finish_reason == "length"
                and not tool_calls
                and (bool(tools) or not text.strip())
            )
            if (not text.strip() and not tool_calls) or truncated:
                self._log_attempt(
                    purpose, self.name, model, attempt, total, "empty",
                    (time.monotonic() - started) * 1000.0, finish_reason,
                )
                if truncated and text.strip():
                    reason = "truncated before emitting a tool call"
                elif finish_reason == "length":
                    reason = "truncated with no content"
                else:
                    reason = "empty content"
                raise LLMError(f"Model {model} returned {reason}", self.name, retryable=True)

            self._log_attempt(
                purpose, self.name, model, attempt, total, "ok",
                (time.monotonic() - started) * 1000.0, finish_reason,
            )
            self._mark_success()
            return LLMResponse(
                text=text,
                provider=self.name,
                model=model,
                raw=data,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
            )

        except LLMError as e:
            if isinstance(e, LLMError) and not str(e).startswith("Model "):
                self._log_attempt(
                    purpose, self.name, model, attempt, total, "error",
                    (time.monotonic() - started) * 1000.0, finish_reason,
                )
            raise
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            self._log_attempt(
                purpose, self.name, model, attempt, total, "error",
                (time.monotonic() - started) * 1000.0, finish_reason,
            )
            if status == 429:
                raise LLMError(f"Rate limited: {e.response.text}", self.name, retryable=True, status=status)
            if 400 <= status < 500:
                raise LLMError(f"Bad request: {e.response.text}", self.name, retryable=False, status=status)
            raise LLMError(f"HTTP {status}: {e.response.text}", self.name, retryable=True, status=status)
        except httpx.RequestError as e:
            self._log_attempt(
                purpose, self.name, model, attempt, total, "error",
                (time.monotonic() - started) * 1000.0, finish_reason,
            )
            raise LLMError(f"Request failed: {e}", self.name, retryable=True)
        except Exception as e:
            self._log_attempt(
                purpose, self.name, model, attempt, total, "error",
                (time.monotonic() - started) * 1000.0, finish_reason,
            )
            raise LLMError(f"Unexpected error: {e}", self.name, retryable=True)

    @staticmethod
    def _parse_tool_calls(raw_calls: Any) -> tuple[LLMToolCall, ...]:
        """Parse OpenAI-style tool_calls into normalized LLMToolCall objects."""
        if not raw_calls:
            return ()
        tool_calls: list[LLMToolCall] = []
        for index, raw in enumerate(raw_calls):
            function = raw.get("function", {}) or {}
            call_id = raw.get("id") or f"call_{index}"
            name = function.get("name", "")
            arguments_raw = function.get("arguments", "")
            if isinstance(arguments_raw, dict):
                arguments = arguments_raw
            elif not arguments_raw:
                arguments = {}
            else:
                try:
                    arguments = json.loads(arguments_raw)
                except (json.JSONDecodeError, TypeError):
                    arguments = {"_raw": arguments_raw}
            tool_calls.append(LLMToolCall(id=call_id, name=name, arguments=arguments))
        return tuple(tool_calls)

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "model": self.config.model,
            "models": self.config.models,
            "failure_count": self._failure_count,
            "cold": self._is_cold(),
            "cold_until": self._cold_until if self._is_cold() else None,
            "model_status": self.model_status(),
        }


class OpenRouterProvider(OpenAICompatProvider):
    name = "openrouter"

    def __init__(self, config: ProviderConfig):
        if not config.base_url:
            config.base_url = "https://openrouter.ai/api/v1"
        super().__init__(config)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            base_url = self.config.base_url or "https://openrouter.ai/api/v1"
            headers = {
                "Authorization": f"Bearer {self.config.api_key}",
                "HTTP-Referer": "https://github.com/sims-sense",
                "X-Title": "Sensewright",
            }
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._client


class DeepSeekProvider(OpenAICompatProvider):
    name = "deepseek"

    def __init__(self, config: ProviderConfig):
        if not config.base_url:
            config.base_url = "https://api.deepseek.com/v1"
        super().__init__(config)


class OpenCodeZenProvider(OpenAICompatProvider):
    """OpenCode Zen gateway (OpenAI-compatible).

    Zen exposes curated models (including free ``*-free`` slugs) at
    ``https://opencode.ai/zen/v1`` behind a Bearer token. Some of the free
    models follow a zero-retention policy; others train on submitted data, so
    the model list is a deliberate choice, not a default.
    """

    name = "opencode"

    def __init__(self, config: ProviderConfig):
        if not config.base_url:
            config.base_url = "https://opencode.ai/zen/v1"
        super().__init__(config)