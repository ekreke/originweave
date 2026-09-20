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
from ..capabilities import CapabilityError
from ..config import (
    BudgetConfig,
    CapabilityConfig,
    Config,
    ConfigError,
    ModelConfig,
    WorkerConfig,
    from_dict,
    parse_duration,
)
from ..config import save as save_config
from ..engine import GATE_A, GATE_B, Engine, EngineError
from ..events import Event, now_iso
from ..persistence import Project, Run, allocate_run_id, is_run_id, summarize_run
from ..reduce import ReduceError, reduce
from ..report import ReportError
from ..runtime import RunContainerWorker
from ..store import RunStore
from . import convert
from .context import ServerContext

# Longest auto-derived title taken from document A's first non-empty line.
_TITLE_LIMIT = 120
# A project id that would collide with the frontend route ``/projects/new`` (M4a).
_RESERVED_PROJECT_IDS: frozenset[str] = frozenset({"new"})
# Upper bound on SearchRequest.num_results, so a client cannot ask a provider for an
# unbounded fan-out.
_MAX_SEARCH_RESULTS = 50
# Synthetic project for a pinned run without run.json (e.g. the committed sample).
_SAMPLE_PROJECT_ID = "sample"
# Terminal states whose run can be re-submitted (the UI's "retry").
_RETRYABLE_STATUSES = frozenset({"failed", "stopped"})


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


def _config_from_settings(base: Config, settings: Any) -> Config:
    """Build a validated :class:`Config` from an ``UpdateSettings`` request.

    The ``worker`` block is all-or-nothing: proto3 scalars have no presence, so an
    omitted scalar arrives as ``""``/``0`` and fails validation rather than silently
    resetting a field (the client round-trips ``GetSettings``); ``tools`` is
    authoritative, so an omitted/empty list clears it. Only the ``llm`` and
    ``budget`` sub-messages may be omitted, in which case the current values are kept.
    """
    if not settings.HasField("worker"):
        raise ConfigError("settings.worker is required")
    worker = settings.worker
    model = base.capability.model
    if worker.HasField("llm"):
        model = ModelConfig(
            provider=worker.llm.provider,
            model=worker.llm.model,
            base_url=worker.llm.base_url,
        )
    budget = (
        BudgetConfig(
            max_steps=worker.budget.max_steps,
            max_wall=worker.budget.max_wall,
            max_cost=worker.budget.max_cost,
        )
        if worker.HasField("budget")
        else base.worker.budget
    )
    candidate = Config(
        hitl=base.hitl,
        capability=CapabilityConfig(
            search=base.capability.search,
            prompt=base.capability.prompt,
            model=model,
        ),
        worker=WorkerConfig(
            provider=worker.provider,
            # Keep compatibility with older generated clients. Current clients round
            # trip these fields, but old clients cannot express them yet.
            execution=worker.execution or base.worker.execution,
            image=worker.image or base.worker.image,
            container_scope=(
                worker.container_scope
                or (
                    "per-call"
                    if worker.provider != "pi"
                    or (worker.execution or base.worker.execution) != "container"
                    else base.worker.container_scope
                )
            ),
            max_concurrency=worker.max_concurrency,
            tools=tuple(worker.tools),
            heartbeat_interval=worker.heartbeat_interval,
            heartbeat_timeout=worker.heartbeat_timeout,
            heartbeat_on_timeout=worker.heartbeat_on_timeout,
            budget=budget,
        ),
        run=base.run,
        project=base.project,
    )
    candidate.validate()
    return candidate


