"""Tests for LLM provider chain with circuit breaker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sensewright_sidecar.config import LLMConfig, ProviderConfig, Settings
from sensewright_sidecar.llm.base import AllProvidersFailed, LLMError, LLMResponse
from sensewright_sidecar.llm.chain import ProviderChain
from sensewright_sidecar.llm.limits import ProviderRateLimiter


class FakeProvider:
    """Fake provider for testing."""

    def __init__(self, name: str, should_fail: bool = False, fail_count: int = 0, retryable: bool = True):
        self.name = name
        self.should_fail = should_fail
        self.fail_count = fail_count
        self.retryable = retryable
        self.call_count = 0
        self._failure_count = 0
        self._cold_until = 0.0
        self.config = MagicMock()
        self.config.enabled = True
        self.config.api_key = "test-key"
        self.config.model = "test-model"
        self.config.models = []

    @property
    def available(self) -> bool:
        return True

    def _is_cold(self) -> bool:
        import time
        return time.time() < self._cold_until

    def _mark_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= 3:
            import time
            self._cold_until = time.time() + 60.0

    def _mark_success(self) -> None:
        self._failure_count = 0
        self._cold_until = 0.0

    async def complete(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
        self.call_count += 1
        if self.should_fail and self.call_count <= self.fail_count:
            self._mark_failure()
            raise LLMError(f"Fake failure {self.call_count}", self.name, retryable=self.retryable)
        self._mark_success()
        return LLMResponse(
            text=f"Response from {self.name}",
            provider=self.name,
            model="test-model",
            raw={},
        )

    def status(self) -> dict:
        return {
            "name": self.name,
            "available": self.available,
            "failure_count": self._failure_count,
            "cold": self._is_cold(),
        }


def make_test_settings(providers: dict[str, ProviderConfig] | None = None) -> Settings:
    """Create a test Settings object."""
    if providers is None:
        providers = {
            "provider_a": ProviderConfig(enabled=True, api_key="key-a", model="model-a"),
            "provider_b": ProviderConfig(enabled=True, api_key="key-b", model="model-b"),
            "provider_c": ProviderConfig(enabled=True, api_key="key-c", model="model-c"),
        }
    return Settings(
        llm=LLMConfig(
            chain=list(providers.keys()),
            providers=providers,
        )
    )


@pytest.mark.asyncio
async def test_chain_success_first_provider():
    """Test that chain returns first provider's response on success."""
    settings = make_test_settings()

    with patch("sensewright_sidecar.llm.chain.PROVIDER_CLASSES", {}):
        chain = ProviderChain(settings)
        # Replace with fake providers
        provider_a = FakeProvider("provider_a")
        provider_b = FakeProvider("provider_b")
        chain._providers = [provider_a, provider_b]
        chain._provider_map = {"provider_a": provider_a, "provider_b": provider_b}
        chain._chain_order = ["provider_a", "provider_b"]

        response = await chain.complete(
            [{"role": "user", "content": "Hello"}],
            lang="en",
        )

        assert response.provider == "provider_a"
        assert response.text == "Response from provider_a"
        assert provider_a.call_count == 1
        assert provider_b.call_count == 0


@pytest.mark.asyncio
async def test_chain_fallback_on_failure():
    """Test that chain falls back to next provider on failure."""
    settings = make_test_settings()

    with patch("sensewright_sidecar.llm.chain.PROVIDER_CLASSES", {}):
        chain = ProviderChain(settings)
        provider_a = FakeProvider("provider_a", should_fail=True, fail_count=1)
        provider_b = FakeProvider("provider_b")
        chain._providers = [provider_a, provider_b]
        chain._provider_map = {"provider_a": provider_a, "provider_b": provider_b}
        chain._chain_order = ["provider_a", "provider_b"]

        response = await chain.complete(
            [{"role": "user", "content": "Hello"}],
            lang="en",
        )

        assert response.provider == "provider_b"
        assert response.text == "Response from provider_b"
        assert provider_a.call_count == 1
        assert provider_b.call_count == 1


