"""Capability abstractions: stable interfaces for external services.

A *capability* is an externally-backed operation (search, prompt retrieval,
model completion). Concrete *providers* implement these protocols and are
interchangeable. Keeping the interfaces provider-agnostic lets orchestration stay
decoupled from any specific SDK (see ``docs/overview/agent-design.md``).

All capability calls are asynchronous and hit real services; credentials (when
needed) are read from environment variables only. Tests inject fakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class CapabilityError(RuntimeError):
    """Base class for capability failures."""


class MissingCredentialError(CapabilityError):
    """Raised when a provider needs a credential that is not configured."""


class ProviderUnavailableError(CapabilityError):
    """Raised when a provider exists but is not implemented yet."""


class ProviderError(CapabilityError):
    """Raised when a provider call fails (transport, status, or malformed body)."""


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    text: str
    version: str | None = None


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, num_results: int = 8) -> str:
        """Return a text context for ``query`` (results formatted for a model)."""
        ...


@runtime_checkable
class PromptProvider(Protocol):
    name: str

    async def get(self, name: str) -> PromptTemplate:
        """Return the named prompt template."""
        ...


__all__ = [
    "CapabilityError",
    "MissingCredentialError",
    "PromptProvider",
    "PromptTemplate",
    "ProviderError",
    "ProviderUnavailableError",
    "SearchProvider",
]
