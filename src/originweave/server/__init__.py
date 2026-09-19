"""Connect server for originweave (M1c-1).

The service layer is the orchestrator/persister (architecture red line 2): it
drives the library-layer :class:`~originweave.engine.Engine` and exposes the frozen
``originweave.v1`` API over Connect. ``create_app`` assembles the ASGI app;
:class:`ServerContext` / :class:`Providers` are the injectable dependencies.
"""

from __future__ import annotations

from .app import create_app
from .context import Providers, ServerContext, build_providers

__all__ = ["Providers", "ServerContext", "build_providers", "create_app"]
