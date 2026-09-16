"""Prompt capability providers.

``local`` reads templates from a repository directory (``prompts/`` by default).
``langfuse`` is a credentialed stub until M3; credentials come from env vars.
"""

from __future__ import annotations

import os
from pathlib import Path

from .base import MissingCredentialError, PromptTemplate, ProviderUnavailableError

LANGFUSE_ENV_VARS: tuple[str, ...] = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")

_SUFFIXES: tuple[str, ...] = (".txt", ".md")


class LocalPrompt:
    name = "local"

    def __init__(self, directory: str | os.PathLike[str] = "prompts") -> None:
        self._directory = Path(directory)

    @property
    def directory(self) -> Path:
        return self._directory

    def get(self, name: str) -> PromptTemplate:
        for suffix in _SUFFIXES:
            candidate = self._directory / f"{name}{suffix}"
            if candidate.is_file():
                text = candidate.read_text(encoding="utf-8").strip()
                return PromptTemplate(name=name, text=text)
        raise FileNotFoundError(f"prompt template {name!r} not found in {self._directory}")


class LangfusePrompt:
    name = "langfuse"

    def __init__(self) -> None:
        self._missing = [var for var in LANGFUSE_ENV_VARS if not os.environ.get(var)]

    def get(self, name: str) -> PromptTemplate:
        if self._missing:
            raise MissingCredentialError(f"missing env vars: {', '.join(self._missing)}")
        raise ProviderUnavailableError(
            "live langfuse prompts are not implemented until M3; "
            "use the local prompt provider for now"
        )
