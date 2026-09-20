"""Run storage: the append-only event log and run directory layout.

A run directory looks like::

    <run-dir>/
    ├── events.jsonl        # append-only, one Event per line
    ├── input/              # document A snapshot
    ├── sources/            # source snapshots
    ├── sessions/           # per-worker-call session snapshots (raw in/out + steps)
    └── report.md           # final artefact             (populated in M2)
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from .blackboard import BlackboardError
from .events import DEFAULT_TONE, Event, format_event_id, now_iso

_SESSION_SUFFIX_RE = re.compile(r"(\d+)$")


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


class RunStore:
    """Read/write access to a single run directory."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._count: int | None = None

    @property
    def root(self) -> Path:
        return self._root

    @property
    def events_path(self) -> Path:
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
        if self._count is None:
            if not self.events_path.is_file():
                self._count = 0
            else:
                self._count = sum(1 for _ in self.iter_events())
        return self._count

    def iter_events(self) -> Iterator[Event]:
        """Yield events in append order, raising on malformed lines."""
        if not self.events_path.is_file():
            return
        with self.events_path.open("r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise BlackboardError(
                        f"{self.events_path}:{lineno}: invalid JSON: {exc}"
                    ) from exc
                if not isinstance(data, dict):
                    raise BlackboardError(
                        f"{self.events_path}:{lineno}: event must be a JSON object"
                    )
                yield Event.from_dict(data)

    def read_events(self) -> list[Event]:
        return list(self.iter_events())

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
        self._root.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), sort_keys=True, ensure_ascii=False))
            handle.write("\n")
        self._count = sequence
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
        rebuilt from ``events.jsonl`` (M2). ``replay`` never calls this.
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
        derived from ``events.jsonl``. Raises :class:`BlackboardError` on malformed
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


__all__ = ["RunStore"]