@pytest.mark.asyncio
async def test_chain_circuit_breaker_after_3_failures():
    """Test that provider is marked cold after 3 failures across multiple requests."""
    settings = make_test_settings()

    with patch("sensewright_sidecar.llm.chain.PROVIDER_CLASSES", {}):
        chain = ProviderChain(settings)
        provider_a = FakeProvider("provider_a", should_fail=True, fail_count=3)
        provider_b = FakeProvider("provider_b")
        chain._providers = [provider_a, provider_b]
        chain._provider_map = {"provider_a": provider_a, "provider_b": provider_b}
        chain._chain_order = ["provider_a", "provider_b"]

        # First request - provider_a fails once, provider_b succeeds
        response = await chain.complete(
            [{"role": "user", "content": "Hello"}],
            lang="en",
        )
        assert response.provider == "provider_b"
        assert provider_a.call_count == 1
        assert provider_b.call_count == 1

        # Second request - provider_a fails again
        provider_b.call_count = 0
        response = await chain.complete(
            [{"role": "user", "content": "Hello 2"}],
            lang="en",
        )
        assert response.provider == "provider_b"
        assert provider_a.call_count == 2
        assert provider_b.call_count == 1

        # Third request - provider_a fails third time, should be marked cold
        provider_b.call_count = 0
        response = await chain.complete(
            [{"role": "user", "content": "Hello 3"}],
            lang="en",
        )
        assert response.provider == "provider_b"
        assert provider_a.call_count == 3
        assert provider_b.call_count == 1

        # Provider A should now be cold
        assert provider_a._is_cold() is True

        # Fourth request - should skip cold provider_a and go straight to provider_b
        provider_b.call_count = 0
        response = await chain.complete(
            [{"role": "user", "content": "Hello 4"}],
            lang="en",
        )
        assert response.provider == "provider_b"
        assert provider_a.call_count == 3  # unchanged
        assert provider_b.call_count == 1


@pytest.mark.asyncio
async def test_chain_all_providers_failed():
    """Test AllProvidersFailed is raised when all providers fail."""
    settings = make_test_settings()

    with patch("sensewright_sidecar.llm.chain.PROVIDER_CLASSES", {}):
        chain = ProviderChain(settings)
        provider_a = FakeProvider("provider_a", should_fail=True, fail_count=1)
        provider_b = FakeProvider("provider_b", should_fail=True, fail_count=1)
        chain._providers = [provider_a, provider_b]
        chain._provider_map = {"provider_a": provider_a, "provider_b": provider_b}
        chain._chain_order = ["provider_a", "provider_b"]

        with pytest.raises(AllProvidersFailed) as exc_info:
            await chain.complete(
                [{"role": "user", "content": "Hello"}],
                lang="en",
            )

        assert "provider_a" in exc_info.value.failed_providers
        assert "provider_b" in exc_info.value.failed_providers


@pytest.mark.asyncio
async def test_chain_prefer_provider():
    """Test that preferred provider is tried first."""
    settings = make_test_settings()

    with patch("sensewright_sidecar.llm.chain.PROVIDER_CLASSES", {}):
        chain = ProviderChain(settings)
        provider_a = FakeProvider("provider_a")
        provider_b = FakeProvider("provider_b")
        chain._providers = [provider_a, provider_b]
        chain._provider_map = {"provider_a": provider_a, "provider_b": provider_b}
        chain._chain_order = ["provider_a", "provider_b"]

        # Prefer provider_b even though provider_a is first in chain
        response = await chain.complete(
            [{"role": "user", "content": "Hello"}],
            lang="en",
            prefer="provider_b",
        )

        assert response.provider == "provider_b"
        assert provider_b.call_count == 1
        assert provider_a.call_count == 0


