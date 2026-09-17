"""Search capability providers backed by public MCP search endpoints.

Mirrors the free, key-less web search used by opencode: a JSON-RPC
``tools/call`` over HTTP against ``https://mcp.exa.ai/mcp`` (default) or
``https://search.parallel.ai/mcp``. ``EXA_API_KEY`` / ``PARALLEL_API_KEY`` are
**optional** — when present they are attached (query param / bearer token) so
callers can use a paid quota; the endpoints work without them.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from urllib.parse import quote

import httpx

from .base import ProviderError

EXA_URL = "https://mcp.exa.ai/mcp"
PARALLEL_URL = "https://search.parallel.ai/mcp"

ENV_VARS: dict[str, str] = {
    "exa": "EXA_API_KEY",
    "parallel": "PARALLEL_API_KEY",
}

TIMEOUT_SECONDS = 25.0
MAX_RESPONSE_BYTES = 256 * 1024


def _user_agent() -> str:
    try:
        return f"originweave/{version('originweave')}"
    except PackageNotFoundError:
        return "originweave/0.0.0"


def _extract_text(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    content = result.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str) and text:
                return text
    return None


def parse_response(body: str) -> str | None:
    """Parse a JSON-RPC response, accepting plain JSON or SSE ``data:`` frames."""
    stripped = body.strip()
    if stripped:
        try:
            direct = _extract_text(json.loads(stripped))
        except json.JSONDecodeError:
            direct = None
        if direct:
            return direct
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            frame = _extract_text(json.loads(line[len("data: ") :]))
        except json.JSONDecodeError:
            continue
        if frame:
            return frame
    return None


class _McpSearch:
    """Shared MCP-over-HTTP search call."""

    name: str
    env_var: str
    url: str
    tool: str

    def __init__(
        self, api_key: str | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get(self.env_var)
        self._client = client

    def _request_url(self) -> str:
        return self.url

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json, text/event-stream", "User-Agent": _user_agent()}

    def _arguments(self, query: str, num_results: int) -> dict[str, Any]:
        raise NotImplementedError

    async def _fetch(self, client: httpx.AsyncClient, body: Mapping[str, Any]) -> str:
        """POST the JSON-RPC body, bounding the response as it streams in."""
        chunks: list[bytes] = []
        try:
            async with client.stream(
                "POST", self._request_url(), headers=self._headers(), json=body
            ) as response:
                if response.status_code >= 400:
                    raise ProviderError(
                        f"{self.name} search returned HTTP {response.status_code}"
                    )
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise ProviderError(
                            f"{self.name} response exceeded {MAX_RESPONSE_BYTES} bytes"
                        )
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} search failed: {exc}") from exc

        text = parse_response(b"".join(chunks).decode("utf-8", errors="replace"))
        if text is None:
            raise ProviderError(f"{self.name} search returned no usable result")
        return text

    async def search(self, query: str, *, num_results: int = 8) -> str:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": self.tool,
                "arguments": self._arguments(query, num_results),
            },
        }
        client = self._client
        owned = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                return await self._fetch(client, body)
        except TimeoutError as exc:
            raise ProviderError(f"{self.name} search timed out") from exc
        finally:
            if owned:
                await client.aclose()


class ExaSearch(_McpSearch):
    name = "exa"
    env_var = ENV_VARS["exa"]
    url = EXA_URL
    tool = "web_search_exa"

    def _request_url(self) -> str:
        if not self._api_key:
            return EXA_URL
        return f"{EXA_URL}?exaApiKey={quote(self._api_key, safe='')}"

    def _arguments(self, query: str, num_results: int) -> dict[str, Any]:
        return {
            "query": query,
            "type": "auto",
            "numResults": num_results,
            "livecrawl": "fallback",
        }


class ParallelSearch(_McpSearch):
    name = "parallel"
    env_var = ENV_VARS["parallel"]
    url = PARALLEL_URL
    tool = "web_search"

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _arguments(self, query: str, num_results: int) -> dict[str, Any]:
        return {"objective": query, "search_queries": [query]}


def credential_env(name: str) -> str | None:
    """Return the environment variable backing ``name``, if any."""
    return ENV_VARS.get(name)


__all__ = [
    "ENV_VARS",
    "EXA_URL",
    "MAX_RESPONSE_BYTES",
    "PARALLEL_URL",
    "TIMEOUT_SECONDS",
    "ExaSearch",
    "ParallelSearch",
    "credential_env",
    "parse_response",
]
