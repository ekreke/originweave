"""Capability registry: resolve provider names to implementations.

Provider names are validated against the allowed sets from
:mod:`originweave.config`. Unknown names raise :class:`CapabilityError` with the
list of valid options. Providers call real services; tests inject fakes.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from ..config import (
    ALLOWED_MODEL_PROVIDERS,
    ALLOWED_PROMPT_PROVIDERS,
    ALLOWED_SEARCH_PROVIDERS,
    ALLOWED_WORKER_PROVIDERS,
    Config,
)
from .base import (
    CapabilityError,
    MissingCredentialError,
    PromptProvider,
    PromptTemplate,
    ProviderError,
    ProviderUnavailableError,
    SearchProvider,
)
from .model import ChatMessage, ModelProvider, OpenAIModel
from .prompt import LANGFUSE_ENV_VARS, LangfusePrompt, LocalPrompt
from .search import ENV_VARS, ExaSearch, ParallelSearch, credential_env
from .worker import LocalWorker, Worker, WorkerReply, WorkerStep

SEARCH_PROVIDERS: dict[str, Callable[[], SearchProvider]] = {
    "exa": ExaSearch,
    "parallel": ParallelSearch,
}

PROMPT_PROVIDERS: dict[str, Callable[[Path], PromptProvider]] = {
    "local": lambda directory: LocalPrompt(directory),
    "langfuse": lambda directory: LangfusePrompt(),
}

MODEL_PROVIDERS: dict[str, Callable[[str, str], ModelProvider]] = {
    "openai": lambda model, base_url: OpenAIModel(model=model, base_url=base_url),
}

WORKER_PROVIDERS: frozenset[str] = ALLOWED_WORKER_PROVIDERS


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


def get_model(name: str, *, model: str, base_url: str) -> ModelProvider:
    """Instantiate the model provider ``name``."""
    if name not in ALLOWED_MODEL_PROVIDERS:
        raise CapabilityError(
            f"unknown model provider {name!r}; expected one of {sorted(MODEL_PROVIDERS)}"
        )
    return MODEL_PROVIDERS[name](model, base_url)


def build_search(config: Config) -> SearchProvider:
    """Resolve the configured search provider."""
    return get_search(config.capability.search.provider)


def build_prompt(config: Config) -> PromptProvider:
    """Resolve the configured prompt provider."""
    return get_prompt(
        config.capability.prompt.provider,
        directory=config.capability.prompt.directory,
    )


def build_model(config: Config) -> ModelProvider:
    """Resolve the configured model provider."""
    return get_model(
        config.capability.model.provider,
        model=config.capability.model.model,
        base_url=config.capability.model.base_url,
    )


def build_worker(config: Config) -> Worker:
    """Resolve the configured worker provider (M6)."""
    provider = config.worker.provider
    if provider not in ALLOWED_WORKER_PROVIDERS:
        raise CapabilityError(
            f"unknown worker provider {provider!r}; expected one of {sorted(WORKER_PROVIDERS)}"
        )
    if provider == "local":
        return LocalWorker(model=build_model(config))
    # provider == "pi"
    raise ProviderUnavailableError(
        "the pi worker provider is not implemented yet (M6 P2); use provider = 'local'"
    )


__all__ = [
    "ENV_VARS",
    "LANGFUSE_ENV_VARS",
    "MODEL_PROVIDERS",
    "PROMPT_PROVIDERS",
    "SEARCH_PROVIDERS",
    "WORKER_PROVIDERS",
    "CapabilityError",
    "ChatMessage",
    "LocalWorker",
    "MissingCredentialError",
    "ModelProvider",
    "OpenAIModel",
    "PromptProvider",
    "PromptTemplate",
    "ProviderError",
    "ProviderUnavailableError",
    "SearchProvider",
    "Worker",
    "WorkerReply",
    "WorkerStep",
    "build_model",
    "build_prompt",
    "build_search",
    "build_worker",
    "credential_env",
    "get_model",
    "get_prompt",
    "get_search",
]
