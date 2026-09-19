"""Server context and dependency injection (M1c-1).

The service layer is constructed with a :class:`ServerContext` that carries the
project config, the resolved capabilities (worker/search/prompt) and the run /
project directories. Tests inject fake providers; production builds them from
``originweave.toml`` via :func:`originweave.capabilities.build_*`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import config as config_module
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
class ServerContext:
    """Everything the service needs, resolved once at app startup."""

    config: Config
    providers: Providers
    runs_dir: Path
    projects_dir: Path

    @classmethod
    def build(
        cls,
        *,
        config: Config | None = None,
        providers: Providers | None = None,
        root: Path | None = None,
    ) -> ServerContext:
        """Resolve config/providers and the run + project directories.

        ``root`` is the base for the relative ``[run].dir`` / ``[project].dir``
        paths (defaults to the current working directory).
        """
        cfg = config if config is not None else config_module.load()
        base = Path.cwd() if root is None else Path(root)
        return cls(
            config=cfg,
            providers=providers if providers is not None else build_providers(cfg),
            runs_dir=base / cfg.run.dir,
            projects_dir=base / cfg.project.dir,
        )

    @property
    def registry(self) -> ProjectRegistry:
        return ProjectRegistry(self.projects_dir, self.runs_dir)
