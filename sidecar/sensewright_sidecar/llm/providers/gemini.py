"""Gemini (Google Generative Language API) provider."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from ...config import ProviderConfig
from ..base import LLMError, LLMResponse, LLMToolCall

logger = logging.getLogger(__name__)


def _supports_thinking(model: str) -> bool:
    """True for Gemini models that accept a thinkingConfig budget."""
    return any(tag in model for tag in ("2.5", "3.", "3-", "latest"))


class GeminiProvider:
    """Gemini provider using the Google Generative Language REST API.

    Endpoint: POST /v1beta/models/{model}:generateContent

    The API key is sent in the ``x-goog-api-key`` header (not the query
    string) so it never appears in request logs.
    """

    name = "gemini"

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._failure_count = 0
        self._cold_until: float = 0.0

    @property
    def available(self) -> bool:
        return self.config.enabled and bool(self.config.api_key)

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
    ) -> LLMResponse:
        if not self.available:
            raise LLMError(f"Provider {self.name} not available (disabled or no API key)", self.name, retryable=False)

        if self._is_cold():
            raise LLMError(f"Provider {self.name} is in cool-down", self.name, retryable=True)

        model = self.config.model or "gemini-1.5-flash-latest"

        contents = self._messages_to_contents(messages)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {},
        }
        if temperature is not None:
            payload["generationConfig"]["temperature"] = temperature
        if max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens
        # Gemini 2.5+ models spend part of the output budget on internal
        # "thinking", which truncates short structured answers. Disable it so
        # JSON/tool responses fit within maxOutputTokens.
        if _supports_thinking(model):
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
        if tools:
            payload["tools"] = self._tools_to_gemini(tools)

        # Merge any extra parameters
        if self.config.extra:
            payload.update(self.config.extra)

        client = self._get_client()
        url = f"/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": self.config.api_key}

        try:
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

            self._mark_success()
            return LLMResponse(
                text=text,
                provider=self.name,
                model=model,
                raw=data,
                tool_calls=tuple(tool_calls),
            )

        except httpx.HTTPStatusError as e:
            self._mark_failure()
            if e.response.status_code == 429:
                raise LLMError(f"Rate limited: {e.response.text}", self.name, retryable=True)
            if 400 <= e.response.status_code < 500:
                raise LLMError(f"Bad request: {e.response.text}", self.name, retryable=False)
            raise LLMError(f"HTTP {e.response.status_code}: {e.response.text}", self.name, retryable=True)
        except httpx.RequestError as e:
            self._mark_failure()
            raise LLMError(f"Request failed: {e}", self.name, retryable=True)
        except Exception as e:
            self._mark_failure()
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