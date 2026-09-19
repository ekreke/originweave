"""Connect server for originweave (M1c-1).

The service layer is the orchestrator/persister (architecture red line 2): it
drives the library-layer :class:`~originweave.engine.Engine` and exposes the frozen
``originweave.v1`` API over Connect. Only :func:`create_app` is public.
"""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
