"""LLM provider protocol and base types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# Accepted reasoning-effort values (OpenAI-compatible ``reasoning.effort``).
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high")


def normalize_reasoning_effort(value: Any) -> str | None:
    """Normalize a reasoning-effort setting to a known value (or ``None``).

    ``None``/empty/unknown means "do not send an explicit reasoning hint".
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in ("default", "off", "false", "auto"):
        return None
    if text == "min":
        text = "minimal"
    return text if text in REASONING_EFFORTS else None


@dataclass(frozen=True)
class LLMToolCall:
    """A single tool/function call requested by an LLM provider."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    """Normalized response from an LLM provider."""

    text: str
    provider: str
    model: str
    raw: dict[str, Any]
    tool_calls: tuple[LLMToolCall, ...] = ()


class LLMError(Exception):
    """Base exception for LLM provider errors.

    ``status`` carries the HTTP status code when the error came from a provider
    response, so callers can tell auth failures (401/403) from model-level
    errors (400/404/429) and decide whether to try another model/provider.
    """

    def __init__(self, message: str, provider: str, retryable: bool = True, status: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.status = status


class AllProvidersFailed(LLMError):
    """Raised when all providers in the chain have failed."""

    def __init__(self, message: str, failed_providers: list[str]):
        super().__init__(message, provider="chain", retryable=False)
        self.failed_providers = failed_providers


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers."""

    name: str

    @property
    def available(self) -> bool:
        """Return True if the provider is configured and ready to use."""
        ...

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        """Complete a chat conversation.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            temperature: Sampling temperature (0.0-2.0).
            max_tokens: Maximum tokens in response.
            tools: Optional OpenAI-style tool schemas to expose to the model.
            reasoning_effort: Optional hidden-reasoning budget hint
                (none|minimal|low|medium|high); ignored by providers that do not
                support it.

        Returns:
            LLMResponse with the generated text and metadata.

        Raises:
            LLMError: On provider-specific errors.
        """
        ...