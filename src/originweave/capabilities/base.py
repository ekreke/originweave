"""Capability abstractions: stable interfaces for external services.

A *capability* is an externally-backed operation (search, prompt retrieval).
Concrete *providers* implement these protocols and are interchangeable. Keeping
the interfaces provider-agnostic lets orchestration stay decoupled from any
specific SDK (see ``docs/overview/agent-design.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class CapabilityError(RuntimeError):
    """Base class for capability failures."""


class MissingCredentialError(CapabilityError):
    """Raised when a provider needs a credential that is not configured."""


class ProviderUnavailableError(CapabilityError):
    """Raised when a provider exists but its live implementation is not ready."""


class CacheMissError(CapabilityError):
    """Raised when an offline replay finds no recorded response."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    published: str | None = None


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    text: str
    version: str | None = None


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        """Return up to ``limit`` results for ``query``."""
        ...


@runtime_checkable
class PromptProvider(Protocol):
    name: str

    def get(self, name: str) -> PromptTemplate:
        """Return the named prompt template."""
        ...
