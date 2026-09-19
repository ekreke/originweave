"""Connect service implementation (M1c-1).

The generated ``originweave.v1`` module provides ``OriginweaveService`` as a
:class:`typing.Protocol` whose default methods raise ``UNIMPLEMENTED``. We subclass
it so unimplemented RPCs keep that behaviour while we implement them milestone by
milestone. C3a wires the read-only RPCs; C3b adds ``CreateRun`` / ``AddHint`` /
``SubmitHumanInput``.
"""

from __future__ import annotations

from typing import Any

from connectrpc.code import Code
from connectrpc.errors import ConnectError

from originweave.v1 import originweave_pb2 as pb
from originweave.v1.originweave_connect import OriginweaveService

from ..blackboard import BlackboardError
from ..persistence import Project, Run, is_run_id, summarize_run
from ..reduce import ReduceError, reduce
from ..store import RunStore
from . import convert
from .context import ServerContext


class Service(OriginweaveService):  # type: ignore[misc]  # generated base is Any (mypy skips gen)
    """OriginweaveService backed by the project registry and run directories."""

    def __init__(self, context: ServerContext) -> None:
        self._ctx = context

    async def list_projects(self, request: Any, ctx: Any) -> Any:
        try:
            projects = self._ctx.registry.list()
        except BlackboardError as exc:
            raise ConnectError(Code.INTERNAL, str(exc)) from exc
        return pb.ListProjectsResponse(projects=[convert.project_pb(p) for p in projects])

    async def get_project(self, request: Any, ctx: Any) -> Any:
        project_id = request.project_id
        project = self._lookup_project(project_id)
        if project is None:
            raise ConnectError(Code.NOT_FOUND, f"project {project_id!r} not found")
        return pb.GetProjectResponse(project=convert.project_pb(project))

    async def list_project_runs(self, request: Any, ctx: Any) -> Any:
        project_id = self._require_project_id(request.project_id)
        runs = self._collect_runs(project_id=project_id)
        return pb.ListProjectRunsResponse(runs=[convert.run_pb(run) for run in runs])

    async def list_runs(self, request: Any, ctx: Any) -> Any:
        project_id = request.project_id if request.HasField("project_id") else None
        if project_id is not None:
            project_id = self._require_project_id(project_id)
        runs = self._collect_runs(project_id=project_id)
        return pb.ListRunsResponse(runs=[convert.run_pb(run) for run in runs])

    async def get_run(self, request: Any, ctx: Any) -> Any:
        run_id = request.run_id
        if not is_run_id(run_id):
            raise ConnectError(Code.NOT_FOUND, f"run {run_id!r} not found")
        store = RunStore(self._ctx.runs_dir / run_id)
        if not store.events_path.is_file():
            raise ConnectError(Code.NOT_FOUND, f"run {run_id!r} not found")
        try:
            return pb.GetRunResponse(run_detail=self._run_detail(store))
        except (BlackboardError, ReduceError) as exc:
            raise ConnectError(
                Code.INTERNAL, f"run {run_id!r} has a malformed event log: {exc}"
            ) from exc

    def _lookup_project(self, project_id: str) -> Project | None:
        try:
            return self._ctx.registry.get(project_id)
        except ValueError as exc:
            raise ConnectError(Code.INVALID_ARGUMENT, str(exc)) from exc
        except BlackboardError as exc:
            raise ConnectError(Code.INTERNAL, str(exc)) from exc

    def _require_project_id(self, project_id: str) -> str:
        try:
            self._ctx.registry.path(project_id)
        except ValueError as exc:
            raise ConnectError(Code.INVALID_ARGUMENT, str(exc)) from exc
        return project_id

    def _collect_runs(self, *, project_id: str | None) -> list[Run]:
        if not self._ctx.runs_dir.is_dir():
            return []
        runs: list[Run] = []
        for entry in sorted(self._ctx.runs_dir.iterdir()):
            # Only real run directories; a stray/corrupt run must not break the list.
            if not entry.is_dir() or not is_run_id(entry.name):
                continue
            store = RunStore(entry)
            try:
                run = summarize_run(
                    store,
                    meta=store.read_run_meta(),
                    budget=self._ctx.config.worker.budget,
                )
            except (BlackboardError, ReduceError, OSError):
                continue
            if project_id is not None and run.project_id != project_id:
                continue
            runs.append(run)
        return runs

    def _run_detail(self, store: RunStore) -> Any:
        events = store.read_events()
        board = reduce(events)
        run = summarize_run(
            store,
            meta=store.read_run_meta(),
            budget=self._ctx.config.worker.budget,
        )
        return convert.run_detail_pb(run, board, events)