class Service(OriginweaveService):  # type: ignore[misc]  # generated base is Any (mypy skips gen)
    """OriginweaveService backed by the project registry and run directories."""

    def __init__(self, context: ServerContext) -> None:
        self._ctx = context

    async def list_projects(self, request: Any, ctx: Any) -> Any:
        if self._ctx.pinned_run is not None:
            return pb.ListProjectsResponse(projects=[convert.project_pb(self._pinned_project())])
        try:
            projects = self._ctx.registry.list()
        except BlackboardError as exc:
            raise ConnectError(Code.INTERNAL, str(exc)) from exc
        return pb.ListProjectsResponse(projects=[convert.project_pb(p) for p in projects])

    async def get_project(self, request: Any, ctx: Any) -> Any:
        project_id = request.project_id
        if self._ctx.pinned_run is not None:
            pinned = self._pinned_project()
            if project_id != pinned.id:
                raise ConnectError(Code.NOT_FOUND, f"project {project_id!r} not found")
            return pb.GetProjectResponse(project=convert.project_pb(pinned))
        project = self._lookup_project(project_id)
        if project is None:
            raise ConnectError(Code.NOT_FOUND, f"project {project_id!r} not found")
        return pb.GetProjectResponse(project=convert.project_pb(project))

    async def create_project(self, request: Any, ctx: Any) -> Any:
        """Create a project registry entry (M4a).

        Projects are the only way to start a run (``CreateRun`` needs one to exist), so
        this is the entry point that lets a fresh server be used at all. Idempotence is
        rejected on purpose (``ALREADY_EXISTS``) rather than silently returning: a typo'd
        id must not look like a success.
        """
        self._reject_if_pinned()
        project_id = request.id.strip()
        name = request.name.strip()
        if not name:
            raise ConnectError(Code.INVALID_ARGUMENT, "name is required")
        if project_id in _RESERVED_PROJECT_IDS:
            raise ConnectError(Code.INVALID_ARGUMENT, f"project id {project_id!r} is reserved")
        # _lookup_project validates the id shape (INVALID_ARGUMENT) and maps a malformed
        # registry file to INTERNAL; a hit means the id is taken.
        if self._lookup_project(project_id) is not None:
            raise ConnectError(Code.ALREADY_EXISTS, f"project {project_id!r} already exists")
        project = Project(
            id=project_id,
            name=name,
            description=request.description if request.HasField("description") else "",
            accent=request.accent if request.HasField("accent") else "",
        )
        self._ctx.registry.write(project)
        return pb.CreateProjectResponse(project=convert.project_pb(project))

    async def list_project_runs(self, request: Any, ctx: Any) -> Any:
        if self._ctx.pinned_run is not None:
            run = self._pinned_run()
            runs = [run] if request.project_id == run.project_id else []
            return pb.ListProjectRunsResponse(runs=[convert.run_pb(r) for r in runs])
        project_id = self._require_project_id(request.project_id)
        runs = self._collect_runs(project_id=project_id)
        return pb.ListProjectRunsResponse(runs=[convert.run_pb(run) for run in runs])

    async def list_runs(self, request: Any, ctx: Any) -> Any:
        if self._ctx.pinned_run is not None:
            run = self._pinned_run()
            project_id = request.project_id if request.HasField("project_id") else None
            runs = [run] if project_id in (None, run.project_id) else []
            return pb.ListRunsResponse(runs=[convert.run_pb(r) for r in runs])
        project_id = request.project_id if request.HasField("project_id") else None
        if project_id is not None:
            project_id = self._require_project_id(project_id)
        runs = self._collect_runs(project_id=project_id)
        return pb.ListRunsResponse(runs=[convert.run_pb(run) for run in runs])

    async def get_run(self, request: Any, ctx: Any) -> Any:
        if self._ctx.pinned_run is not None:
            return self._get_pinned_run(request)
        run_id = request.run_id
        if not is_run_id(run_id):
            raise ConnectError(Code.NOT_FOUND, f"run {run_id!r} not found")
        store = RunStore(self._ctx.runs_dir / run_id)
        if not store.events_path.is_file():
            raise ConnectError(Code.NOT_FOUND, f"run {run_id!r} not found")
        at_event = request.at_event if request.HasField("at_event") else None
        try:
            return pb.GetRunResponse(run_detail=self._run_detail(store, at_event=at_event))
        except (BlackboardError, ReduceError, ReportError) as exc:
            raise ConnectError(
                Code.INTERNAL, f"run {run_id!r} has a malformed event log: {exc}"
            ) from exc

    async def get_run_graph(self, request: Any, ctx: Any) -> Any:
        """The light graph projection polled by the console (dashboard.md §4)."""
        store = self._read_store(request.run_id)
        at_event = request.at_event if request.HasField("at_event") else None
        try:
            events, board, run = self._folded_board(store, at_event=at_event)
        except (BlackboardError, ReduceError, ReportError) as exc:
            raise ConnectError(
                Code.INTERNAL, f"run {request.run_id!r} has a malformed event log: {exc}"
            ) from exc
        return pb.GetRunGraphResponse(
            graph=convert.run_graph_pb(run, board, event_count=len(events))
        )

    async def get_fact_detail(self, request: Any, ctx: Any) -> Any:
        """One Fact with its verbatim evidence; fetched on node click, not polled."""
        if not request.fact_id:
            raise ConnectError(Code.INVALID_ARGUMENT, "fact_id is required")
        store = self._read_store(request.run_id)
        at_event = request.at_event if request.HasField("at_event") else None
        try:
            folded = self._folded_events(store.read_events(), at_event)
            board = reduce(folded)
        except (BlackboardError, ReduceError) as exc:
            raise ConnectError(
                Code.INTERNAL, f"run {request.run_id!r} has a malformed event log: {exc}"
            ) from exc
        fact = board.fact(request.fact_id)
        if fact is None and board.origin.id == request.fact_id:
            fact = board.origin
        if fact is None and board.goal.id == request.fact_id:
            fact = board.goal
        if fact is None:
            raise ConnectError(
                Code.NOT_FOUND, f"fact {request.fact_id!r} not found in run {request.run_id!r}"
            )
        return pb.GetFactDetailResponse(fact=convert.fact_pb(fact))

    async def list_events(self, request: Any, ctx: Any) -> Any:
        """The event timeline (EVENTS tab); optionally sliced for Replay."""
        store = self._read_store(request.run_id)
        at_event = request.at_event if request.HasField("at_event") else None
        try:
            events = store.read_events()
            folded = self._folded_events(events, at_event)
        except (BlackboardError, ReduceError, ReportError) as exc:
            raise ConnectError(
                Code.INTERNAL, f"run {request.run_id!r} has a malformed event log: {exc}"
            ) from exc
        return pb.ListEventsResponse(events=[convert.event_pb(event) for event in folded])

    async def list_sessions(self, request: Any, ctx: Any) -> Any:
        """Worker session snapshots; the Inspector fetches these on demand."""
        store = self._read_store(request.run_id)
        try:
            sessions = store.read_sessions()
        except BlackboardError as exc:
            raise ConnectError(
                Code.INTERNAL, f"run {request.run_id!r} has a malformed session log: {exc}"
            ) from exc
        if request.HasField("intent_id"):
            intent_id = str(request.intent_id)
            sessions = [s for s in sessions if s.get("intentId") == intent_id]
        return pb.ListSessionsResponse(sessions=[convert.session_pb(s) for s in sessions])

    async def create_run(self, request: Any, ctx: Any) -> Any:
        """Start a run: persist the input, schedule the engine, return the run (C3b).

        The engine runs as a background task; this RPC waits only until the ``PROJECT``
        event lands so any following ``GetRun`` can already read the board. ``auto``
        defaults to ``[hitl].auto`` when the request does not set it.
        """
        self._reject_if_pinned()
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
            # Static, non-secret runtime snapshot. A Gate resume must use the same
            # Pi image and container lease even if project Settings changed meanwhile.
            "runtime": self._ctx.config.to_dict(),
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
        task = self._ctx.scheduler.start(
            run_id, self._run_initial(engine, store, origin=origin, goal=goal, auto=auto)
        )
        await self._await_project(store, task)
        run = summarize_run(store, meta=meta, budget=self._ctx.config.worker.budget)
        return pb.CreateRunResponse(run=convert.run_pb(run))

    async def add_hint(self, request: Any, ctx: Any) -> Any:
        """Append a human Hint (non-blocking, C3b)."""
        self._reject_if_pinned()
        store = self._require_run_store(request.run_id)
        next_index = sum(1 for event in store.iter_events() if event.type == "HINT") + 1
        hint = Hint(id=f"h{next_index}", text=request.text, author="human", createdAt=now_iso())
        store.append_event("HINT", {"hint": hint.to_dict()}, message="Hint added")
        return pb.AddHintResponse(hint=convert.hint_pb(hint))

    async def submit_human_input(self, request: Any, ctx: Any) -> Any:
        """Resolve a paused gate and continue the run (C3b; fresh-engine resume)."""
        self._reject_if_pinned()
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
        if pending not in (GATE_A, GATE_B):
            # Gate C (review) lands in M3; a matching-but-unknown gate is not a client
            # argument error, so report it as unimplemented rather than 400.
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
        await self._release_if_terminal(store)
        run = summarize_run(
            store, meta=store.read_run_meta(), budget=self._ctx.config.worker.budget
        )
        return pb.SubmitHumanInputResponse(run=convert.run_pb(run))

    async def get_settings(self, request: Any, ctx: Any) -> Any:
        """Return the live project settings (M6 P3; read-only, allowed when pinned)."""
        return pb.GetSettingsResponse(settings=convert.settings_pb(self._ctx.config))

    async def update_settings(self, request: Any, ctx: Any) -> Any:
        """Validate, persist to ``originweave.toml`` and apply new settings (M6 P3).

        New runs (and later gate resumes) pick up the rebuilt providers; a run already
        in flight keeps the providers it started with.
        """
        self._reject_if_pinned()
        try:
            new_config = _config_from_settings(self._ctx.config, request.settings)
        except ConfigError as exc:
            raise ConnectError(Code.INVALID_ARGUMENT, str(exc)) from exc
        try:
            save_config(new_config, self._ctx.config_path)
        except OSError as exc:
            raise ConnectError(Code.INTERNAL, f"could not write settings: {exc}") from exc
        # Swap the live config/providers only after the file is safely persisted, so a
        # failed write leaves memory and disk consistent.
        try:
            self._ctx.apply_settings(new_config)
        except CapabilityError as exc:
            raise ConnectError(Code.INTERNAL, f"could not apply settings: {exc}") from exc
        return pb.UpdateSettingsResponse(settings=convert.settings_pb(new_config))

    async def shutdown(self) -> None:
        """Fail and reclaim non-terminal shared Pi containers during server shutdown."""
        for run_dir in list(self._ctx.run_workers):
            store = RunStore(run_dir)
            try:
                await self._ctx.scheduler.cancel(run_dir.name)
                engine = self._build_engine(store, auto=False)
                await engine.fail_runtime("server shutdown released shared worker container")
            finally:
                await self._ctx.release_run_worker(run_dir)

    async def _run_initial(
        self, engine: Engine, store: RunStore, *, origin: Fact, goal: Fact, auto: bool
    ) -> Any:
        board = await engine.run(origin=origin, goal=goal, auto=auto)
        await self._release_if_terminal(store)
        return board

    async def _release_if_terminal(self, store: RunStore) -> None:
        board = reduce(store.read_events())
        if board.status in {"completed", "failed", "stopped"}:
            await self._ctx.release_run_worker(store.root)

    async def search(self, request: Any, ctx: Any) -> Any:
        """Run a retrieval through the configured search provider (M6 P3b).

        Read-only, so it is allowed in the pinned single-run view too. The Pi TS
        extension (P4) calls this so the provider choice stays in Python: switching
        ``[capability.search]`` needs no extension change (red line 5).
        """
        query = request.query.strip()
        if not query:
            raise ConnectError(Code.INVALID_ARGUMENT, "query is required")
        num_results = request.num_results if request.HasField("num_results") else 8
        if num_results <= 0 or num_results > _MAX_SEARCH_RESULTS:
            raise ConnectError(
                Code.INVALID_ARGUMENT,
                f"num_results must be in 1..{_MAX_SEARCH_RESULTS}, got {num_results}",
            )
        try:
            text = await self._ctx.providers.search.search(query, num_results=num_results)
        except CapabilityError as exc:
            raise ConnectError(Code.UNAVAILABLE, str(exc)) from exc
        return pb.SearchResponse(text=text)

    def _build_engine(self, store: RunStore, *, auto: bool) -> Engine:
        """Build an engine over ``store`` using its immutable runtime snapshot."""
        config = self._runtime_config(store)
        worker = config.worker
        resolved_worker = self._ctx.worker_for(store.root, config=config)
        engine = Engine(
            worker=resolved_worker,
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
        if isinstance(resolved_worker, RunContainerWorker):
            async def fail_lease(reason: str) -> None:
                await engine.fail_runtime(reason)
                await self._ctx.release_run_worker(store.root)

            resolved_worker.set_failure_callback(fail_lease)
        return engine

    def _runtime_config(self, store: RunStore) -> Config:
        """The configuration frozen at CreateRun, with a legacy-run fallback."""
        meta = store.read_run_meta() or {}
        runtime = meta.get("runtime")
        if isinstance(runtime, dict):
            snapshot = from_dict(runtime)
            snapshot.validate()
            return snapshot
        return self._ctx.config

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

    def _reject_if_pinned(self) -> None:
        """Write RPCs are disabled in the single-run (``ui --run``) view (C4)."""
        if self._ctx.pinned_run is not None:
            raise ConnectError(Code.FAILED_PRECONDITION, "the single-run view is read-only")

    def _pinned_store(self) -> RunStore:
        path = self._ctx.pinned_run
        assert path is not None  # only called after a pinned_run check
        store = RunStore(path)
        if not store.events_path.is_file():
            raise ConnectError(Code.NOT_FOUND, f"run {path.name!r} not found")
        return store

    @staticmethod
    def _run_id_of(store: RunStore) -> str:
        """A pinned run's id: its ``run.json`` id, else the directory name."""
        try:
            meta = store.read_run_meta()
        except BlackboardError:
            meta = None
        run_id = meta.get("id") if isinstance(meta, dict) else None
        return run_id if isinstance(run_id, str) and run_id else store.root.name

    def _pinned_run(self) -> Run:
        store = self._pinned_store()
        try:
            run = summarize_run(
                store, meta=store.read_run_meta(), budget=self._ctx.config.worker.budget
            )
        except (BlackboardError, ReduceError, OSError) as exc:
            raise ConnectError(
                Code.INTERNAL, f"run {store.root.name!r} is unreadable: {exc}"
            ) from exc
        # A run without run.json (the committed sample) has no project; put it in a
        # synthetic one so lists and the run detail agree on the id.
        if not run.project_id:
            run.project_id = _SAMPLE_PROJECT_ID
        return run

    def _pinned_project(self) -> Project:
        run = self._pinned_run()
        return Project(
            id=run.project_id,
            name=run.title or "Sample",
            run_count=1,
            updated_at=run.updated_at,
        )

    def _get_pinned_run(self, request: Any) -> Any:
        store = self._pinned_store()
        if request.run_id != self._run_id_of(store):
            raise ConnectError(Code.NOT_FOUND, f"run {request.run_id!r} not found")
        at_event = request.at_event if request.HasField("at_event") else None
        try:
            return pb.GetRunResponse(run_detail=self._run_detail(store, at_event=at_event))
        except (BlackboardError, ReduceError, ReportError) as exc:
            raise ConnectError(
                Code.INTERNAL, f"run {request.run_id!r} has a malformed event log: {exc}"
            ) from exc

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

    def _read_store(self, run_id: str) -> RunStore:
        """RunStore for a read RPC, honouring the pinned single-run mode."""
        if self._ctx.pinned_run is not None:
            store = self._pinned_store()
            if run_id != self._run_id_of(store):
                raise ConnectError(Code.NOT_FOUND, f"run {run_id!r} not found")
            return store
        if not is_run_id(run_id):
            raise ConnectError(Code.NOT_FOUND, f"run {run_id!r} not found")
        store = RunStore(self._ctx.runs_dir / run_id)
        if not store.events_path.is_file():
            raise ConnectError(Code.NOT_FOUND, f"run {run_id!r} not found")
        return store

    def _folded_board(
        self, store: RunStore, *, at_event: int | None
    ) -> tuple[list[Event], Any, Run]:
        """(full events, folded board, folded run summary) shared by the read RPCs."""
        events = store.read_events()
        folded = self._folded_events(events, at_event)
        board = reduce(folded)
        run = summarize_run(
            store,
            meta=store.read_run_meta(),
            budget=self._ctx.config.worker.budget,
            events=folded,
        )
        return events, board, run

    def _run_detail(self, store: RunStore, *, at_event: int | None = None) -> Any:
        events = store.read_events()
        folded = self._folded_events(events, at_event)
        board = reduce(folded)
        run = summarize_run(
            store,
            meta=store.read_run_meta(),
            budget=self._ctx.config.worker.budget,
            events=folded,
        )
        # The board is folded to `at_event` (Replay), but the timeline keeps the full
        # log so its length stays stable while stepping. `source_text` only feeds the
        # retry flow, which is offered for terminal failures, so we skip reading the
        # document on every (polled) GetRun of an active run.
        source_text = (
            self._read_source_text(store) if board.status in _RETRYABLE_STATUSES else ""
        )
        return convert.run_detail_pb(
            run,
            board,
            events,
            sessions=store.read_sessions(),
            source_text=source_text,
        )

    @staticmethod
    def _read_source_text(store: RunStore) -> str:
        """Document A's text (``input/document.md``) for the retry flow; '' if absent."""
        path = store.input_dir / "document.md"
        try:
            return path.read_text(encoding="utf-8") if path.is_file() else ""
        except (OSError, UnicodeDecodeError):
            return ""

    @staticmethod
    def _folded_events(events: list[Event], at_event: int | None) -> list[Event]:
        """The event prefix to fold for Replay; ``None`` folds the whole log."""
        if at_event is None:
            return events
        if at_event < 1 or at_event > len(events):
            raise ConnectError(
                Code.INVALID_ARGUMENT,
                f"at_event must be within 1..{len(events)}; got {at_event}",
            )
        return events[:at_event]
