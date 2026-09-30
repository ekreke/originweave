"""Resilience wrapper around a :class:`SearchProvider` (retry + circuit breaker).

Wraps any search provider so a flaky or rate-limited endpoint cannot fail a run
outright: transient :class:`ProviderError` calls are retried with **exponential
backoff and full jitter**, and repeated failures **trip a process-wide breaker**
that short-circuits further calls to :class:`SearchUnavailableError` until a
cooldown elapses.

The breaker state lives on the wrapper instance, which ``build_search`` creates
once per server process and shares across runs (see ``capabilities/__init__.py``):
a rate limit is a global condition, so one run's failures should stop the others
from hammering the same endpoint. The provider choice stays inside the wrapper
(red line 5); callers see the same ``SearchProvider`` interface.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable, Coroutine
from typing import Any

from .base import ProviderError, SearchProvider, SearchUnavailableError

# ``sleep``/``clock``/``rng`` are injectable so tests run deterministically without
# real delays (the repo injects fakes rather than hitting the network).
_Sleep = Callable[[float], Coroutine[Any, Any, None]]


class ResilientSearch:
    """Retry + circuit-breaker decorator implementing :class:`SearchProvider`."""

    def __init__(
        self,
        provider: SearchProvider,
        *,
        max_attempts: int = 3,
        backoff: float = 1.0,
        backoff_max: float = 30.0,
        breaker_threshold: int = 3,
        breaker_cooldown: float = 60.0,
        sleep: _Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: Callable[[], float] = random.random,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if breaker_threshold < 1:
            raise ValueError("breaker_threshold must be >= 1")
        self._provider = provider
        self.name = provider.name
        self._max_attempts = max_attempts
        self._backoff = backoff
        self._backoff_max = backoff_max
        self._breaker_threshold = breaker_threshold
        self._breaker_cooldown = breaker_cooldown
        self._sleep = sleep
        self._clock = clock
        self._rng = rng
        self._lock = asyncio.Lock()
        self._failures = 0
        self._open_until = 0.0
        # Incremented every time the breaker opens. A call records the generation it
        # started under and only resets the breaker on success if it is unchanged, so a
        # slow in-flight success cannot close a breaker that tripped meanwhile.
        self._generation = 0

    async def search(self, query: str, *, num_results: int = 8) -> str:
        """Search ``query``, retrying transient failures and honouring the breaker."""
        generation = await self._before_call()
        attempt = 0
        while True:
            attempt += 1
            try:
                text = await self._provider.search(query, num_results=num_results)
            except ProviderError:
                if attempt >= self._max_attempts:
                    await self._record_failure()
                    raise
                await self._sleep(self._delay(attempt))
                continue
            await self._record_success(generation)
            return text

    def _delay(self, attempt: int) -> float:
        """Exponential backoff (base * 2^(n-1), capped) with full jitter."""
        capped: float = min(self._backoff * (2 ** (attempt - 1)), self._backoff_max)
        jitter: float = self._rng()
        return capped * jitter

    async def _before_call(self) -> int:
        """Return the current breaker generation, or raise if the breaker is open."""
        async with self._lock:
            if self._failures >= self._breaker_threshold and self._clock() < self._open_until:
                remaining = self._open_until - self._clock()
                raise SearchUnavailableError(
                    f"search circuit breaker open; retry in {remaining:.1f}s"
                )
            return self._generation

    async def _record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._failures >= self._breaker_threshold:
                if self._clock() >= self._open_until:
                    # (Re)open: bump the generation so stale in-flight successes cannot
                    # close it.
                    self._generation += 1
                self._open_until = self._clock() + self._breaker_cooldown

    async def _record_success(self, generation: int) -> None:
        async with self._lock:
            if generation != self._generation:
                # The breaker was (re)opened while this call was in flight; leave it.
                return
            self._failures = 0
            self._open_until = 0.0


__all__ = ["ResilientSearch"]
