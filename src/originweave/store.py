"""Run storage: the event log, its backends, and the run directory layout.

A run directory looks like::

    <run-dir>/
    ├── events.jsonl        # live backend (append-only, one Event per line)
    ├── events.db           # optional self-contained SQLite binding (sample/exports)
    ├── input/              # document A snapshot
    ├── sources/            # source snapshots
    ├── sessions/           # per-worker-call session snapshots (raw in/out + steps)
    └── report.md           # final artefact             (populated in M2)

The event log sits behind the :class:`EventLog` protocol; :class:`RunStore` is a
facade that owns the directory layout and delegates log storage to a backend.
:class:`JsonlEventLog` is the live server backend; :class:`SqliteEventLog` is the
migration target and is used for bundled sample databases (and by anything that
explicitly stores a run's events in the workspace database).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Protocol

from .blackboard import BlackboardError
from .events import DEFAULT_TONE, Event, format_event_id, now_iso
from .sqlite_backend import SqliteEventLog, sqlite_run_has_events

_SESSION_SUFFIX_RE = re.compile(r"(\d+)$")

BUNDLED_DB_FILENAME = "events.db"


def _session_sort_key(path: Path) -> tuple[int, str]:
    """Sort ``sess_NNN`` snapshots numerically (so ``sess_1000`` follows ``sess_999``)."""
    match = _SESSION_SUFFIX_RE.search(path.stem)
    return (int(match.group(1)) if match else 0, path.stem)


def _validate_session(path: Path, data: Mapping[str, Any]) -> None:
    """Reject a structurally malformed session snapshot as a :class:`BlackboardError`.

    Guards the type assumptions the proto mapper makes (``input`` an object, ``steps``
    a list of objects with an integer ``seq``) so bad data becomes a clean INTERNAL
    rather than a leaked ``ParseError``/``AttributeError``/``ValueError``.
    """
    source = data.get("input")
    if source is not None and not isinstance(source, dict):
        raise BlackboardError(f"{path}: session.input must be an object")
    steps = data.get("steps", [])
    if not isinstance(steps, list):
        raise BlackboardError(f"{path}: session.steps must be a list")
    for step in steps:
        if not isinstance(step, dict):
            raise BlackboardError(f"{path}: session step must be an object")
        seq = step.get("seq")
        if seq is not None and (isinstance(seq, bool) or not isinstance(seq, int)):
            raise BlackboardError(f"{path}: session step seq must be an integer")


class EventLog(Protocol):
    """Storage backend for one run's append-only event log.

    Implementations must preserve append order, derive ``Event.id`` sequences
    without gaps, and scope every operation to a single run. ``has_events`` is a
    cheap existence probe: it never parses stored payloads, so a corrupt log
    still reads as "present" and the read path can report it as malformed.
    """

    def append(self, event: Event) -> None: ...

    def iter_events(self) -> Iterator[Event]: ...

    def count(self) -> int: ...

    def count_type(self, event_type: str) -> int: ...

    def has_events(self) -> bool: ...

    def close(self) -> None: ...


class JsonlEventLog:
    """Legacy backend: ``events.jsonl``, one JSON object per line, append-only."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._count: int | None = None

    @property
    def path(self) -> Path:
        return self._root / "events.jsonl"

    def append(self, event: Event) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), sort_keys=True, ensure_ascii=False))
            handle.write("\n")
        # Keep the warm count cache correct; ``None`` means "rescan on next read".
        if self._count is not None:
            self._count += 1

    def iter_events(self) -> Iterator[Event]:
        """Yield events in append order, raising on malformed lines."""
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise BlackboardError(f"{self.path}:{lineno}: invalid JSON: {exc}") from exc
                if not isinstance(data, dict):
                    raise BlackboardError(f"{self.path}:{lineno}: event must be a JSON object")
                yield Event.from_dict(data)

    def count(self) -> int:
        if self._count is None:
            if not self.path.is_file():
                self._count = 0
            else:
                self._count = sum(1 for _ in self.iter_events())
        return self._count

    def count_type(self, event_type: str) -> int:
        return sum(1 for event in self.iter_events() if event.type == event_type)

    def has_events(self) -> bool:
        """True when the log file exists with at least one non-blank line."""
        if not self.path.is_file():
            return False
        with self.path.open("r", encoding="utf-8") as handle:
            return any(line.strip() for line in handle)

    def close(self) -> None:
        return None


