"""Connect service implementation (M1c-1).

The generated ``originweave.v1`` module provides ``OriginweaveService`` as a
:class:`typing.Protocol` whose default methods raise ``UNIMPLEMENTED``. We subclass
it so unimplemented RPCs keep that behaviour while we implement them milestone by
milestone. C3a wires the read-only RPCs; C3b adds ``CreateRun`` / ``AddHint`` /
``SubmitHumanInput``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from connectrpc.code import Code
from connectrpc.errors import ConnectError

from originweave.v1 import originweave_pb2 as pb
from originweave.v1.originweave_connect import OriginweaveService

from ..blackboard import BlackboardError, Fact, Hint
from ..config import parse_duration
from ..engine import GATE_A, Engine, EngineError
from ..events import now_iso
from ..persistence import Project, Run, allocate_run_id, is_run_id, summarize_run
from ..reduce import ReduceError, reduce
from ..store import RunStore
from . import convert
from .context import ServerContext

# Longest auto-derived title taken from document A's first non-empty line.
_TITLE_LIMIT = 120


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:_TITLE_LIMIT]
    return ""


def _budget_override(request: Any) -> dict[str, Any]:
    """Collect the set CreateRunRequest budget overrides (unset fields are omitted)."""
    budget: dict[str, Any] = {}
    if request.HasField("max_steps"):
        budget["max_steps"] = int(request.max_steps)
    if request.HasField("max_wall"):
        parse_duration(request.max_wall, "max_wall")
        budget["max_wall"] = request.max_wall
    if request.HasField("max_cost"):
        budget["max_cost"] = float(request.max_cost)
    return budget


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

    async def create_run(self, request: Any, ctx: Any) -> Any:
        """Start a run: persist the input, schedule the engine, return the run (C3b).

        The engine runs as a background task; this RPC waits only until the ``PROJECT``
        event lands so any following ``GetRun`` can already read the board. ``auto``
        defaults to ``[hitl].auto`` when the request does not set it.
        """
        project_id = request.project_id
        if self._lookup_project(project_id) is None:
            raise ConnectError(Code.NOT_FOUND, f"project {project_id!r} not found")

        if request.source_type != "text":
            raise ConnectError(
                Code.INVALID_ARGUMENT,
                f"source_type {request.source_type!r} is not supported yet; use 'text'",
            )
        source_text = request.source_text if request.HasField("source_text") else ""
        if not source_text.strip():
            raise ConnectError(
                Code.INVALID_ARGUMENT, "source_text is required for source_type='text'"
            )
        analysis = request.analysis if request.HasField("analysis") else "provenance"
        if analysis != "provenance":
            raise ConnectError(
                Code.INVALID_ARGUMENT, f"analysis {analysis!r} is not supported until M5"
            )
        if not request.goal.strip():
            raise ConnectError(Code.INVALID_ARGUMENT, "goal is required")

        # All of this is synchronous: no await may slip between allocate_run_id and the
        # directory creation, so two concurrent CreateRun calls cannot take the same id.
        run_id = allocate_run_id(self._ctx.runs_dir)
        store = self._ctx.scheduler.store_for(run_id)
        store.init_layout()
        title = (request.title if request.HasField("title") else "").strip()[:_TITLE_LIMIT]
        title = title or _first_line(source_text) or run_id
        created_at = now_iso()
        store.write_input("document.md", source_text)
        store.write_input(
            "source.json",
            json.dumps(
                {"sourceType": "text", "title": title, "createdAt": created_at},
                sort_keys=True,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        meta: dict[str, Any] = {
            "id": run_id,
            "project_id": project_id,
            "title": title,
            "source_type": "text",
            "analysis": analysis,
            "goal": request.goal,
            "created_at": created_at,
        }
        if request.HasField("auto"):
            meta["auto"] = bool(request.auto)
        try:
            budget = _budget_override(request)
        except ValueError as exc:  # ConfigError: a malformed max_wall duration
            raise ConnectError(Code.INVALID_ARGUMENT, str(exc)) from exc
        if budget:
            meta["budget"] = budget
        store.write_run_meta(meta)

        origin = Fact(
            id="origin",
            kind="origin",
            role="none",
            label=title,
            subtitle="text",
            status="verified",
            confidence=1.0,
            note=source_text,
        )
        goal = Fact(
            id="goal",
            kind="goal",
            role="none",
            label=request.goal,
            subtitle="停止条件",
            status="verified",
            confidence=1.0,
        )
        auto = bool(request.auto) if request.HasField("auto") else self._ctx.config.hitl.auto
        engine = self._build_engine(store, auto=auto)
        task = self._ctx.scheduler.start(run_id, engine.run(origin=origin, goal=goal, auto=auto))
        await self._await_project(store, task)
        run = summarize_run(store, meta=meta, budget=self._ctx.config.worker.budget)
        return pb.CreateRunResponse(run=convert.run_pb(run))

    async def add_hint(self, request: Any, ctx: Any) -> Any:
        """Append a human Hint (non-blocking, C3b)."""
        store = self._require_run_store(request.run_id)
        next_index = sum(1 for event in store.iter_events() if event.type == "HINT") + 1
        hint = Hint(id=f"h{next_index}", text=request.text, author="human", createdAt=now_iso())
        store.append_event("HINT", {"hint": hint.to_dict()}, message="Hint added")
        return pb.AddHintResponse(hint=convert.hint_pb(hint))

    async def submit_human_input(self, request: Any, ctx: Any) -> Any:
        """Resolve a paused gate and continue the run (C3b; fresh-engine resume)."""
        store = self._require_run_store(request.run_id)
        try:
            board = reduce(store.read_events())
        except (BlackboardError, ReduceError) as exc:
            raise ConnectError(
                Code.INTERNAL, f"run {request.run_id!r} has a malformed event log: {exc}"
            ) from exc
        if board.status != "awaiting_human" or board.waitingFor is None:
            raise ConnectError(Code.FAILED_PRECONDITION, "run is not awaiting human input")
        pending = board.waitingFor.gate
        if request.gate != pending:
            raise ConnectError(
                Code.INVALID_ARGUMENT,
                f"gate {request.gate!r} does not match the pending gate {pending!r}",
            )
        if pending != GATE_A:
            # Gate B/C do not exist until M2/M3; a matching-but-unknown gate is not a
            # client argument error, so report it as unimplemented rather than 400.
            raise ConnectError(Code.UNIMPLEMENTED, f"gate {pending!r} is not supported yet")
        if request.decision not in ("approve", "edit", "reject"):
            raise ConnectError(Code.INVALID_ARGUMENT, f"unknown decision {request.decision!r}")
        engine = self._build_engine(store, auto=False)
        try:
            await engine.resume(
                decision=request.decision,
                text=request.text if request.HasField("text") else "",
                targets=list(request.targets),
            )
        except EngineError as exc:
            raise ConnectError(Code.FAILED_PRECONDITION, str(exc)) from exc
        run = summarize_run(
            store, meta=store.read_run_meta(), budget=self._ctx.config.worker.budget
        )
        return pb.SubmitHumanInputResponse(run=convert.run_pb(run))

    def _build_engine(self, store: RunStore, *, auto: bool) -> Engine:
        """Build an engine over ``store`` from the resolved config/providers."""
        worker = self._ctx.config.worker
        return Engine(
            worker=self._ctx.providers.worker,
            search=self._ctx.providers.search,
            prompt=self._ctx.providers.prompt,
            store=store,
            max_concurrency=worker.max_concurrency,
            heartbeat_interval=parse_duration(
                worker.heartbeat_interval, "worker.heartbeat_interval"
            ),
            heartbeat_timeout=parse_duration(worker.heartbeat_timeout, "worker.heartbeat_timeout"),
            heartbeat_on_timeout=worker.heartbeat_on_timeout,
            auto=auto,
        )

    async def _await_project(self, store: RunStore, task: asyncio.Task[Any]) -> None:
        """Yield until the background engine has written its first (``PROJECT``) event.

        ``Engine.run`` appends ``PROJECT`` synchronously before its first await, so this
        normally returns after a single yield. The ``task.done()`` guard only avoids
        spinning if the task died earlier; in that case the run never became readable,
        so surface it instead of returning a half-created run.
        """
        while store.event_count() == 0 and not task.done():
            await asyncio.sleep(0)
        if store.event_count() == 0:
            raise ConnectError(Code.INTERNAL, f"run {store.root.name!r} failed to start")

    def _require_run_store(self, run_id: str) -> RunStore:
        """Return the shared store for an existing run, or ``NOT_FOUND``.

        Existence is checked on a throwaway store *before* touching the scheduler's
        cache, so probing unknown ids cannot grow it.
        """
        if not is_run_id(run_id):
            raise ConnectError(Code.NOT_FOUND, f"run {run_id!r} not found")
        if not RunStore(self._ctx.runs_dir / run_id).events_path.is_file():
            raise ConnectError(Code.NOT_FOUND, f"run {run_id!r} not found")
        return self._ctx.scheduler.store_for(run_id)

    def _lookup_project(self, project_id: str) -> Project | None:
        try:
            return self._ctx.registry.get(project_id)
        except BlackboardError as exc:
            raise ConnectError(Code.INTERNAL, str(exc)) from exc
        except ValueError as exc:
            raise ConnectError(Code.INVALID_ARGUMENT, str(exc)) from exc

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