@pytest.mark.asyncio
async def test_chain_non_retryable_error_stops_chain():
    """Test that non-retryable errors stop the chain immediately."""
    settings = make_test_settings()

    with patch("sensewright_sidecar.llm.chain.PROVIDER_CLASSES", {}):
        chain = ProviderChain(settings)
        provider_a = FakeProvider("provider_a", should_fail=True, fail_count=1, retryable=False)
        provider_b = FakeProvider("provider_b")
        chain._providers = [provider_a, provider_b]
        chain._provider_map = {"provider_a": provider_a, "provider_b": provider_b}
        chain._chain_order = ["provider_a", "provider_b"]

        with pytest.raises(AllProvidersFailed) as exc_info:
            await chain.complete(
                [{"role": "user", "content": "Hello"}],
                lang="en",
            )

        # Should not have tried provider_b
        assert provider_a.call_count == 1
        assert provider_b.call_count == 0
        assert "provider_a" in exc_info.value.failed_providers
        assert "provider_b" not in exc_info.value.failed_providers


@pytest.mark.asyncio
async def test_chain_status():
    """Test chain status reporting."""
    settings = make_test_settings()

    with patch("sensewright_sidecar.llm.chain.PROVIDER_CLASSES", {}):
        chain = ProviderChain(settings)
        provider_a = FakeProvider("provider_a")
        provider_b = FakeProvider("provider_b")
        chain._providers = [provider_a, provider_b]
        chain._provider_map = {"provider_a": provider_a, "provider_b": provider_b}
        chain._chain_order = ["provider_a", "provider_b"]

        status = chain.status()

        assert status["chain_order"] == ["provider_a", "provider_b"]
        assert "provider_a" in status["providers"]
        assert "provider_b" in status["providers"]
        assert status["providers"]["provider_a"]["name"] == "provider_a"


def test_rate_limiter_disabled_never_blocks():
    limiter = ProviderRateLimiter(rpm=0, rpd=0)

    assert limiter.enabled is False
    assert all(limiter.try_acquire() for _ in range(50))


def test_rate_limiter_enforces_rpm_then_rpd():
    clock = [1000.0]
    limiter = ProviderRateLimiter(
        rpm=2,
        rpd=3,
        monotonic=lambda: clock[0],
        wall_clock=lambda: clock[0],
    )

    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is False  # RPM exhausted

    clock[0] += 61.0  # window slides
    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is False  # RPD exhausted

    snap = limiter.snapshot()
    assert snap["rpm"] == 2
    assert snap["day_used"] == 3
    assert snap["day_remaining"] == 0


@pytest.mark.asyncio
async def test_chain_skips_rate_limited_provider():
    settings = make_test_settings()

    with patch("sensewright_sidecar.llm.chain.PROVIDER_CLASSES", {}):
        chain = ProviderChain(settings)
        provider_a = FakeProvider("provider_a")
        provider_b = FakeProvider("provider_b")
        chain._providers = [provider_a, provider_b]
        chain._provider_map = {"provider_a": provider_a, "provider_b": provider_b}
        chain._chain_order = ["provider_a", "provider_b"]
        chain._limiters = {"provider_a": ProviderRateLimiter(rpm=1)}

        first = await chain.complete([{"role": "user", "content": "hi"}], lang="en")
        assert first.provider == "provider_a"
        assert provider_a.call_count == 1

        second = await chain.complete([{"role": "user", "content": "hi"}], lang="en")
        assert second.provider == "provider_b"
        assert provider_a.call_count == 1  # skipped, not called again
        assert provider_b.call_count == 1


def test_chain_primary_rpm_reads_configured_provider():
    providers = {
        "provider_a": ProviderConfig(enabled=True, api_key="key-a", model="model-a", rpm=42),
    }
    settings = make_test_settings(providers)

    with patch("sensewright_sidecar.llm.chain.PROVIDER_CLASSES", {}):
        chain = ProviderChain(settings)
        provider_a = FakeProvider("provider_a")
        chain._providers = [provider_a]
        chain._provider_map = {"provider_a": provider_a}
        chain._chain_order = ["provider_a"]

        assert chain.primary_rpm() == 42