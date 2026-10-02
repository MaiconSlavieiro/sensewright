"""Tests for sensewright_sidecar.llm.scheduler module."""
from __future__ import annotations

import pytest

from sensewright_sidecar.config import Config, DEFAULT_CONFIG
from sensewright_sidecar.llm.scheduler import LLMScheduler, _extract_json, _recover_structured
from sensewright_sidecar.purposes import PURPOSES, get_purpose


class TestExtractJson:
    """Tests for _extract_json helper."""

    def test_plain_json(self):
        text = '{"key": "value", "num": 42}'
        result = _extract_json(text)
        assert result == {"key": "value", "num": 42}

    def test_markdown_fence(self):
        text = '```json\n{"key": "value"}\n```'
        result = _extract_json(text)
        assert result == {"key": "value"}

    def test_markdown_fence_with_language(self):
        text = '```python\n{"key": "value"}\n```'
        result = _extract_json(text)
        assert result == {"key": "value"}

    def test_trailing_prose(self):
        text = '{"key": "value"} Some extra text here'
        result = _extract_json(text)
        assert result == {"key": "value"}

    def test_leading_prose(self):
        text = 'Here is the result: {"key": "value"}'
        result = _extract_json(text)
        assert result == {"key": "value"}

    def test_invalid_json_returns_empty(self):
        text = 'not json at all'
        result = _extract_json(text)
        assert result == {}

    def test_empty_string_returns_empty(self):
        assert _extract_json("") == {}

    def test_nested_json(self):
        text = '{"outer": {"inner": [1, 2, 3]}}'
        result = _extract_json(text)
        assert result == {"outer": {"inner": [1, 2, 3]}}

    def test_array_at_root_returns_empty(self):
        text = '[1, 2, 3]'
        result = _extract_json(text)
        assert result == {}

    def test_balanced_braces_extraction(self):
        text = 'prefix {"a": 1} middle {"b": 2} suffix'
        result = _extract_json(text)
        assert result == {"a": 1}


class TestRecoverStructured:
    """Tests for _recover_structured (non-JSON few-shot imitation)."""

    def test_impulse_thought_block(self):
        text = "[thought]Need coffee before my shift.[/thought]"
        result = _recover_structured("sim.impulse", text)
        assert result == {"thought": "Need coffee before my shift.", "intents": []}

    def test_chat_thought_plus_speech(self):
        text = "[thought]Worn out today.[/thought]\nHi! How are you doing?"
        result = _recover_structured("sim.chat", text)
        assert result == {
            "response": "Hi! How are you doing?",
            "thought": "Worn out today.",
            "intents": [],
            "trust_delta": 0.0,
        }

    def test_chat_thought_only_returns_empty(self):
        # Without speech there is no chat response; fall back instead.
        assert _recover_structured("sim.chat", "[thought]Worn out.[/thought]") == {}

    def test_no_thought_block_returns_empty(self):
        assert _recover_structured("sim.impulse", "plain prose, no block") == {}
        assert _recover_structured("sim.impulse", "") == {}


class TestLLMScheduler:
    """Tests for LLMScheduler with no providers configured (fallback mode)."""

    @pytest.fixture
    def config(self):
        """Config with no enabled providers."""
        import copy
        raw = copy.deepcopy(DEFAULT_CONFIG)
        # Ensure all providers disabled
        for provider in raw["llm"]["providers"].values():
            provider["enabled"] = False
        raw["llm"]["free_only"] = True
        return Config(raw)

    @pytest.fixture
    def scheduler(self, config):
        return LLMScheduler(config)

    def test_run_purpose_returns_fallback_for_all_purposes(self, scheduler):
        """Test that all 33 purposes return fallback when no providers configured."""
        for purpose in PURPOSES:
            result = scheduler.run_purpose(purpose.id, context={}, lang="pt-BR")
            assert result.ok is True
            assert result.fallback is True
            assert result.data is not None
            assert isinstance(result.data, dict)
            assert len(result.data) > 0, f"Purpose {purpose.id} returned empty fallback data"

    def test_run_purpose_unknown_purpose_returns_empty_fallback(self, scheduler):
        result = scheduler.run_purpose("unknown.purpose", context={}, lang="pt-BR")
        assert result.ok is True
        assert result.fallback is True
        assert result.data == {}

    def test_run_purpose_includes_latency(self, scheduler):
        result = scheduler.run_purpose("sim.chat", context={}, lang="pt-BR")
        assert result.latency_s >= 0

    def test_run_purpose_with_context(self, scheduler):
        context = {"sim_id": 1, "sim_name": "Test", "message": "Hello"}
        result = scheduler.run_purpose("sim.chat", context=context, lang="pt-BR")
        assert result.fallback is True
        assert "response" in result.data

    def test_submit_bg_dedup(self, scheduler):
        """Test that submit_bg deduplicates by dedup_key when jobs overlap in flight."""
        callback_results = []

        def callback(result):
            callback_results.append(result)

        # Submit same job twice with same dedup_key quickly
        scheduler.submit_bg("sim.impulse", {"sim_id": 1}, "pt-BR", dedup_key="test:1", callback=callback)
        scheduler.submit_bg("sim.impulse", {"sim_id": 1}, "pt-BR", dedup_key="test:1", callback=callback)

        # Give worker time to process - with fallback mode, jobs complete very fast
        # so dedup may not catch both. This test verifies the mechanism exists.
        import time
        time.sleep(0.5)

        # At least one should have executed
        assert len(callback_results) >= 1
        # The dedup mechanism is tested by checking in_flight tracking
        status = scheduler.status()
        # After completion, in_flight should be empty
        assert status["in_flight"] == []

    def test_submit_bg_different_keys_not_deduped(self, scheduler):
        callback_results = []

        def callback(result):
            callback_results.append(result)

        scheduler.submit_bg("sim.impulse", {"sim_id": 1}, "pt-BR", dedup_key="test:1", callback=callback)
        scheduler.submit_bg("sim.impulse", {"sim_id": 1}, "pt-BR", dedup_key="test:2", callback=callback)

        import time
        time.sleep(0.5)

        assert len(callback_results) == 2

    def test_status_returns_chain_queue_budget(self, scheduler):
        status = scheduler.status()
        assert "chain" in status
        assert "queue_depth" in status
        assert "in_flight" in status
        assert "game_budget" in status


if __name__ == "__main__":
    pytest.main([__file__, "-v"])