"""Server context and dependency injection (M1c-1).

The service layer is constructed with a :class:`ServerContext` that carries the
project config, the resolved capabilities (worker/search/prompt) and the run /
project directories. Tests inject fake providers; production builds them from
``originweave.toml`` via :func:`originweave.capabilities.build_*`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import config as config_module
from ..blackboard import Board
from ..capabilities import (
    CapabilityError,
    PromptProvider,
    SearchProvider,
    Worker,
    build_prompt,
    build_search,
    build_worker,
)
from ..capabilities.model import BASE_URL_ENV_VAR, ENV_VAR
from ..config import Config
from ..persistence import ProjectRegistry
from ..runtime import ContainerManager, ContainerWorker, RunContainerWorker
from ..runtime.container import ENV_BASE_URL, ENV_MODEL, ENV_PROVIDER, ENV_TOOLS
from ..store import RunStore

_log = logging.getLogger(__name__)


def _container_manager_for(cfg: Config) -> ContainerManager | None:
    """A runtime container manager when ``[worker].execution == "container"``."""
    if cfg.worker.execution == "container":
        return ContainerManager(image=cfg.worker.image)
    return None


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

    This is the temporary in-process scheduling (``agent-design.md`` section 6); the
    container-per-worker backend in M3 replaces the Worker execution, not this interface.
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

    async def cancel(self, run_id: str) -> None:
        """Stop one active engine before its runtime lease is force-released."""
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


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
    # Runtime container manager (M3a); built when [worker].execution == "container".
    container_manager: ContainerManager | None = None
    # Run-scoped Pi workers retain their lease across a human Gate. They are keyed by
    # resolved run directory so a fresh Engine used by SubmitHumanInput finds the same
    # container rather than starting another one.
    run_workers: dict[Path, RunContainerWorker] = field(default_factory=dict)
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
        # Rebuild the container manager too: [worker].execution/image may have changed.
        self.container_manager = _container_manager_for(config)

    def worker_for(self, run_dir: Path, *, config: Config | None = None) -> Worker:
        """The Worker for one run: container-per-worker, else the in-process provider.

        ``per-run`` Pi workers retain a container lease across Gate resumes; ``per-call``
        workers retain the earlier strict isolation. Both mount the run directory.
        """
        cfg = self.config if config is None else config
        if cfg.worker.execution != "container":
            return self.providers.worker
        if config is None and self.container_manager is None:
            raise CapabilityError(
                "worker.execution=container but no container manager is configured"
            )
        manager = self._manager_for(cfg)
        if manager is None:
            raise CapabilityError(
                "worker.execution=container but no container manager is configured"
            )
        env = self._worker_env(cfg)
        if cfg.worker.container_scope == "per-run":
            key = run_dir.resolve()
            worker = self.run_workers.get(key)
            if worker is None:
                worker = RunContainerWorker(
                    manager=manager, run_dir=run_dir, env=env
                )
                self.run_workers[key] = worker
            return worker
        return ContainerWorker(manager=manager, run_dir=run_dir, env=env)

    def _manager_for(self, config: Config) -> ContainerManager | None:
        """Resolve the runtime image frozen in a run snapshot, not live Settings."""
        if config.worker.execution != "container":
            return None
        if (
            self.container_manager is not None
            and self.config.worker.execution == "container"
            and self.config.worker.image == config.worker.image
        ):
            return self.container_manager
        return ContainerManager(image=config.worker.image)

    async def release_run_worker(self, run_dir: Path) -> None:
        """Release a run-level container at a terminal lifecycle boundary."""
        worker = self.run_workers.pop(run_dir.resolve(), None)
        if worker is not None:
            await worker.close()

    def _worker_env(self, config: Config | None = None) -> dict[str, str]:
        """Env injected into the container: worker config + credentials (env only)."""
        cfg = self.config if config is None else config
        model = cfg.capability.model
        # `search` is not mounted inside the container: the Pi TS search extension would
        # call the server at an address the container cannot reach. Retrieval therefore
        # stays a host-side pre-fetch (the engine sees no `search` tool and pre-fetches),
        # so container and in-process workers agree on who searches (M3a).
        tools = tuple(tool for tool in cfg.worker.tools if tool != "search")
        if "search" in cfg.worker.tools:
            _log.warning(
                "worker.tools 'search' is not mounted under execution=container; "
                "retrieval runs as a host-side pre-fetch (M3a)"
            )
        env = {
            ENV_PROVIDER: cfg.worker.provider,
            ENV_MODEL: model.model,
            ENV_BASE_URL: model.base_url or os.environ.get(BASE_URL_ENV_VAR, ""),
            ENV_TOOLS: ",".join(tools),
        }
        for name in (ENV_VAR, BASE_URL_ENV_VAR):
            value = os.environ.get(name)
            if value:
                env[name] = value
        return env

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
            container_manager=_container_manager_for(cfg),
            pinned_run=pinned,
        )

    @property
    def registry(self) -> ProjectRegistry:
        return ProjectRegistry(self.projects_dir, self.runs_dir)
