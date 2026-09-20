"""Server context and dependency injection (M1c-1).

The service layer is constructed with a :class:`ServerContext` that carries the
project config, the resolved capabilities (worker/search/prompt) and the run /
project directories. Tests inject fake providers; production builds them from
``originweave.toml`` via :func:`originweave.capabilities.build_*`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import config as config_module
from ..blackboard import Board
from ..capabilities import (
    PromptProvider,
    SearchProvider,
    Worker,
    build_prompt,
    build_search,
    build_worker,
)
from ..config import Config
from ..persistence import ProjectRegistry
from ..store import RunStore

_log = logging.getLogger(__name__)


@dataclass
class Providers:
    """The capabilities one run's engine needs (red line 4: interchangeable)."""

    worker: Worker
    search: SearchProvider
    prompt: PromptProvider


def build_providers(cfg: Config) -> Providers:
    """Resolve the configured worker/search/prompt providers."""
    return Providers(
        worker=build_worker(cfg),
        search=build_search(cfg),
        prompt=build_prompt(cfg),
    )


@dataclass
class RunScheduler:
    """Owns the in-process background run tasks and their shared run stores (M1c-1).

    The server runs each ``Engine`` in an asyncio task instead of in the request
    coroutine, so ``CreateRun`` can return immediately. Every writer for one run --
    the background engine and ``AddHint`` -- must share the *same* :class:`RunStore`
    instance: ``append_event`` keeps a per-instance event count, so two instances
    would hand out colliding event ids. ``store_for`` is that single point of truth.

    This is the temporary in-process Dispatcher (``agent-design.md`` section 6); the
    container Dispatcher in M3 replaces the execution backend, not this interface.
    """

    runs_dir: Path
    _stores: dict[str, RunStore] = field(default_factory=dict, init=False)
    _tasks: dict[str, asyncio.Task[Board]] = field(default_factory=dict, init=False)

    def store_for(self, run_id: str) -> RunStore:
        """Return the cached store for ``run_id`` (created on first use)."""
        store = self._stores.get(run_id)
        if store is None:
            store = RunStore(self.runs_dir / run_id)
            self._stores[run_id] = store
        return store

    def start(self, run_id: str, coro: Awaitable[Board]) -> asyncio.Task[Board]:
        """Schedule ``coro`` as a background task, tracked per run."""
        task = asyncio.ensure_future(coro)
        task.set_name(f"run:{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(self._on_done)
        return task

    def _on_done(self, task: asyncio.Task[Board]) -> None:
        # Drop the finished task (and its store) so long-lived servers do not grow
        # either table. A later write RPC re-caches a fresh store for the run.
        run_id = task.get_name().removeprefix("run:")
        self._tasks.pop(run_id, None)
        self._stores.pop(run_id, None)
        # Retrieve the exception so asyncio never warns about an unretrieved one; the
        # engine reports failures on the board (FAILED), so this is a defensive log.
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _log.warning("run %s task failed: %s", run_id, exc)

    async def wait(self, run_id: str) -> None:
        """Wait for one run's background task to finish (no-op if untracked)."""
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def drain(self) -> None:
        """Wait for every tracked task (server shutdown / test teardown)."""
        if self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)


@dataclass
class ServerContext:
    """Everything the service needs, resolved once at app startup."""

    config: Config
    providers: Providers
    runs_dir: Path
    projects_dir: Path
    scheduler: RunScheduler
    # The ``originweave.toml`` UpdateSettings writes back to; derived from ``root``.
    config_path: Path = Path(config_module.CONFIG_FILENAME)
    # Rebuilds providers after UpdateSettings; tests inject a fake factory.
    providers_factory: Callable[[Config], Providers] = build_providers
    # ``originweave ui --run <dir>``: serve only this one run, read-only (C4).
    pinned_run: Path | None = None

    def apply_settings(self, config: Config) -> None:
        """Replace the live config and rebuild providers for subsequent runs.

        Providers are rebuilt *before* the swap so a factory failure leaves the
        context untouched. Running engines keep the providers they were built with;
        only new runs (and new ``CreateRun`` / ``SubmitHumanInput`` resumes) observe
        the change.
        """
        providers = self.providers_factory(config)
        self.config = config
        self.providers = providers

    @classmethod
    def build(
        cls,
        *,
        config: Config | None = None,
        providers: Providers | None = None,
        root: Path | None = None,
        run_dir: Path | None = None,
        config_path: Path | None = None,
        providers_factory: Callable[[Config], Providers] | None = None,
    ) -> ServerContext:
        """Resolve config/providers and the run + project directories.

        ``root`` is the base for the relative ``[run].dir`` / ``[project].dir``
        paths (defaults to the current working directory). ``run_dir`` pins the
        server to a single run directory (relative paths resolve against ``root``).
        ``config_path`` overrides where ``UpdateSettings`` writes (defaults to
        ``<root>/originweave.toml``).
        """
        cfg = config if config is not None else config_module.load()
        base = Path.cwd() if root is None else Path(root)
        runs_dir = base / cfg.run.dir
        pinned = None
        if run_dir is not None:
            candidate = Path(run_dir)
            pinned = (candidate if candidate.is_absolute() else base / candidate).resolve()
        resolved_config_path = (
            config_path if config_path is not None else base / config_module.CONFIG_FILENAME
        )
        if providers_factory is not None:
            resolved_factory = providers_factory
        elif providers is not None:
            # Keep injected (test) providers across UpdateSettings instead of swapping
            # them for the production build, which would silently drop the fakes.
            injected = providers

            def resolved_factory(_config: Config) -> Providers:
                return injected

        else:
            resolved_factory = build_providers
        return cls(
            config=cfg,
            providers=providers if providers is not None else resolved_factory(cfg),
            runs_dir=runs_dir,
            projects_dir=base / cfg.project.dir,
            scheduler=RunScheduler(runs_dir=runs_dir),
            config_path=resolved_config_path,
            providers_factory=resolved_factory,
            pinned_run=pinned,
        )

    @property
    def registry(self) -> ProjectRegistry:
        return ProjectRegistry(self.projects_dir, self.runs_dir)
