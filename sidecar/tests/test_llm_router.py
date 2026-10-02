"""Tests for sensewright_sidecar.llm.router module."""
from __future__ import annotations

from sensewright_sidecar.config import Config, DEFAULT_CONFIG
from sensewright_sidecar.llm.router import ModelRouter, RouteCandidate
from sensewright_sidecar.llm.providers.base import is_free_model


class TestModelRouter:
    """Tests for ModelRouter."""

    def _make_config(self, free_only=True, providers=None, routes=None):
        """Create a Config with custom settings."""
        import copy
        raw = copy.deepcopy(DEFAULT_CONFIG)
        raw["llm"]["free_only"] = free_only
        if providers:
            raw["llm"]["providers"] = providers
        if routes:
            raw["llm"]["routes"] = routes
        return Config(raw)

    def test_plan_returns_routed_provider_first(self):
        config = self._make_config(
            free_only=False,
            providers={
                "openrouter": {"enabled": True, "models": ["model-a"], "rpm": 0, "rpd": 0, "tpm": 0},
                "gemini": {"enabled": True, "models": ["model-b"], "rpm": 0, "rpd": 0, "tpm": 0},
            },
            routes={"default": {"provider": "gemini", "model": "model-b"}}
        )
        router = ModelRouter(config)
        plan = router.plan("some.purpose")
        assert len(plan) >= 1
        assert plan[0].provider == "gemini"
        assert plan[0].model == "model-b"

    def test_plan_free_only_filters_paid_models(self):
        config = self._make_config(
            free_only=True,
            providers={
                "openrouter": {"enabled": True, "models": ["paid-model"], "rpm": 0, "rpd": 0, "tpm": 0},
                "gemini": {"enabled": True, "models": ["gemini-2.0-flash:free"], "rpm": 0, "rpd": 0, "tpm": 0},
            },
            routes={"default": {"provider": "openrouter", "model": "paid-model"}}
        )
        router = ModelRouter(config)
        plan = router.plan("some.purpose")
        # Should not include paid-model
        providers_in_plan = [c.provider for c in plan]
        assert "openrouter" not in providers_in_plan or all(
            is_free_model(c.model, config.provider(c.provider)) for c in plan if c.provider == "openrouter"
        )
        # Should include free gemini model
        assert any(c.provider == "gemini" and "free" in c.model for c in plan)

    def test_plan_skips_disabled_providers(self):
        config = self._make_config(
            free_only=False,
            providers={
                "openrouter": {"enabled": False, "models": ["model-a"], "rpm": 0, "rpd": 0, "tpm": 0},
                "gemini": {"enabled": True, "models": ["model-b"], "rpm": 0, "rpd": 0, "tpm": 0},
            },
            routes={"default": {"provider": "openrouter", "model": "model-a"}}
        )
        router = ModelRouter(config)
        plan = router.plan("some.purpose")
        # openrouter is disabled, should fall back to gemini
        assert all(c.provider != "openrouter" for c in plan)
        assert any(c.provider == "gemini" for c in plan)

    def test_plan_no_duplicates(self):
        config = self._make_config(
            free_only=False,
            providers={
                "openrouter": {"enabled": True, "models": ["model-a", "model-b"], "rpm": 0, "rpd": 0, "tpm": 0},
            },
            routes={"default": {"provider": "openrouter", "model": "model-a"}}
        )
        router = ModelRouter(config)
        plan = router.plan("some.purpose")
        seen = set()
        for c in plan:
            key = (c.provider, c.model)
            assert key not in seen, f"Duplicate route: {key}"
            seen.add(key)

    def test_plan_empty_when_no_enabled_providers(self):
        config = self._make_config(
            free_only=False,
            providers={
                "openrouter": {"enabled": False, "models": ["model-a"], "rpm": 0, "rpd": 0, "tpm": 0},
            },
            routes={"default": {"provider": "openrouter", "model": "model-a"}}
        )
        router = ModelRouter(config)
        plan = router.plan("some.purpose")
        assert plan == []

    def test_has_route_true_when_plan_nonempty(self):
        config = self._make_config(
            free_only=False,
            providers={"openrouter": {"enabled": True, "models": ["model-a"], "rpm": 0, "rpd": 0, "tpm": 0}},
            routes={"default": {"provider": "openrouter", "model": "model-a"}}
        )
        router = ModelRouter(config)
        assert router.has_route("some.purpose") is True

    def test_has_route_false_when_plan_empty(self):
        config = self._make_config(
            free_only=False,
            providers={"openrouter": {"enabled": False, "models": ["model-a"], "rpm": 0, "rpd": 0, "tpm": 0}},
            routes={"default": {"provider": "openrouter", "model": "model-a"}}
        )
        router = ModelRouter(config)
        assert router.has_route("some.purpose") is False

    def test_plan_uses_fallback_models_when_routed_model_missing(self):
        config = self._make_config(
            free_only=False,
            providers={
                "openrouter": {"enabled": True, "models": ["model-a", "model-b"], "rpm": 0, "rpd": 0, "tpm": 0},
            },
            routes={"default": {"provider": "openrouter"}}  # No model specified
        )
        router = ModelRouter(config)
        plan = router.plan("some.purpose")
        assert len(plan) >= 1
        assert plan[0].provider == "openrouter"
        assert plan[0].model == "model-a"  # First model in list

    def test_plan_free_only_with_free_models_suffix(self):
        """Test that models with :free suffix are recognized as free."""
        config = self._make_config(
            free_only=True,
            providers={
                "openrouter": {"enabled": True, "models": ["model-a:free", "model-b"], "rpm": 0, "rpd": 0, "tpm": 0},
            },
            routes={"default": {"provider": "openrouter", "model": "model-b"}}
        )
        router = ModelRouter(config)
        plan = router.plan("some.purpose")
        # Should only include model-a:free
        assert len(plan) == 1
        assert plan[0].model == "model-a:free"


class TestIsFreeModel:
    """Tests for is_free_model helper."""

    def test_free_suffix(self):
        cfg = {"models": ["model:free"]}
        assert is_free_model("model:free", cfg) is True

    def test_known_free_models(self):
        # free_models list in config
        cfg = {"models": ["gemini-2.0-flash", "gemini-1.5-flash"], "free_models": ["gemini-2.0-flash", "gemini-1.5-flash"]}
        assert is_free_model("gemini-2.0-flash", cfg) is True
        assert is_free_model("gemini-1.5-flash", cfg) is True

    def test_paid_model(self):
        cfg = {"models": ["gpt-4o", "claude-3-opus"], "free_models": []}
        assert is_free_model("gpt-4o", cfg) is False
        assert is_free_model("claude-3-opus", cfg) is False

    def test_ollama_always_free(self):
        # Ollama models are free (no :free suffix needed, but can use free_models list)
        cfg = {"models": ["llama3.1"], "free_models": ["llama3.1"]}
        assert is_free_model("llama3.1", cfg) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])