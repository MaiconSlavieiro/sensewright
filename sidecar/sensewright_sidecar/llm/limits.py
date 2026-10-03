"""Triple rate limiter — RPM, RPD and TPM (REQ-LLM-01).

Tracks requests per minute, requests per day, and tokens per minute. Tokens are
estimated before sending (input) and reconciled with ``usage.total_tokens``
after the response. A job that would exceed the remaining TPM of the current
minute is skipped pre-flight so the chain can hop to the next provider without
ever emitting an HTTP 429.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars / 4). Used pre-flight for TPM budgeting.

    This is deliberately cheap and conservative. Exact counts come back in the
    provider's ``usage.total_tokens`` and are reconciled by the limiter.
    """
    if not text:
        return 0
    # Non-ASCII text is denser; use a slightly larger divisor for CJK-ish text.
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    if non_ascii > len(text) * 0.5:
        return max(1, len(text) // 2)
    return max(1, len(text) // 4)


class ProviderRateLimiter:
    """Sliding-window limiter for one provider (thread-safe)."""

    def __init__(self, rpm: int = 0, rpd: int = 0, tpm: int = 0) -> None:
        self.rpm = max(0, int(rpm))     # requests per minute (0 = unlimited)
        self.rpd = max(0, int(rpd))     # requests per day   (0 = unlimited)
        self.tpm = max(0, int(tpm))     # tokens per minute  (0 = unlimited)
        self._lock = threading.Lock()
        self._requests: Deque[float] = deque()           # minute window timestamps
        self._daily_requests: Deque[float] = deque()     # day window timestamps
        self._tokens: Deque[Tuple[float, int]] = deque()  # (timestamp, tokens)

    def _prune(self, now: float) -> None:
        minute_ago = now - 60.0
        day_ago = now - 86400.0
        while self._requests and self._requests[0] < minute_ago:
            self._requests.popleft()
        while self._daily_requests and self._daily_requests[0] < day_ago:
            self._daily_requests.popleft()
        while self._tokens and self._tokens[0][0] < minute_ago:
            self._tokens.popleft()

    def can_accept(self, estimated_tokens: int = 0) -> bool:
        """True if the provider can accept a request right now."""
        with self._lock:
            now = time.time()
            self._prune(now)
            if self.rpm and len(self._requests) >= self.rpm:
                return False
            if self.rpd and len(self._daily_requests) >= self.rpd:
                return False
            if self.tpm and estimated_tokens > 0:
                used_tokens = sum(t for _, t in self._tokens)
                if used_tokens + estimated_tokens > self.tpm:
                    return False
            return True

    def record_request(self) -> None:
        """Record that a request was dispatched (RPM/RPD accounting)."""
        with self._lock:
            now = time.time()
            self._prune(now)
            self._requests.append(now)
            self._daily_requests.append(now)

    def try_accept_and_record(self, estimated_tokens: int = 0) -> bool:
        """Atomically check capacity and, if allowed, record the dispatch.

        Replaces the separate ``can_accept`` + ``record_request`` calls, which
        formed a check-then-act race across concurrent HTTP threads and allowed
        the limiter to overshoot its RPM/RPD/TPM budget (3.6).
        """
        with self._lock:
            now = time.time()
            self._prune(now)
            if self.rpm and len(self._requests) >= self.rpm:
                return False
            if self.rpd and len(self._daily_requests) >= self.rpd:
                return False
            if self.tpm and estimated_tokens > 0:
                used_tokens = sum(t for _, t in self._tokens)
                if used_tokens + estimated_tokens > self.tpm:
                    return False
            self._requests.append(now)
            self._daily_requests.append(now)
            return True

    def record_tokens(self, tokens: int) -> None:
        """Record reconciled token usage (TPM accounting)."""
        if tokens <= 0:
            return
        with self._lock:
            now = time.time()
            self._prune(now)
            self._tokens.append((now, int(tokens)))

    def remaining_tpm(self) -> Optional[int]:
        """Remaining TPM in the current minute, or None when unlimited."""
        with self._lock:
            now = time.time()
            self._prune(now)
            if not self.tpm:
                return None
            used = sum(t for _, t in self._tokens)
            return max(0, self.tpm - used)

    def snapshot(self) -> Dict[str, int]:
        """Return current counters for the Web Studio dashboard."""
        with self._lock:
            now = time.time()
            self._prune(now)
            used_tokens = sum(t for _, t in self._tokens)
        return {
            "requests_last_minute": len(self._requests),
            "requests_last_day": len(self._daily_requests),
            "tokens_last_minute": used_tokens,
            "rpm_limit": self.rpm,
            "rpd_limit": self.rpd,
            "tpm_limit": self.tpm,
        }
