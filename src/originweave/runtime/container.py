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
import contextlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..capabilities.base import CapabilityError, PromptTemplate
from ..capabilities.model import Usage
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


def _parse_usage(value: object) -> Usage | None:
    """Parse the runner's ``usage`` field into a :class:`Usage` (M3b; ``None`` if absent)."""
    if not isinstance(value, dict):
        return None
    prompt = value.get("prompt_tokens")
    completion = value.get("completion_tokens")
    total = value.get("total_tokens")
    if not (isinstance(prompt, int) and isinstance(completion, int) and isinstance(total, int)):
        return None
    return Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


def _first_host_port(port_output: str) -> str:
    """Parse ``docker port`` output (``127.0.0.1:32768``) into the host port."""
    for line in port_output.splitlines():
        line = line.strip()
        if line and ":" in line:
            return line.rsplit(":", 1)[1]
    raise ContainerError(f"could not read the container port from {port_output!r}")


def _error_detail(response: httpx.Response) -> str:
    """The failure text of a non-200 runner response.

    The runner returns ``{"error": "<Type>: <message>"}`` (see ``runtime/runner.py``);
    prefer that over the raw JSON so the run's FAILED reason reads cleanly. Anything
    else (a proxy error page, a truncated body) falls back to the raw text.
    """
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, str) and error:
            return error
    return response.text[:500]


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
            return await self._request(handle, task, template, board, extra=extra)
        finally:
            await self._manager.remove(handle)

    async def _request(
        self,
        handle: ContainerHandle,
        task: TaskKind,
        template: PromptTemplate,
        board: Any,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> WorkerReply:
        """Send one task to an already-ready runtime container."""
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
            raise ContainerError(f"worker container request failed: {exc}") from exc
        if response.status_code != 200:
            raise ContainerError(
                f"worker container returned {response.status_code}: {_error_detail(response)}"
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
                usage=_parse_usage(data.get("usage")),
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ContainerError(f"worker container returned a malformed reply: {exc}") from exc

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


class RunContainerWorker(ContainerWorker):
    """A Pi Worker that shares one lazily-created container for an entire run.

    The runner remains stateless: each HTTP request creates its own Pi session.  Only
    the OS container is shared.  A failed request poisons the lease; retrying it would
    violate the run-level failure boundary, so later calls fail immediately.
    """

    def __init__(
        self,
        *,
        health_interval: float = 5.0,
        failure_callback: Callable[[str], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._lease_lock = asyncio.Lock()
        self._handle: ContainerHandle | None = None
        self._failure: str | None = None
        self._closed = False
        self._health_interval = health_interval
        self._failure_callback = failure_callback
        self._monitor_task: asyncio.Task[None] | None = None
        self._inflight = 0

    def set_failure_callback(self, callback: Callable[[str], Awaitable[None]]) -> None:
        """Install the Engine-owned failure writer before the first task starts."""
        self._failure_callback = callback

    async def run(
        self,
        task: TaskKind,
        template: PromptTemplate,
        board: Any,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> WorkerReply:
        handle = await self._begin_call()
        try:
            return await self._request(handle, task, template, board, extra=extra)
        except ContainerError as exc:
            await self._poison(exc)
            raise
        finally:
            await self._end_call()

    async def close(self) -> None:
        """Release the run lease. Safe to call repeatedly at a terminal boundary."""
        async with self._lease_lock:
            self._closed = True
            handle, self._handle = self._handle, None
            monitor, self._monitor_task = self._monitor_task, None
        if monitor is not None and monitor is not asyncio.current_task():
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor
        if handle is not None:
            await self._manager.remove(handle)

    async def abort(self) -> None:
        """Poison a lease whose caller timed out; it must never be reused."""
        await self._poison(ContainerError("run worker container call timed out"))

    async def _acquire(self) -> ContainerHandle:
        async with self._lease_lock:
            if self._closed:
                raise ContainerError("run worker container has been closed")
            if self._failure is not None:
                raise ContainerError(f"run worker container is unavailable: {self._failure}")
            if self._handle is None:
                handle = await self._manager.spawn(run_dir=self._run_dir, env=self._env)
                try:
                    await self._wait_ready(handle)
                except ContainerError as exc:
                    await self._manager.remove(handle)
                    self._failure = str(exc)
                    raise
                self._handle = handle
                self._monitor_task = asyncio.create_task(self._monitor())
            return self._handle

    async def _begin_call(self) -> ContainerHandle:
        handle = await self._acquire()
        async with self._lease_lock:
            if self._handle is not handle or self._failure is not None or self._closed:
                raise ContainerError("run worker container is unavailable")
            self._inflight += 1
        return handle

    async def _end_call(self) -> None:
        async with self._lease_lock:
            self._inflight = max(0, self._inflight - 1)

    async def _poison(self, exc: ContainerError) -> None:
        async with self._lease_lock:
            if self._failure is None:
                self._failure = str(exc)
            handle, self._handle = self._handle, None
        if handle is not None:
            await self._manager.remove(handle)

    async def _poison_if_idle(self, exc: ContainerError) -> bool:
        """Poison only if no request started while the monitor probed health."""
        async with self._lease_lock:
            if self._inflight or self._handle is None or self._closed:
                return False
            if self._failure is None:
                self._failure = str(exc)
            handle, self._handle = self._handle, None
        await self._manager.remove(handle)
        return True

    async def _monitor(self) -> None:
        """Detect a shared container dying while its run waits at a human Gate."""
        while True:
            await asyncio.sleep(self._health_interval)
            async with self._lease_lock:
                handle = self._handle
                closed = self._closed
                inflight = self._inflight
            if closed or handle is None:
                return
            if inflight:
                continue
            try:
                async with httpx.AsyncClient(timeout=2.0, transport=self._transport) as http:
                    response = await http.get(f"{handle.base_url}/health")
                if response.status_code != 200:
                    raise ContainerError(
                        f"worker container health check returned {response.status_code}"
                    )
            except (ContainerError, httpx.HTTPError) as exc:
                error = exc if isinstance(exc, ContainerError) else ContainerError(str(exc))
                poisoned = await self._poison_if_idle(error)
                if poisoned and self._failure_callback is not None:
                    await self._failure_callback(str(error))
                if poisoned:
                    return


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
    "RunContainerWorker",
]
