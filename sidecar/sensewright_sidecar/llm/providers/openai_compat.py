"""OpenAI-compatible chat completions provider base class."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ...config import ProviderConfig
from ..base import LLMError, LLMResponse, LLMToolCall, normalize_reasoning_effort

logger = logging.getLogger(__name__)


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

    @property
    def available(self) -> bool:
        return self.config.enabled and bool(self.config.api_key)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            base_url = self.config.base_url or "https://api.openai.com/v1"
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers={"Authorization": f"Bearer {self.config.api_key}"},
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

    def _candidate_models(self) -> list[str]:
        """Ordered model list: explicit ``model`` first, then the ``models`` list.

        Trying several models within one provider keeps a reply coming when a
        single free model is rate-limited or briefly unavailable, before the
        chain has to fall back to the next provider.

        When ``free_only`` is set, any model not marked free (an id containing
        ``:free``) is dropped, so a misconfigured list can never trigger billing.
        """
        models: list[str] = []
        if self.config.model:
            models.append(self.config.model)
        for model in self.config.models:
            if model and model not in models:
                models.append(model)
        if self.config.free_only:
            models = [model for model in models if ":free" in model]
        return models or ([] if self.config.free_only else ["gpt-3.5-turbo"])

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        if not self.available:
            raise LLMError(f"Provider {self.name} not available (disabled or no API key)", self.name, retryable=False)

        if self._is_cold():
            raise LLMError(f"Provider {self.name} is in cool-down", self.name, retryable=True)

        models = self._candidate_models()
        if not models:
            raise LLMError(
                f"Provider {self.name} has no usable models (free_only guard)",
                self.name,
                retryable=True,
            )
        last_error: LLMError | None = None

        for index, model in enumerate(models):
            try:
                return await self._complete_with_model(
                    model,
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                    reasoning_effort=reasoning_effort,
                )
            except LLMError as e:
                last_error = e
                if _is_auth_error(e):
                    # A bad/expired key or missing permission is provider-wide;
                    # another model on the same key cannot fix it.
                    self._mark_failure()
                    raise
                if index < len(models) - 1:
                    logger.warning(f"Provider {self.name} model {model} failed: {e}; trying next model")

        self._mark_failure()
        if last_error is not None:
            raise last_error
        raise LLMError(f"Provider {self.name} produced no response", self.name)

    async def _complete_with_model(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        reasoning_effort: str | None = None,
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

        # Merge any extra parameters
        if self.config.extra:
            payload.update(self.config.extra)

        # Forward the per-request reasoning effort, but only to providers that
        # accept it (otherwise a strict API would 400). Merges into any reasoning
        # hints already configured via ``extra``.
        effort = normalize_reasoning_effort(reasoning_effort)
        if effort and self.config.supports_reasoning:
            reasoning = dict(payload.get("reasoning") or {})
            reasoning["effort"] = effort
            payload["reasoning"] = reasoning

        client = self._get_client()
        try:
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
            # reasoning and return ``finish_reason=length`` with no tool call.
            # That leaves an acting agent silent, so treat it as a model-level
            # failure and let the provider try the next model in its list.
            if tools and not tool_calls and finish_reason == "length":
                raise LLMError(
                    f"Model {model} truncated before emitting a tool call",
                    self.name,
                    retryable=True,
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

        except LLMError:
            raise
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 429:
                raise LLMError(f"Rate limited: {e.response.text}", self.name, retryable=True, status=status)
            if 400 <= status < 500:
                raise LLMError(f"Bad request: {e.response.text}", self.name, retryable=False, status=status)
            raise LLMError(f"HTTP {status}: {e.response.text}", self.name, retryable=True, status=status)
        except httpx.RequestError as e:
            raise LLMError(f"Request failed: {e}", self.name, retryable=True)
        except Exception as e:
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