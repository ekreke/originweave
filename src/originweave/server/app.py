"""ASGI app assembly for the originweave server (M1c-1).

Wraps the generated Connect ASGI application in Starlette so C4 can attach static
files / middleware. The Connect endpoints live under the root mount at
``/originweave.v1.OriginweaveService/<Method>``.
"""

from __future__ import annotations

from starlette.applications import Starlette

from originweave.v1.originweave_connect import OriginweaveServiceASGIApplication

from .service import Service


def create_app(*, service: Service | None = None) -> Starlette:
    """Build the ASGI app: the Connect service mounted at the root."""
    app = Starlette()
    app.mount("/", OriginweaveServiceASGIApplication(service or Service()))
    return app
