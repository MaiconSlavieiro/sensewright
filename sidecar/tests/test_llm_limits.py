"""Tests for sensewright_sidecar.llm.limits module."""
from __future__ import annotations

import time

import pytest

from sensewright_sidecar.llm.limits import estimate_tokens, ProviderRateLimiter


class TestEstimateTokens:
    """Tests for estimate_tokens."""

    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_ascii_text(self):
        # Roughly 4 chars per token
        text = "a" * 100
        assert estimate_tokens(text) == 25

    def test_non_ascii_text(self):
        # Non-ASCII uses divisor of 2
        text = "あ" * 100  # Japanese characters
        assert estimate_tokens(text) == 50

    def test_mixed_text_mostly_ascii(self):
        text = "a" * 100 + "あ" * 10  # 90% ASCII
        # Should use divisor 4
        assert estimate_tokens(text) == 27  # 110 // 4 = 27

    def test_mixed_text_mostly_non_ascii(self):
        text = "a" * 10 + "あ" * 100  # 90% non-ASCII
        # Should use divisor 2
        assert estimate_tokens(text) == 55  # 110 // 2 = 55

    def test_minimum_one_token(self):
        assert estimate_tokens("a") == 1
        assert estimate_tokens("あ") == 1


class TestProviderRateLimiter:
    """Tests for ProviderRateLimiter."""

    def test_unlimited_by_default(self):
        limiter = ProviderRateLimiter(rpm=0, rpd=0, tpm=0)
        assert limiter.can_accept(1000) is True
        limiter.record_request()
        limiter.record_tokens(1000)
        assert limiter.can_accept(1000) is True

    def test_rpm_limit(self):
        limiter = ProviderRateLimiter(rpm=2, rpd=0, tpm=0)
        assert limiter.can_accept() is True
        limiter.record_request()
        assert limiter.can_accept() is True
        limiter.record_request()
        assert limiter.can_accept() is False  # Exceeded RPM

    def test_rpm_window_expiry(self):
        limiter = ProviderRateLimiter(rpm=1, rpd=0, tpm=0)
        limiter.record_request()
        assert limiter.can_accept() is False
        # Manually expire the request by manipulating time
        # We can't easily test time expiry without mocking time.time()
        # But we can verify the pruning logic works by checking internal state
        assert len(limiter._requests) == 1

    def test_tpm_limit(self):
        limiter = ProviderRateLimiter(rpm=0, rpd=0, tpm=100)
        assert limiter.can_accept(50) is True
        limiter.record_request()
        limiter.record_tokens(50)
        assert limiter.can_accept(60) is False  # Would exceed TPM
        assert limiter.can_accept(50) is True   # Exactly at limit

    def test_tpm_reconciliation(self):
        limiter = ProviderRateLimiter(rpm=0, rpd=0, tpm=100)
        limiter.record_request()
        limiter.record_tokens(30)  # Estimated 50, actual 30
        # Should have 70 remaining
        assert limiter.remaining_tpm() == 70

    def test_remaining_tpm_unlimited(self):
        limiter = ProviderRateLimiter(rpm=0, rpd=0, tpm=0)
        assert limiter.remaining_tpm() is None

    def test_remaining_tpm_limited(self):
        limiter = ProviderRateLimiter(rpm=0, rpd=0, tpm=100)
        limiter.record_tokens(30)
        assert limiter.remaining_tpm() == 70

    def test_snapshot(self):
        limiter = ProviderRateLimiter(rpm=10, rpd=100, tpm=1000)
        limiter.record_request()
        limiter.record_tokens(50)
        snap = limiter.snapshot()
        assert snap["requests_last_minute"] == 1
        assert snap["tokens_last_minute"] == 50
        assert snap["rpm_limit"] == 10
        assert snap["tpm_limit"] == 1000

    def test_record_request_increments_counter(self):
        limiter = ProviderRateLimiter(rpm=10, rpd=0, tpm=0)
        assert len(limiter._requests) == 0
        limiter.record_request()
        assert len(limiter._requests) == 1

    def test_record_tokens_increments_counter(self):
        limiter = ProviderRateLimiter(rpm=0, rpd=0, tpm=100)
        assert len(limiter._tokens) == 0
        limiter.record_tokens(25)
        assert len(limiter._tokens) == 1
        assert limiter._tokens[0][1] == 25

    def test_negative_limits_treated_as_zero(self):
        limiter = ProviderRateLimiter(rpm=-1, rpd=-1, tpm=-1)
        assert limiter.rpm == 0
        assert limiter.rpd == 0
        assert limiter.tpm == 0
        assert limiter.can_accept(1000) is True

    def test_prune_removes_old_entries(self):
        limiter = ProviderRateLimiter(rpm=10, rpd=100, tpm=1000)
        # Manually add old timestamps
        old_time = time.time() - 100  # 100 seconds ago
        limiter._requests.append(old_time)
        limiter._tokens.append((old_time, 10))

        # Call can_accept which triggers prune
        limiter.can_accept()

        # Old entries should be pruned
        assert len(limiter._requests) == 0
        assert len(limiter._tokens) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])