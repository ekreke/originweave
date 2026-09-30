from __future__ import annotations

import asyncio
from typing import Any

import pytest

from originweave.capabilities.base import (
    MissingCredentialError,
    ProviderError,
    SearchUnavailableError,
)
from originweave.capabilities.resilience import ResilientSearch


def test_rejects_invalid_construction() -> None:
    provider = _FakeSearch(["ok"])
    with pytest.raises(ValueError):
        ResilientSearch(provider, max_attempts=0)
    with pytest.raises(ValueError):
        ResilientSearch(provider, breaker_threshold=0)


class _FakeSearch:
    name = "fake"

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.calls = 0

    async def search(self, query: str, *, num_results: int = 8) -> str:
        self.calls += 1
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _recorder() -> tuple[list[float], Any]:
    delays: list[float] = []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    return delays, sleep


async def test_retries_transient_then_succeeds() -> None:
    delays, sleep = _recorder()
    provider = _FakeSearch([ProviderError("boom"), ProviderError("boom"), "ok"])
    search = ResilientSearch(provider, max_attempts=3, backoff=1.0, rng=lambda: 1.0, sleep=sleep)

    assert await search.search("q") == "ok"
    assert provider.calls == 3
    # Two backoff waits: 1s then 2s (rng pinned to 1.0 → no jitter loss).
    assert delays == [1.0, 2.0]


async def test_exhausts_attempts_and_raises() -> None:
    _, sleep = _recorder()
    provider = _FakeSearch([ProviderError("boom")] * 3)
    search = ResilientSearch(provider, max_attempts=3, rng=lambda: 1.0, sleep=sleep)

    with pytest.raises(ProviderError):
        await search.search("q")
    assert provider.calls == 3


async def test_breaker_opens_after_threshold() -> None:
    _, sleep = _recorder()
    provider = _FakeSearch([ProviderError("boom"), ProviderError("boom")])
    search = ResilientSearch(
        provider, max_attempts=1, breaker_threshold=2, breaker_cooldown=60.0, sleep=sleep
    )

    with pytest.raises(ProviderError):
        await search.search("q")
    with pytest.raises(ProviderError):
        await search.search("q")
    # Breaker is now open: the third call is short-circuited without touching the provider.
    with pytest.raises(SearchUnavailableError):
        await search.search("q")
    assert provider.calls == 2


async def test_breaker_half_open_probe_recovers() -> None:
    _, sleep = _recorder()
    now = [0.0]
    provider = _FakeSearch([ProviderError("boom"), "ok", "ok"])
    search = ResilientSearch(
        provider,
        max_attempts=1,
        breaker_threshold=1,
        breaker_cooldown=60.0,
        clock=lambda: now[0],
        sleep=sleep,
    )

    with pytest.raises(ProviderError):
        await search.search("q")
    with pytest.raises(SearchUnavailableError):
        await search.search("q")

    # After the cooldown a probe is allowed; success closes the breaker again.
    now[0] = 61.0
    assert await search.search("q") == "ok"
    assert await search.search("q") == "ok"


async def test_non_provider_error_is_not_retried() -> None:
    delays, sleep = _recorder()
    provider = _FakeSearch([MissingCredentialError("no key")])
    search = ResilientSearch(provider, max_attempts=3, sleep=sleep)

    with pytest.raises(MissingCredentialError):
        await search.search("q")
    assert provider.calls == 1
    assert delays == []


async def test_backoff_is_capped() -> None:
    delays, sleep = _recorder()
    provider = _FakeSearch([ProviderError("boom")] * 4)
    search = ResilientSearch(
        provider, max_attempts=4, backoff=1.0, backoff_max=4.0, rng=lambda: 1.0, sleep=sleep
    )

    with pytest.raises(ProviderError):
        await search.search("q")
    # 1, 2, 4, then capped at 4 — the last retry never sleeps (attempts exhausted).
    assert delays == [1.0, 2.0, 4.0]


async def test_in_flight_success_does_not_close_an_open_breaker() -> None:
    _, sleep = _recorder()
    release = asyncio.Event()

    class _GatedSearch:
        name = "gated"

        def __init__(self) -> None:
            self.calls = 0

        async def search(self, query: str, *, num_results: int = 8) -> str:
            self.calls += 1
            if self.calls == 1:
                await release.wait()
                return "late-ok"
            raise ProviderError("boom")

    provider = _GatedSearch()
    search = ResilientSearch(
        provider,
        max_attempts=1,
        breaker_threshold=2,
        breaker_cooldown=60.0,
        clock=lambda: 0.0,
        sleep=sleep,
    )

    # Start a call that will only finish after the breaker trips.
    in_flight = asyncio.create_task(search.search("q"))
    await asyncio.sleep(0)  # let it record its generation and block on the provider

    with pytest.raises(ProviderError):
        await search.search("q")
    with pytest.raises(ProviderError):
        await search.search("q")  # threshold reached -> breaker opens

    release.set()
    assert await in_flight == "late-ok"
    # The late success must not have closed the breaker.
    with pytest.raises(SearchUnavailableError):
        await search.search("q")

