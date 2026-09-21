"""Fake-provider server for the browser end-to-end tests (M1c-2b 2b-5).

Boots the real ASGI app (Connect API + the built ``frontend/dist``) over uvicorn with a
scripted worker, so Playwright can drive the actual UI without a network or credentials.
The run root is a fresh temp dir per process and a project ``e2e`` is pre-created so the
NewRun form can submit. Reuses the smoke worker from :mod:`smoke`.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import uvicorn
from smoke import _FakePrompt, _NoSearch, _replies, _ScriptedModel

from originweave.capabilities.worker import LocalWorker
from originweave.config import Config, WorkerConfig
from originweave.persistence import Project, ProjectRegistry
from originweave.server import Providers, create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "e2e"
PORT = int(os.environ.get("PORT", "8790"))


def main() -> None:
    static_dir = REPO_ROOT / "frontend" / "dist"
    if not (static_dir / "index.html").is_file():
        raise SystemExit(f"no built frontend at {static_dir}; run `make frontend-build` first")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ProjectRegistry(root / "projects", root / "runs").write(
            Project(id=PROJECT_ID, name="E2E")
        )
        providers = Providers(
            worker=LocalWorker(model=_ScriptedModel(*_replies())),
            search=_NoSearch(),
            prompt=_FakePrompt(),
        )
        # Let create_app build the context so the lifespan drains the run scheduler.
        # Force the injected fake worker: the production default is container execution,
        # which would try to spawn Docker instead of running the scripted worker.
        app = create_app(
            config=Config(worker=WorkerConfig(execution="in-process", container_scope="per-call")),
            providers=providers,
            root=root,
            static_dir=static_dir,
        )
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
