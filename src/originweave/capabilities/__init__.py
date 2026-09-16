"""Capability registry: resolve provider names to implementations.

Provider names are validated against the allowed sets from
:mod:`originweave.config`. Unknown names raise :class:`CapabilityError` with the
list of valid options.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from ..config import ALLOWED_PROMPT_PROVIDERS, ALLOWED_SEARCH_PROVIDERS, Config
from .base import (
    CacheMissError,
    CapabilityError,
    MissingCredentialError,
    PromptProvider,
    PromptTemplate,
    ProviderUnavailableError,
    SearchProvider,
    SearchResult,
)
from .cache import ResponseCache, request_key
from .prompt import LANGFUSE_ENV_VARS, LangfusePrompt, LocalPrompt
from .record import CachedPrompt, CachedSearch, RecordingPrompt, RecordingSearch
from .search import ENV_VARS, ExaSearch, ParallelSearch, credential_env

SEARCH_PROVIDERS: dict[str, Callable[[], SearchProvider]] = {
    "exa": ExaSearch,
    "parallel": ParallelSearch,
}

PROMPT_PROVIDERS: dict[str, Callable[[Path], PromptProvider]] = {
    "local": lambda directory: LocalPrompt(directory),
    "langfuse": lambda directory: LangfusePrompt(),
}


def get_search(name: str) -> SearchProvider:
    """Instantiate the search provider ``name``."""
    if name not in ALLOWED_SEARCH_PROVIDERS:
        raise CapabilityError(
            f"unknown search provider {name!r}; expected one of {sorted(SEARCH_PROVIDERS)}"
        )
    return SEARCH_PROVIDERS[name]()


def get_prompt(name: str, *, directory: str | os.PathLike[str] = "prompts") -> PromptProvider:
    """Instantiate the prompt provider ``name``."""
    if name not in ALLOWED_PROMPT_PROVIDERS:
        raise CapabilityError(
            f"unknown prompt provider {name!r}; expected one of {sorted(PROMPT_PROVIDERS)}"
        )
    return PROMPT_PROVIDERS[name](Path(directory))


def build_search(config: Config, cache: ResponseCache) -> SearchProvider:
    """Resolve the configured search provider, wired for live calls or replay.

    When ``config.live.enabled`` is true the provider is called live and every
    response is recorded; otherwise responses are replayed from ``cache`` and no
    network access happens.
    """
    provider = get_search(config.capability.search.provider)
    if config.live.enabled:
        return RecordingSearch(provider, cache)
    return CachedSearch(provider.name, cache)


def build_prompt(config: Config, cache: ResponseCache) -> PromptProvider:
    """Resolve the configured prompt provider, wired for live calls or replay."""
    provider = get_prompt(
        config.capability.prompt.provider,
        directory=config.capability.prompt.directory,
    )
    if config.live.enabled:
        return RecordingPrompt(provider, cache)
    return CachedPrompt(provider.name, cache)


__all__ = [
    "ENV_VARS",
    "LANGFUSE_ENV_VARS",
    "PROMPT_PROVIDERS",
    "SEARCH_PROVIDERS",
    "CacheMissError",
    "CachedPrompt",
    "CachedSearch",
    "CapabilityError",
    "MissingCredentialError",
    "PromptProvider",
    "PromptTemplate",
    "ProviderUnavailableError",
    "RecordingPrompt",
    "RecordingSearch",
    "ResponseCache",
    "SearchProvider",
    "SearchResult",
    "build_prompt",
    "build_search",
    "credential_env",
    "get_prompt",
    "get_search",
    "request_key",
]
