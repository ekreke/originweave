"""ASGI app assembly for the originweave server (M1c-1).

Wraps the generated Connect ASGI application in Starlette so ``originweave ui`` can
also host the built frontend. The Connect endpoints live under the proto service path
(``/originweave.v1.OriginweaveService/<Method>``); when ``static_dir`` is given the
built single-page app is served from ``/`` with an ``index.html`` fallback.

``config`` / ``providers`` / ``root`` / ``static_dir`` / ``run_dir`` are injected here
(tests pass fakes and a temp root); production uses the project ``originweave.toml``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from originweave.v1.originweave_connect import OriginweaveServiceASGIApplication

from ..config import Config
from .context import Providers, ServerContext
from .service import Service


class SPAStaticFiles(StaticFiles):
    """Static files with an ``index.html`` fallback for client-side routes.

    The frontend is a single-page app: a deep link such as
    ``/projects/p/runs/run_001`` has no file on disk, so a miss must return the shell
    (the router then renders the right view) instead of a bare 404.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            # Only navigation requests (no file extension, e.g. /projects/x/runs/y)
            # fall back to the shell; a missing asset must stay a 404 so a broken
            # build is visible rather than masked by index.html with a wrong MIME.
            if exc.status_code == 404 and "." not in PurePosixPath(path).name:
                return await super().get_response("index.html", scope)
            raise


def create_app(
    *,
    config: Config | None = None,
    providers: Providers | None = None,
    root: Path | None = None,
    service: Service | None = None,
    static_dir: Path | None = None,
    run_dir: Path | None = None,
) -> Starlette:
    """Build the ASGI app: the Connect service plus optional SPA static hosting.

    The Connect app is mounted at its own proto path so the static tree can own ``/``.
    When the service is built here, the lifespan drains the scheduler's in-flight
    background run tasks on shutdown. ``service=`` is the test seam (it bypasses the
    context), so ``run_dir`` is ignored and the lifespan has no scheduler to drain
    in that case — tests drive ``ServerContext.scheduler`` directly.
    """
    scheduler = None
    managed_service = None
    if service is None:
        context = ServerContext.build(
            config=config, providers=providers, root=root, run_dir=run_dir
        )
        service = Service(context)
        scheduler = context.scheduler
        managed_service = service

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:
            # Shared Pi leases must be failed and reclaimed before waiting for other
            # background work; otherwise an indefinitely wedged call delays shutdown.
            if managed_service is not None:
                await managed_service.shutdown()
            if scheduler is not None:
                await scheduler.drain()

    app = Starlette(lifespan=lifespan)
    connect = OriginweaveServiceASGIApplication(service)
    app.mount(connect.path, connect)
    if static_dir is not None and Path(static_dir).is_dir():
        app.mount("/", SPAStaticFiles(directory=Path(static_dir), html=True), name="ui")
    return app
