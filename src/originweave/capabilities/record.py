"""Recording and replay wrappers around capability providers.

``Recording*`` calls the inner provider and persists the response; ``Cached*``
replays a previously recorded response without touching the network. This is how
``LIVE=0`` stays offline and how a run remains byte-reproducible.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from .base import CacheMissError, PromptProvider, PromptTemplate, SearchProvider, SearchResult
from .cache import ResponseCache


def _result_from_record(item: Any) -> SearchResult:
    if not isinstance(item, Mapping):
        raise CacheMissError("malformed recorded search result")
    published = item.get("published")
    return SearchResult(
        title=str(item.get("title", "")),
        url=str(item.get("url", "")),
        snippet=str(item.get("snippet", "")),
        published=None if published is None else str(published),
    )


class RecordingSearch:
    """Run a search live and record the response to the cache."""

    def __init__(self, inner: SearchProvider, cache: ResponseCache) -> None:
        self.name = inner.name
        self._inner = inner
        self._cache = cache

    def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        params = {"query": query, "limit": limit}
        results = self._inner.search(query, limit=limit)
        self._cache.write(self.name, "search", params, [asdict(r) for r in results])
        return results


class CachedSearch:
    """Replay a recorded search response, raising on a cache miss."""

    def __init__(self, provider: str, cache: ResponseCache) -> None:
        self.name = provider
        self._cache = cache

    def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        params = {"query": query, "limit": limit}
        record = self._cache.read(self.name, "search", params)
        if record is None:
            raise CacheMissError(
                f"no recorded response for {self.name} search: {query!r} (limit={limit})"
            )
        raw = record.get("response")
        if not isinstance(raw, list):
            raise CacheMissError(f"malformed recorded response for {self.name} search")
        return [_result_from_record(item) for item in raw]


class RecordingPrompt:
    """Resolve a prompt and record the response to the cache."""

    def __init__(self, inner: PromptProvider, cache: ResponseCache) -> None:
        self.name = inner.name
        self._inner = inner
        self._cache = cache

    def get(self, name: str) -> PromptTemplate:
        params = {"name": name}
        template = self._inner.get(name)
        self._cache.write(self.name, "prompt", params, asdict(template))
        return template


class CachedPrompt:
    """Replay a recorded prompt response, raising on a cache miss."""

    def __init__(self, provider: str, cache: ResponseCache) -> None:
        self.name = provider
        self._cache = cache

    def get(self, name: str) -> PromptTemplate:
        params = {"name": name}
        record = self._cache.read(self.name, "prompt", params)
        if record is None:
            raise CacheMissError(f"no recorded response for {self.name} prompt: {name!r}")
        raw = record.get("response")
        if not isinstance(raw, Mapping):
            raise CacheMissError(f"malformed recorded response for {self.name} prompt")
        version = raw.get("version")
        return PromptTemplate(
            name=str(raw.get("name", name)),
            text=str(raw.get("text", "")),
            version=None if version is None else str(version),
        )
