"""LLM orchestration layer for the Sensewright sidecar."""
from __future__ import annotations

from .base import (
    LLMError, LLMJob, LLMNetworkError, LLMProviderError, LLMRateLimited,
    LLMResult, LLMTimeout, ProviderResponse,
)
from .chain import ProviderChain
from .context import ContextAssembler
from .limits import ProviderRateLimiter, estimate_tokens
from .router import ModelRouter
from .scheduler import LLMScheduler, get_scheduler

__all__ = [
    "LLMError", "LLMJob", "LLMNetworkError", "LLMProviderError",
    "LLMRateLimited", "LLMResult", "LLMTimeout", "ProviderResponse",
    "ProviderChain", "ContextAssembler", "ProviderRateLimiter", "estimate_tokens",
    "ModelRouter", "LLMScheduler", "get_scheduler",
]


def run_purpose(purpose_id, context=None, lang="", trace_id=None, timeout=None):
    """Convenience wrapper: run a purpose synchronously via the shared scheduler."""
    return get_scheduler().run_purpose(purpose_id, context, lang, trace_id, timeout)
