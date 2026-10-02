"""Core LLM layer data types and exceptions."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class LLMError(Exception):
    """Base class for all LLM-layer failures."""


class LLMTimeout(LLMError):
    """The provider call exceeded the tier SLO."""


class LLMNetworkError(LLMError):
    """A network-level failure (connection reset, DNS, etc.)."""


class LLMProviderError(LLMError):
    """The provider returned a non-2xx or malformed response."""


class LLMRateLimited(LLMError):
    """The provider's rate limit was exceeded (pre-flight skip or HTTP 429)."""


@dataclass
class LLMJob:
    """A single unit of LLM work routed through the scheduler."""

    purpose_id: str
    tier: str
    context: Dict[str, Any]
    lang: str = ""
    trace_id: str = "-"
    sim_id: Optional[int] = None
    # dedup_key = player:save:scope:id:purpose (REQ-SCHED-03).
    dedup_key: str = ""
    created_wall: float = field(default_factory=time.time)
    retries: int = 0


@dataclass
class ProviderResponse:
    """A normalized response from a provider."""

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""


@dataclass
class LLMResult:
    """Result of running a purpose, with fallback provenance."""

    ok: bool
    data: Dict[str, Any]
    fallback: bool = False
    provider: Optional[str] = None
    model: Optional[str] = None
    error: Optional[str] = None
    latency_s: float = 0.0
