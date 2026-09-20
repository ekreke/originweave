"""In-container worker runner (M3a).

This module is the container command (``Dockerfile.runtime``). It exposes:

- ``GET /health`` -- readiness probe (the host polls it before sending a task);
- ``POST /run``    -- execute one worker task and return the raw reply.

The worker body is rebuilt from environment variables injected at ``docker run`` time
(provider / model / base_url / tools), so a single image serves both ``local`` and
``pi``; credentials still come from the environment (``OPENAI_API_KEY``), never config.
"""

from __future__ import annotations

import os
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..blackboard import Board
from ..capabilities.base import PromptTemplate
from ..capabilities.model import OpenAIModel
from ..capabilities.worker import LocalWorker, Worker
from ..config import ModelConfig
from .container import CONTAINER_PORT, ENV_BASE_URL, ENV_MODEL, ENV_PROVIDER, ENV_TOOLS


def build_container_worker() -> Worker:
    """Rebuild the configured worker (local/pi) from the container's environment."""
    provider = os.environ.get(ENV_PROVIDER, "local")
    model = os.environ.get(ENV_MODEL, "")
    base_url = os.environ.get(ENV_BASE_URL, "")
    tools = tuple(tool for tool in os.environ.get(ENV_TOOLS, "").split(",") if tool)
    if provider == "pi":
        # Import lazily so a local-only image needs no Pi runtime.
        from ..capabilities.pi import PiWorker

        return PiWorker(
            model=ModelConfig(provider="openai", model=model, base_url=base_url),
            tools=tools,
        )
    return LocalWorker(model=OpenAIModel(model=model, base_url=base_url))


async def _health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def _run(request: Request) -> JSONResponse:
    body: dict[str, Any] = await request.json()
    worker = build_container_worker()
    template = PromptTemplate(name=str(body.get("task", "")), text=str(body.get("template", "")))
    board = Board.from_dict(body.get("board") or {})
    extra = body.get("extra") or None
    reply = await worker.run(body["task"], template, board, extra=extra)
    return JSONResponse(
        {
            "text": reply.text,
            "input": reply.input,
            "steps": [step.to_session_dict() for step in reply.steps],
        }
    )


def create_runner_app() -> Starlette:
    """The container ASGI app: readiness probe + one-task execution."""
    return Starlette(
        routes=[
            Route("/health", _health, methods=["GET"]),
            Route("/run", _run, methods=["POST"]),
        ]
    )


def main() -> None:
    uvicorn.run(create_runner_app(), host="0.0.0.0", port=CONTAINER_PORT)


if __name__ == "__main__":
    main()
