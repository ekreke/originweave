"""Container-per-worker execution backend (M3a).

``ContainerWorker`` implements the same ``Worker`` protocol as ``LocalWorker`` /
``PiWorker`` but executes every call in a **fresh** container (red line 3):

    Engine (server) --Worker.run()--> ContainerWorker
        docker run -d --rm -p 127.0.0.1::8000 -v <run_dir>:<run_dir> <image>
        wait GET /health -> POST /run {task, template, board, extra} -> WorkerReply
        docker rm -f

The engine stays the sole blackboard writer (red lines 2/4); the container only runs
the worker (calls the model / Pi tools) and returns the raw reply. ``docker`` is
invoked as a subprocess so no extra Python dependency is needed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..capabilities.base import CapabilityError, PromptTemplate
from ..capabilities.worker import TaskKind, WorkerReply, WorkerStep, board_payload

# Container-side HTTP port; the host port is assigned by Docker and read back.
CONTAINER_PORT = 8000
# Env vars the runner reads to rebuild the worker (see runtime/runner.py).
ENV_MODEL = "ORIGINWEAVE_MODEL"
ENV_PROVIDER = "ORIGINWEAVE_WORKER_PROVIDER"
ENV_TOOLS = "ORIGINWEAVE_WORKER_TOOLS"
ENV_BASE_URL = "ORIGINWEAVE_MODEL_BASE_URL"


class ContainerError(CapabilityError):
    """Raised when a container cannot be started, reached, or cleaned up."""


@dataclass(frozen=True)
class ContainerHandle:
    container_id: str
    base_url: str  # e.g. http://127.0.0.1:32768


async def _run_command(argv: list[str], *, check: bool = True) -> str:
    """Run ``argv`` and return stdout; raise :class:`ContainerError` on failure."""
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ContainerError(f"{argv[0]!r} not found on PATH (is Docker installed?)") from exc
    stdout, stderr = await process.communicate()
    if check and process.returncode != 0:
        detail = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise ContainerError(f"{argv[0]} failed (exit {process.returncode}): {detail}")
    return stdout.decode(errors="replace")


def _first_host_port(port_output: str) -> str:
    """Parse ``docker port`` output (``127.0.0.1:32768``) into the host port."""
    for line in port_output.splitlines():
        line = line.strip()
        if line and ":" in line:
            return line.rsplit(":", 1)[1]
    raise ContainerError(f"could not read the container port from {port_output!r}")


class ContainerManager:
    """Starts and reclaims one runtime container per Worker call (M3a)."""

    def __init__(self, *, image: str, docker: str = "docker") -> None:
        self._image = image
        self._docker = docker

    async def spawn(self, *, run_dir: Path, env: Mapping[str, str]) -> ContainerHandle:
        """Start a detached container mounting ``run_dir`` and return its endpoint."""
        argv = [
            self._docker,
            "run",
            "-d",
            "--rm",
            "-p",
            f"127.0.0.1::{CONTAINER_PORT}",
            "-v",
            f"{run_dir}:{run_dir}",
            "-w",
            str(run_dir),
        ]
        for key, value in env.items():
            argv += ["-e", f"{key}={value}"]
        argv.append(self._image)
        container_id = (await _run_command(argv)).strip()
        if not container_id:
            raise ContainerError(f"docker run for image {self._image!r} returned no container id")
        try:
            port = _first_host_port(
                await _run_command([self._docker, "port", container_id, str(CONTAINER_PORT)])
            )
        except ContainerError:
            # Don't leak the container we just started if we cannot reach its port.
            await _run_command([self._docker, "rm", "-f", container_id], check=False)
            raise
        return ContainerHandle(container_id=container_id, base_url=f"http://127.0.0.1:{port}")

    async def remove(self, handle: ContainerHandle) -> None:
        """Force-remove the container (idempotent; ``--rm`` also cleans up on exit)."""
        await _run_command([self._docker, "rm", "-f", handle.container_id], check=False)


class ContainerWorker:
    """A ``Worker`` whose every ``run`` happens in one short-lived container."""

    name = "container"

    def __init__(
        self,
        *,
        manager: ContainerManager,
        run_dir: Path,
        env: Mapping[str, str],
        ready_timeout: float = 30.0,
        request_timeout: float = 300.0,
        poll_interval: float = 0.2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._manager = manager
        self._run_dir = run_dir
        self._env = dict(env)
        self._ready_timeout = ready_timeout
        self._request_timeout = request_timeout
        self._poll_interval = poll_interval
        # Injectable for tests (httpx.MockTransport); None uses the real network.
        self._transport = transport

    @property
    def model(self) -> str:
        # The engine labels sessions with ``worker.model``; surface the configured model.
        return self._env.get(ENV_MODEL) or self.name

    @property
    def tools(self) -> tuple[str, ...]:
        # The engine decides whether a worker self-searches by inspecting ``tools``;
        # build it from what we actually pass to the container (``search`` is filtered
        # out by the server, so retrieval stays a host-side pre-fetch, M3a).
        return tuple(tool for tool in self._env.get(ENV_TOOLS, "").split(",") if tool)

    async def run(
        self,
        task: TaskKind,
        template: PromptTemplate,
        board: Any,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> WorkerReply:
        """Execute one task in a fresh container and return its raw reply."""
        handle = await self._manager.spawn(run_dir=self._run_dir, env=self._env)
        try:
            await self._wait_ready(handle)
            payload = {
                "task": task,
                "template": template.text,
                "board": board_payload(board),
                "extra": dict(extra) if extra else {},
            }
            try:
                async with httpx.AsyncClient(
                    timeout=self._request_timeout, transport=self._transport
                ) as http:
                    response = await http.post(f"{handle.base_url}/run", json=payload)
            except httpx.HTTPError as exc:
                # Wrap transport failures so the engine sees a CapabilityError and
                # fails the run loudly instead of leaving it stuck in `running`.
                raise ContainerError(f"worker container request failed: {exc}") from exc
            if response.status_code != 200:
                raise ContainerError(
                    f"worker container returned {response.status_code}: {response.text[:500]}"
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise ContainerError(f"worker container returned invalid JSON: {exc}") from exc
            try:
                steps = [WorkerStep(**step) for step in data.get("steps", [])]
                return WorkerReply(
                    text=str(data.get("text", "")),
                    input=dict(data.get("input") or {}),
                    steps=steps,
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise ContainerError(
                    f"worker container returned a malformed reply: {exc}"
                ) from exc
        finally:
            await self._manager.remove(handle)

    async def _wait_ready(self, handle: ContainerHandle) -> None:
        deadline = asyncio.get_running_loop().time() + self._ready_timeout
        async with httpx.AsyncClient(timeout=2.0, transport=self._transport) as http:
            while True:
                try:
                    response = await http.get(f"{handle.base_url}/health")
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                if asyncio.get_running_loop().time() > deadline:
                    raise ContainerError(
                        f"worker container {handle.container_id} not ready within "
                        f"{self._ready_timeout:g}s"
                    )
                await asyncio.sleep(self._poll_interval)


__all__ = [
    "CONTAINER_PORT",
    "ENV_BASE_URL",
    "ENV_MODEL",
    "ENV_PROVIDER",
    "ENV_TOOLS",
    "ContainerError",
    "ContainerHandle",
    "ContainerManager",
    "ContainerWorker",
]
