"""Gemini (Google Generative Language API) provider."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from ...config import ProviderConfig
from ..base import LLMError, LLMResponse, LLMToolCall

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Gemini provider using the Google Generative Language REST API.

    Endpoint: POST /v1beta/models/{model}:generateContent

    The API key is sent in the ``x-goog-api-key`` header (not the query
    string) so it never appears in request logs.

    v0.5 follow-up: tries the configured ``model``/``models`` in order (so a
    retired model or a per-model 404/429 falls through to the next one), counts
    every real request (A2), treats empty content with no tool call as a
    retryable failure, and only sends ``thinkingConfig`` when the config asks
    for it (Gemini 3.x rejects ``thinkingBudget=0`` with a 400).
    """

    name = "gemini"

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._failure_count = 0
        self._cold_until: float = 0.0
        self._requests_last_call = 0

    @property
    def available(self) -> bool:
        # v0.5 follow-up A6: honour ``api_key_optional`` for consistency (Gemini
        # itself needs a key, but a generic/local config may not).
        if not self.config.enabled:
            return False
        return bool(self.config.api_key) or bool(self.config.api_key_optional)

    @property
    def requests_last_call(self) -> int:
        return self._requests_last_call

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url="https://generativelanguage.googleapis.com",
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _is_cold(self) -> bool:
        return time.time() < self._cold_until

    def _mark_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= 3:
            self._cold_until = time.time() + 60.0
            logger.warning(f"Provider {self.name} marked cold for 60s after {self._failure_count} failures")

    def _mark_success(self) -> None:
        self._failure_count = 0
        self._cold_until = 0.0

    def _candidate_models(self) -> list[str]:
        models: list[str] = []
        if self.config.model:
            models.append(self.config.model)
        for model in self.config.models:
            if model and model not in models:
                models.append(model)
        return models or ["gemini-2.5-flash"]

    def _messages_to_contents(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Convert OpenAI-style messages to Gemini contents format."""
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            # Map roles: system/user/assistant -> user/model
            if role == "system":
                # Prepend system instruction to first user message or add as user
                contents.append({"role": "user", "parts": [{"text": f"[System]: {content}"}]})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
            else:
                contents.append({"role": "user", "parts": [{"text": content}]})
        return contents

    def _tools_to_gemini(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI-style tool schemas to Gemini functionDeclarations."""
        declarations = []
        for tool in tools:
            function = tool.get("function", {}) or {}
            declarations.append(
                {
                    "name": function.get("name", ""),
                    "description": function.get("description", ""),
                    "parameters": function.get("parameters", {}),
                }
            )
        return [{"functionDeclarations": declarations}]

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

        models = self._candidate_models()
        last_error: LLMError | None = None

        for model in models:
            try:
                response = await self._generate_with_model(
                    model,
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                    purpose=purpose,
                )
                self._mark_success()
                return response
            except LLMError as e:
                last_error = e
                if not e.retryable:
                    # Bad key / forbidden: another model on the same key cannot
                    # fix it, abort the whole provider.
                    self._mark_failure()
                    raise
                logger.warning(f"Provider {self.name} model {model} failed: {e}; trying next model")

        self._mark_failure()
        if last_error is not None:
            raise last_error
        raise LLMError(f"Provider {self.name} produced no response", self.name)

    async def _generate_with_model(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        purpose: str | None = None,
    ) -> LLMResponse:
        contents = self._messages_to_contents(messages)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {},
        }
        if temperature is not None:
            payload["generationConfig"]["temperature"] = temperature
        if max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens
        # Only send a thinking budget when explicitly configured. Gemini 3.x
        # rejects ``thinkingBudget=0`` with HTTP 400, so the old automatic
        # "disable thinking" is gone (v0.5 follow-up).
        if self.config.thinking_budget is not None:
            payload["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": int(self.config.thinking_budget)
            }
        if tools:
            payload["tools"] = self._tools_to_gemini(tools)

        # Merge any extra parameters
        if self.config.extra:
            payload.update(self.config.extra)

        client = self._get_client()
        url = f"/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": self.config.api_key}

        started = time.monotonic()
        try:
            self._requests_last_call += 1
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            # Extract text and function calls from Gemini response
            candidates = data.get("candidates", [])
            if not candidates:
                raise LLMError(f"No candidates in response from {self.name}", self.name)

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            text = "".join(part.get("text", "") for part in parts)

            tool_calls: list[LLMToolCall] = []
            for part in parts:
                function_call = part.get("functionCall")
                if not function_call:
                    continue
                tool_calls.append(
                    LLMToolCall(
                        id=f"gemini_call_{len(tool_calls)}",
                        name=function_call.get("name", ""),
                        arguments=function_call.get("args", {}) or {},
                    )
                )

            finish_reason = candidates[0].get("finishReason")
            # v0.5 R1 parity: empty content with no tool call is a retryable
            # failure, so a reasoning model that burns its budget (MAX_TOKENS)
            # or a silent answer does not fall through to a template.
            if not text.strip() and not tool_calls:
                logger.info(
                    "llm.attempt purpose=%s provider=%s model=%s attempt=1/1 outcome=empty latency_ms=%.0f finish=%s",
                    purpose or "-",
                    self.name,
                    model,
                    (time.monotonic() - started) * 1000.0,
                    finish_reason or "-",
                )
                raise LLMError(f"Model {model} returned empty content", self.name, retryable=True)

            return LLMResponse(
                text=text,
                provider=self.name,
                model=model,
                raw=data,
                tool_calls=tuple(tool_calls),
                finish_reason=finish_reason,
            )

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status in (401, 403):
                raise LLMError(f"Auth error: {e.response.text}", self.name, retryable=False, status=status)
            if status == 429:
                raise LLMError(f"Rate limited: {e.response.text}", self.name, retryable=True, status=status)
            if 400 <= status < 500:
                # Model-specific (e.g. a retired model -> 404): try the next one.
                raise LLMError(f"Bad request: {e.response.text}", self.name, retryable=True, status=status)
            raise LLMError(f"HTTP {status}: {e.response.text}", self.name, retryable=True, status=status)
        except httpx.RequestError as e:
            raise LLMError(f"Request failed: {e}", self.name, retryable=True)
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Unexpected error: {e}", self.name, retryable=True)

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
