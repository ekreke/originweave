"""Model capability: an OpenAI-compatible chat completions provider.

``complete`` returns the **raw assistant text**; parsing structured output and
mapping it onto the blackboard (Fact/Intent) is the orchestration layer's job
(M1). Credentials are read from environment variables only: ``OPENAI_API_KEY``,
with an optional ``OPENAI_BASE_URL`` overriding the configured ``base_url``.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from .base import MissingCredentialError, ProviderError

ENV_VAR = "OPENAI_API_KEY"
BASE_URL_ENV_VAR = "OPENAI_BASE_URL"
TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class Usage:
    """Token usage reported by an OpenAI-compatible endpoint (M3b)."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ModelResult(str):
    """The assistant text, optionally carrying token ``usage`` (M3b).

    A ``str`` subclass so ``ModelProvider.complete`` keeps its ``-> str`` contract --
    plain-string test fakes stay valid -- while attaching usage to the *value*. This is
    concurrency-safe: I4 runs several Worker passes against one shared provider, so
    usage must not live on the provider instance.
    """

    usage: Usage | None

    def __new__(cls, text: str, *, usage: Usage | None = None) -> ModelResult:
        result = super().__new__(cls, text)
        result.usage = usage
        return result


@runtime_checkable
class ModelProvider(Protocol):
    name: str

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        """Return the assistant's raw text for ``messages``."""
        ...


def _extract_usage(payload: object) -> Usage | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("usage")
    if not isinstance(raw, dict):
        return None
    prompt = raw.get("prompt_tokens")
    completion = raw.get("completion_tokens")
    total = raw.get("total_tokens")
    if not (isinstance(prompt, int) and isinstance(completion, int) and isinstance(total, int)):
        return None
    return Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


def _extract_content(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None


class OpenAIModel:
    name = "openai"

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._base_url = (os.environ.get(BASE_URL_ENV_VAR) or base_url).rstrip("/")
        self._api_key = api_key if api_key is not None else os.environ.get(ENV_VAR)
        self._client = client

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        if not self._api_key:
            raise MissingCredentialError(f"{ENV_VAR} is not set")
        if not self._base_url:
            raise MissingCredentialError(f"{BASE_URL_ENV_VAR} is not set")
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        client = self._client
        owned = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        try:
            try:
                response = await client.post(
                    f"{self._base_url}/chat/completions", headers=headers, json=body
                )
            except httpx.HTTPError as exc:
                raise ProviderError(f"{self.name} completion failed: {exc}") from exc
            if response.status_code >= 400:
                raise ProviderError(f"{self.name} completion returned HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderError(f"{self.name} returned a non-JSON body") from exc
        finally:
            if owned:
                await client.aclose()
        content = _extract_content(payload)
        if content is None:
            raise ProviderError(f"{self.name} returned no assistant content")
        return ModelResult(content, usage=_extract_usage(payload))


__all__ = [
    "BASE_URL_ENV_VAR",
    "ChatMessage",
    "ENV_VAR",
    "ModelProvider",
    "ModelResult",
    "OpenAIModel",
    "TIMEOUT_SECONDS",
    "Usage",
]
