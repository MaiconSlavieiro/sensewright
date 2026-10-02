"""Tests for the LLM provider request shaping."""
from __future__ import annotations

from sensewright_sidecar.llm.providers import build_provider
from sensewright_sidecar.llm.providers.base import GeminiProvider, OpenAICompatProvider


def _msgs():
    return [{"role": "user", "content": "hi"}]


def test_build_provider_tags_instance_name():
    provider = build_provider("openrouter", {"base_url": "http://x", "api_key": "k", "models": []})
    assert isinstance(provider, OpenAICompatProvider)
    assert provider.name == "openrouter"

    gemini = build_provider("gemini", {"base_url": "http://x", "api_key": "k", "models": []})
    assert isinstance(gemini, GeminiProvider)
    assert gemini.name == "gemini"

    assert build_provider("nope", {}) is None


def test_openrouter_disables_reasoning():
    provider = build_provider("openrouter", {"base_url": "http://x", "api_key": "k", "models": []})
    payload = provider.build_payload(_msgs(), "some/model:free", 220, 0.0)
    assert payload["reasoning"] == {"enabled": False}
    assert payload["max_tokens"] == 220


def test_non_openrouter_keeps_default_payload():
    provider = OpenAICompatProvider({"base_url": "http://x", "api_key": "k", "models": []})
    provider.name = "deepseek"
    payload = provider.build_payload(_msgs(), "deepseek-flash", 400, 0.7)
    assert "reasoning" not in payload
    assert payload["temperature"] == 0.7
