"""Run/project persistence for the server (M1c-1 C2).

Two layers, per ``docs/overview/agent-design.md`` section 5:

- ``events.jsonl`` is the **sole source of truth** for a run's board.
- ``run.json`` holds only the run's **static/launch metadata** (project, title,
  source_type, analysis, goal, created_at, budget overrides, ...); every derived
  field (status, counts, steps, updated_at) is recomputed from the events by
  :func:`summarize_run`, so it can never drift from the log.

Projects are a directory registry: ``projects/<project_id>/project.json`` holds
the static fields, while ``run_count``/``updated_at`` are derived by scanning the
run directories at read time.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .blackboard import BlackboardError
from .config import BudgetConfig
from .events import Event
from .reduce import reduce
from .store import RunStore, open_run_store
from .workspace import WorkspaceStore

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_RUN_ID_RE = re.compile(r"run_(\d+)")


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _terminal_reason(events: Sequence[Event]) -> str:
    """The last ``FAILED``/``STOPPED`` event's ``reason`` ("" when there is none).

    The terminal reason is a *derived* field: it lives in the event log and is only
    surfaced when the folded board ends in a terminal state (see ``summarize_run``).
    """
    reason = ""
    for event in events:
        if event.type in ("FAILED", "STOPPED"):
            value = event.payload.get("reason")
            reason = value if isinstance(value, str) else ""
    return reason


@dataclass
class IntentCounts:
    open: int = 0
    done: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"open": self.open, "done": self.done}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> IntentCounts:
        return cls(open=_int(data.get("open")), done=_int(data.get("done")))


@dataclass
class Steps:
    current: int = 0
    total: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"current": self.current, "total": self.total}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Steps:
        return cls(current=_int(data.get("current")), total=_int(data.get("total")))


@dataclass
class Budget:
    tokens: int = 0
    cost: float = 0.0
    elapsed: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"tokens": self.tokens, "cost": self.cost, "elapsed": self.elapsed}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Budget:
        return cls(
            tokens=_int(data.get("tokens")),
            cost=_float(data.get("cost")),
            elapsed=_str(data.get("elapsed")),
        )


@dataclass
class Run:
    """The proto ``Run`` read model (static fields + event-derived fields)."""

    id: str
    project_id: str = ""
    title: str = ""
    source_type: str = "text"
    analysis: str = "provenance"
    status: str = "queued"
    status_reason: str = ""
    goal: str = ""
    facts: int = 0
    deviations: int = 0
    entities: int = 0
    relations: int = 0
    intents: IntentCounts = field(default_factory=IntentCounts)
    confidence: float = 0.0
    steps: Steps = field(default_factory=Steps)
    budget: Budget = field(default_factory=Budget)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "source_type": self.source_type,
            "analysis": self.analysis,
            "status": self.status,
            "status_reason": self.status_reason,
            "goal": self.goal,
            "facts": self.facts,
            "deviations": self.deviations,
            "entities": self.entities,
            "relations": self.relations,
            "intents": self.intents.to_dict(),
            "confidence": self.confidence,
            "steps": self.steps.to_dict(),
            "budget": self.budget.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Run:
        intents = data.get("intents")
        steps = data.get("steps")
        budget = data.get("budget")
        return cls(
            id=_str(data.get("id")),
            project_id=_str(data.get("project_id")),
            title=_str(data.get("title")),
            source_type=_str(data.get("source_type")) or "text",
            analysis=_str(data.get("analysis")) or "provenance",
            status=_str(data.get("status")) or "queued",
            status_reason=_str(data.get("status_reason")),
            goal=_str(data.get("goal")),
            facts=_int(data.get("facts")),
            deviations=_int(data.get("deviations")),
            entities=_int(data.get("entities")),
            relations=_int(data.get("relations")),
            intents=IntentCounts.from_dict(intents if isinstance(intents, dict) else {}),
            confidence=_float(data.get("confidence")),
            steps=Steps.from_dict(steps if isinstance(steps, dict) else {}),
            budget=Budget.from_dict(budget if isinstance(budget, dict) else {}),
            created_at=_str(data.get("created_at")),
            updated_at=_str(data.get("updated_at")),
        )


@dataclass
class Project:
    """A project registry entry; ``run_count``/``updated_at`` are derived."""

    id: str
    name: str = ""
    description: str = ""
    run_count: int = 0
    updated_at: str = ""
    accent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "run_count": self.run_count,
            "updated_at": self.updated_at,
            "accent": self.accent,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Project:
        return cls(
            id=_str(data.get("id")),
            name=_str(data.get("name")),
            description=_str(data.get("description")),
            run_count=_int(data.get("run_count")),
            updated_at=_str(data.get("updated_at")),
            accent=_str(data.get("accent")),
        )


def is_run_id(name: str) -> bool:
    """True if ``name`` looks like a run directory id (``run_<digits>``)."""
    return _RUN_ID_RE.fullmatch(name) is not None


def allocate_run_id(runs_dir: Path, workspace: WorkspaceStore | None = None) -> str:
    """Return the next global ``run_00N`` id.

    Scans ``runs_dir`` (legacy directories) and, when a workspace database is
    given, its ``runs`` table; the id must be free in *both* stores.
    """
    highest = 0
    if runs_dir.is_dir():
        for entry in runs_dir.iterdir():
            if not entry.is_dir():
                continue
            match = _RUN_ID_RE.fullmatch(entry.name)
            if match is not None:
                highest = max(highest, int(match.group(1)))
    if workspace is not None:
        highest = max(highest, workspace.max_run_seq())
    return f"run_{highest + 1:03d}"


def load_run_meta(
    store: RunStore, workspace: WorkspaceStore | None, run_id: str | None = None
) -> dict[str, Any] | None:
    """Static run metadata: the workspace database first, ``run.json`` as fallback.

    Legacy runs (and the committed sample) have no workspace row, so the
    directory file stays their source; server-created runs are authoritative in
    the database.
    """
    if workspace is not None:
        meta = workspace.get_run_meta(run_id if run_id is not None else store.root.name)
        if meta is not None:
            return meta
    return store.read_run_meta()


def _format_elapsed(events: Sequence[Event]) -> str:
    """Human-readable wall time between the first and last event (e.g. ``1m02s``)."""
    if len(events) < 2:
        return ""
    try:
        first = datetime.fromisoformat(events[0].at)
        last = datetime.fromisoformat(events[-1].at)
        if first.tzinfo is None and last.tzinfo is not None:
            first = first.replace(tzinfo=last.tzinfo)
        elif last.tzinfo is None and first.tzinfo is not None:
            last = last.replace(tzinfo=first.tzinfo)
        seconds = (last - first).total_seconds()
    except (ValueError, TypeError):
        return ""
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}m{rest:02d}s"


def summarize_run(
    store: RunStore,
    *,
    meta: Mapping[str, Any] | None = None,
    budget: BudgetConfig | None = None,
    events: Sequence[Event] | None = None,
) -> Run:
    """Build a :class:`Run` from a run directory: static fields from ``run.json``
    (when present), everything else from the event log.

    Works for directories without ``run.json`` (e.g. the committed sample), which
    is why the static fields that can only come from metadata fall back to the
    directory name / defaults. Result fields (status/updated_at/counts) are always
    derived from the events; a ``status`` in ``run.json`` is ignored. ``confidence``
    stays zero until the milestone that produces it. ``budget`` tokens/cost come from
    the per-call ``SESSION`` events (M3b) and ``elapsed`` from the first/last event.

    ``events`` overrides the log to fold (Replay's ``at_event`` passes a prefix); the
    default reads the full log from ``store``. Passing ``events`` (even an empty
    sequence) means "fold exactly this" and never falls back to the store.
    """
    meta = dict(meta) if meta is not None else {}
    events = list(events) if events is not None else store.read_events()
    board = reduce(events) if events else None

    intents = IntentCounts()
    if board is not None:
        for intent in board.intents:
            if intent.status == "open":
                intents.open += 1
            elif intent.status == "done":
                intents.done += 1

    budget_meta = meta.get("budget")
    max_steps = _int(budget_meta.get("max_steps")) if isinstance(budget_meta, dict) else 0
    if max_steps <= 0 and budget is not None:
        max_steps = budget.max_steps

    sessions = sum(1 for event in events if event.type == "SESSION")
    tokens = sum(_int(event.payload.get("tokens")) for event in events if event.type == "SESSION")
    cost = sum(_float(event.payload.get("cost")) for event in events if event.type == "SESSION")
    return Run(
        id=_str(meta.get("id")) or store.root.name,
        project_id=_str(meta.get("project_id")),
        title=_str(meta.get("title")) or store.root.name,
        source_type=_str(meta.get("source_type")) or "text",
        analysis=_str(meta.get("analysis")) or "provenance",
        status=board.status if board is not None else "queued",
        status_reason=(
            _terminal_reason(events)
            if board is not None and board.status in {"failed", "stopped"}
            else ""
        ),
        goal=_str(meta.get("goal")) or (board.goal.label if board is not None else ""),
        facts=len(board.facts) if board is not None else 0,
        deviations=sum(1 for fact in board.facts if fact.kind == "deviation")
        if board is not None
        else 0,
        intents=intents,
        steps=Steps(current=sessions, total=max_steps),
        budget=Budget(tokens=tokens, cost=cost, elapsed=_format_elapsed(events)),
        created_at=_str(meta.get("created_at")) or (events[0].at if events else ""),
        updated_at=events[-1].at if events else "",
    )


class ProjectRegistry:
    """Project registry: the workspace database first, legacy directories as fallback.

    With a :class:`~originweave.workspace.WorkspaceStore` attached, writes go to
    both stores (the directory keeps serving tooling that reads it directly) and
    reads prefer the database. Without one, the class behaves exactly like the
    original directory registry.
    """

    def __init__(
        self,
        projects_dir: Path,
        runs_dir: Path,
        *,
        workspace: WorkspaceStore | None = None,
    ) -> None:
        self._projects_dir = Path(projects_dir)
        self._runs_dir = Path(runs_dir)
        self._workspace = workspace

    def path(self, project_id: str) -> Path:
        """Return the ``project.json`` path for ``project_id`` (validates the id)."""
        if not _ID_RE.fullmatch(project_id):
            raise ValueError(f"invalid project id {project_id!r}")
        return self._projects_dir / project_id / "project.json"

    def get(self, project_id: str) -> Project | None:
        if self._workspace is not None:
            data = self._workspace.get_project(project_id)
            if data is not None:
                return self._with_usage(
                    Project(
                        id=data["id"],
                        name=data["name"],
                        description=data["description"],
                        accent=data["accent"],
                    )
                )
        path = self.path(project_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise BlackboardError(f"{path}: invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise BlackboardError(f"{path}: project metadata must be a JSON object")
        return self._with_usage(Project.from_dict(data))

    def list(self) -> list[Project]:
        projects: dict[str, Project] = {}
        if self._workspace is not None:
            for data in self._workspace.list_projects():
                projects[data["id"]] = Project(
                    id=data["id"],
                    name=data["name"],
                    description=data["description"],
                    accent=data["accent"],
                )
        if self._projects_dir.is_dir():
            for entry in sorted(self._projects_dir.iterdir()):
                # Skip stray entries the registry itself could not have created.
                if not entry.is_dir() or _ID_RE.fullmatch(entry.name) is None:
                    continue
                if entry.name in projects or not (entry / "project.json").is_file():
                    continue
                try:
                    project = self.get(entry.name)
                except BlackboardError:
                    # A single corrupt run must not break the whole registry listing.
                    continue
                if project is not None:
                    projects[entry.name] = project
        ordered = sorted(projects.values(), key=lambda project: project.id)
        return [self._with_usage(project) for project in ordered]

    def write(self, project: Project) -> Path:
        """Persist the static project fields (counts are never written).

        Written to a sibling temp file and replaced, so a crash mid-write cannot leave a
        corrupt ``project.json`` (a malformed file breaks ``list()``/the whole overview).
        With a workspace attached, the database row is updated as well.
        """
        path = self.path(project.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        static = {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "accent": project.accent,
        }
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_text(
            json.dumps(static, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
        if self._workspace is not None:
            self._workspace.upsert_project(
                project.id,
                name=project.name,
                description=project.description,
                accent=project.accent,
            )
        return path

    def ensure(self, project_id: str, *, name: str | None = None) -> Project:
        """Return the existing project or create a minimal one."""
        existing = self.get(project_id)
        if existing is not None:
            return existing
        project = Project(id=project_id, name=name or project_id)
        self.write(project)
        return self._with_usage(project)

    def _open_store(self, run_dir: Path) -> RunStore:
        """A store reading this run's events from whichever backend holds them."""
        db_path = self._workspace.path if self._workspace is not None else None
        return open_run_store(run_dir, db_path=db_path)

    def _with_usage(self, project: Project) -> Project:
        count = 0
        latest = ""
        db_run_ids: set[str] = set()
        if self._workspace is not None:
            count, latest = self._workspace.project_run_stats(project.id)
            db_run_ids = self._workspace.run_ids()
        if self._runs_dir.is_dir():
            for entry in self._runs_dir.iterdir():
                if not entry.is_dir():
                    continue
                in_db = entry.name in db_run_ids
                # A database row whose events also live in the database is already
                # folded by ``project_run_stats``. A bootstrapped legacy run has a
                # row but its events only on disk, so it still needs reading here
                # (without double-counting the run).
                if in_db and not (entry / "events.jsonl").is_file():
                    continue
                store: RunStore | None = None
                try:
                    # Opening may raise for a corrupt/foreign ``events.db``; that must
                    # not break the whole registry listing (the adjacent contract).
                    store = self._open_store(entry)
                    meta = store.read_run_meta()
                    if not meta or meta.get("project_id") != project.id:
                        continue
                    events = store.read_events()
                except (BlackboardError, OSError):
                    # A single corrupt run must not break the whole registry listing.
                    continue
                finally:
                    if store is not None:
                        store.close()
                if not in_db:
                    count += 1
                updated = events[-1].at if events else _str(meta.get("created_at"))
                latest = max(latest, updated)
        project.run_count = count
        project.updated_at = latest
        return project


__all__ = [
    "Budget",
    "IntentCounts",
    "Project",
    "ProjectRegistry",
    "Run",
    "Steps",
    "allocate_run_id",
    "is_run_id",
    "load_run_meta",
    "summarize_run",
]