class RunStore:
    """Read/write access to a single run directory and its event log."""

    def __init__(self, root: Path, *, log: EventLog | None = None) -> None:
        self._root = Path(root)
        self._log: EventLog = log if log is not None else JsonlEventLog(self._root)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def events_path(self) -> Path:
        """Legacy JSONL path; only meaningful with the JSONL backend."""
        return self._root / "events.jsonl"

    @property
    def input_dir(self) -> Path:
        return self._root / "input"

    @property
    def sources_dir(self) -> Path:
        return self._root / "sources"

    @property
    def sessions_dir(self) -> Path:
        return self._root / "sessions"

    @property
    def report_path(self) -> Path:
        return self._root / "report.md"

    @property
    def run_json_path(self) -> Path:
        return self._root / "run.json"

    def init_layout(self) -> None:
        """Create the run directory and its sub-directories."""
        self._root.mkdir(parents=True, exist_ok=True)
        for directory in (self.input_dir, self.sources_dir, self.sessions_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def event_count(self) -> int:
        return self._log.count()

    def has_events(self) -> bool:
        """True when the run has at least one event (backend-agnostic existence)."""
        return self._log.has_events()

    def iter_events(self) -> Iterator[Event]:
        """Yield events in append order, raising on malformed stored data."""
        return self._log.iter_events()

    def read_events(self) -> list[Event]:
        return list(self.iter_events())

    def next_hint_id(self) -> str:
        """The next Hint id (``h<N>``), derived from the HINT events already written.

        Both writers of hints (the server's ``AddHint`` and the engine's agent-side
        Reason hints) must derive ids from the event log so a human hint and an agent
        hint interleaved in the same run never collide (blackboard-protocol.md §2.3).
        """
        return f"h{self._log.count_type('HINT') + 1}"

    def close(self) -> None:
        """Release backend resources (no-op for the JSONL backend)."""
        self._log.close()

    def read_sessions(self) -> list[dict[str, Any]]:
        """Read the worker session snapshots under ``sessions/`` (M6 P3c).

        Returns every ``sessions/*.json`` in filename order (``sess_NNN`` sorts
        chronologically); an absent directory yields ``[]`` (e.g. the committed
        sample). Raises :class:`BlackboardError` on malformed content, mirroring
        :meth:`read_events`.
        """
        if not self.sessions_dir.is_dir():
            return []
        sessions: list[dict[str, Any]] = []
        for path in sorted(self.sessions_dir.glob("*.json"), key=_session_sort_key):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise BlackboardError(f"{path}: invalid JSON: {exc}") from exc
            if not isinstance(data, dict):
                raise BlackboardError(f"{path}: session must be a JSON object")
            _validate_session(path, data)
            sessions.append(data)
        return sessions

    def append_event(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        message: str = "",
        tone: str | None = None,
        at: str | None = None,
    ) -> Event:
        """Append an event, assigning a monotonic id and a UTC timestamp."""
        resolved_tone = tone if tone is not None else DEFAULT_TONE.get(event_type, "info")
        sequence = self.event_count() + 1
        event = Event(
            id=format_event_id(sequence),
            at=at if at is not None else now_iso(),
            type=event_type,
            payload=dict(payload or {}),
            message=message,
            tone=resolved_tone,
        )
        self._log.append(event)
        return event

    def write_input(self, name: str, content: str) -> Path:
        """Write one input file (e.g. document A) under ``input/``.

        Not an event: the input snapshot is launch material, not board state. ``name``
        must be a bare filename so a caller cannot escape the run directory.
        """
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            raise BlackboardError(f"input name must be a bare filename, got {name!r}")
        self.input_dir.mkdir(parents=True, exist_ok=True)
        path = self.input_dir / name
        path.write_text(content, encoding="utf-8")
        return path

    def write_report(self, content: str) -> Path:
        """Write the rendered deviation scorecard as ``report.md``.

        Not an event: the report is a *derivation* from the board, so it can always be
        rebuilt from the event log (M2). ``replay`` never calls this.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(content, encoding="utf-8")
        return self.report_path

    def write_session(self, session_id: str, session: Mapping[str, Any]) -> Path:
        """Write the raw session snapshot for one worker call (M6).

        The snapshot holds the untruncated raw input/output and step chain; the
        ``SESSION`` / ``WORKER_STEP`` events only index it. Not an event: the board
        never derives from it, so ``replay`` of the board is unaffected.
        """
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self.sessions_dir / f"{session_id}.json"
        with path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(session, sort_keys=True, ensure_ascii=False, indent=2))
            handle.write("\n")
        return path

    def read_run_meta(self) -> dict[str, Any] | None:
        """Read ``run.json`` (static run metadata) or ``None`` when it is absent.

        This file only holds launch/static fields (project, title, source_type,
        analysis, goal, budget overrides, ...); the board and its counts are always
        derived from the event log. Raises :class:`BlackboardError` on malformed
        content, mirroring :meth:`read_events`.
        """
        if not self.run_json_path.is_file():
            return None
        try:
            data = json.loads(self.run_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise BlackboardError(f"{self.run_json_path}: invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise BlackboardError(f"{self.run_json_path}: run metadata must be a JSON object")
        return data

    def write_run_meta(self, meta: Mapping[str, Any]) -> Path:
        """Write ``run.json`` (static run metadata); overwrite, not an event."""
        self._root.mkdir(parents=True, exist_ok=True)
        with self.run_json_path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(meta), sort_keys=True, ensure_ascii=False, indent=2))
            handle.write("\n")
        return self.run_json_path


def run_has_events(run_dir: Path, *, db_path: Path | None = None) -> bool:
    """Backend-agnostic existence probe: does this run have any event?

    Read-only and connection-free by design (the server calls it on every polled
    read RPC, so it must not run DDL or keep a connection). Checks the legacy
    ``events.jsonl`` first, then a bundled ``events.db``, then the workspace
    database.
    """
    run_dir = Path(run_dir)
    if JsonlEventLog(run_dir).has_events():
        return True
    bundled = run_dir / BUNDLED_DB_FILENAME
    if bundled.is_file() and sqlite_run_has_events(bundled, run_dir.name):
        return True
    return db_path is not None and sqlite_run_has_events(Path(db_path), run_dir.name)


def open_run_store(run_dir: Path, *, db_path: Path | None = None) -> RunStore:
    """Open a run with the right event-log backend.

    Probe order:

    1. a bundled ``<run-dir>/events.db`` that holds this run's events
       (self-contained sample/exports) wins;
    2. when the workspace database already holds events for this run, that
       database is authoritative (a run migrated into SQLite keeps reading there
       even if a stale ``events.jsonl`` lingers);
    3. otherwise the legacy JSONL backend is used. The live server keeps writing
       ``events.jsonl``; the workspace database currently stores only the
       static run/project metadata. The SQLite event backend is the migration
       target, exercised today by bundled runs and by explicit imports.
    """
    run_dir = Path(run_dir)
    bundled = run_dir / BUNDLED_DB_FILENAME
    if bundled.is_file() and sqlite_run_has_events(bundled, run_dir.name):
        return RunStore(run_dir, log=SqliteEventLog(bundled, run_dir.name))
    if db_path is not None and sqlite_run_has_events(Path(db_path), run_dir.name):
        return RunStore(run_dir, log=SqliteEventLog(Path(db_path), run_dir.name))
    return RunStore(run_dir)


__all__ = [
    "BUNDLED_DB_FILENAME",
    "EventLog",
    "JsonlEventLog",
    "RunStore",
    "open_run_store",
    "run_has_events",
]
