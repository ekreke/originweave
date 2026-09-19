"""ASGI app assembly for the originweave server (M1c-1).

Wraps the generated Connect ASGI application in Starlette so C4 can attach static
files / middleware. The Connect endpoints live under the root mount at
``/originweave.v1.OriginweaveService/<Method>``.

``config`` / ``providers`` / ``root`` are injected here (tests pass fakes and a
temp root); production uses the project ``originweave.toml``.
"""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette

from originweave.v1.originweave_connect import OriginweaveServiceASGIApplication

from ..config import Config
from .context import Providers, ServerContext
from .service import Service


def create_app(
    *,
    config: Config | None = None,
    providers: Providers | None = None,
    root: Path | None = None,
    service: Service | None = None,
) -> Starlette:
    """Build the ASGI app: the Connect service mounted at the root."""
    if service is None:
        service = Service(ServerContext.build(config=config, providers=providers, root=root))
    app = Starlette()
    app.mount("/", OriginweaveServiceASGIApplication(service))
    return app
