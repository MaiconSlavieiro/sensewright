"""Provider abstractions for the Sensewright LLM layer.

Providers use only the standard library (``urllib.request``) so the sidecar has
no heavyweight HTTP dependencies. Two families are supported:

* ``OpenAICompatProvider`` — OpenAI-compatible ``/chat/completions`` endpoints
  (OpenRouter, Groq, DeepSeek, Ollama).
* ``GeminiProvider`` — Google's ``generateContent`` REST API.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..base import (
    LLMNetworkError, LLMProviderError, LLMRateLimited, LLMTimeout, ProviderResponse,
)

DEFAULT_TIMEOUT = 30.0


def is_free_model(model: str, config: Dict[str, Any]) -> bool:
    """Heuristic: ``:free`` suffix (OpenRouter) or explicit ``free_models`` list."""
    cfg = config or {}
    free_models = cfg.get("free_models") or []
    if model in free_models:
        return True
    return model.endswith(":free")


class Provider:
    """Base class for an LLM provider client."""

    name = "base"

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config or {}
        self.base_url = (self.config.get("base_url") or "").rstrip("/")
        self.api_key = self.config.get("api_key") or ""
        self.models = list(self.config.get("models") or [])
        self.free_models = list(self.config.get("free_models") or [])

    def is_free_model(self, model: str) -> bool:
        return is_free_model(model, self.config)

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        max_tokens: int = 256,
        temperature: float = 0.7,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> ProviderResponse:
        raise NotImplementedError

    def _http_post_json(self, url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: float) -> Dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise LLMRateLimited("HTTP 429 rate limited (provider={})".format(self.name))
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            raise LLMProviderError(
                "HTTP {} from {}: {}".format(exc.code, self.name, detail)
            )
        except (socket.timeout, TimeoutError):
            raise LLMTimeout("timeout calling {} ({:.1f}s)".format(self.name, timeout))
        except urllib.error.URLError as exc:
            raise LLMNetworkError("network error calling {}: {}".format(self.name, exc.reason))
        except json.JSONDecodeError as exc:
            raise LLMProviderError("invalid JSON from {}: {}".format(self.name, exc))


class OpenAICompatProvider(Provider):
    """Client for OpenAI-compatible chat completion endpoints."""

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        max_tokens: int = 256,
        temperature: float = 0.7,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> ProviderResponse:
        url = "{}/chat/completions".format(self.base_url)
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(self.api_key),
        }
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
        }
        data = self._http_post_json(url, payload, headers, timeout)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("malformed response from {}: {}".format(self.name, exc))
        usage = data.get("usage") or {}
        return ProviderResponse(
            text=content or "",
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            model=model,
        )


class GeminiProvider(Provider):
    """Client for Google Gemini's generateContent REST API."""

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        max_tokens: int = 256,
        temperature: float = 0.7,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> ProviderResponse:
        url = "{}/models/{}:generateContent".format(self.base_url, model)
        if self.api_key:
            url = url + "?key=" + self.api_key
        headers = {"Content-Type": "application/json"}
        contents = []
        for message in messages:
            role = message.get("role", "user")
            parts = [{"text": message.get("content", "")}]
            # Gemini uses "model" instead of "assistant".
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": parts})
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": int(max_tokens),
                "temperature": float(temperature),
            },
        }
        data = self._http_post_json(url, payload, headers, timeout)
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("malformed response from gemini: {}".format(exc))
        usage = data.get("usageMetadata") or {}
        total = int(usage.get("totalTokenCount", 0))
        prompt = int(usage.get("promptTokenCount", 0))
        return ProviderResponse(
            text=text or "",
            prompt_tokens=prompt,
            completion_tokens=max(0, total - prompt),
            total_tokens=total,
            model=model,
        )
