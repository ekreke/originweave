"""Run storage: the append-only event log and run directory layout.

A run directory looks like::

    <run-dir>/
    ├── events.jsonl        # append-only, one Event per line
    ├── input/              # document A snapshot
    ├── sources/            # source snapshots
    └── report.md           # final artefact             (populated in M2)
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from .blackboard import BlackboardError
from .events import DEFAULT_TONE, Event, format_event_id, now_iso


class RunStore:
    """Read/write access to a single run directory."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

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
    def report_path(self) -> Path:
        return self._root / "report.md"

    def init_layout(self) -> None:
        """Create the run directory and its sub-directories."""
        self._root.mkdir(parents=True, exist_ok=True)
        for directory in (self.input_dir, self.sources_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def event_count(self) -> int:
        if not self.events_path.is_file():
            return 0
        return sum(1 for _ in self.iter_events())

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
        event = Event(
            id=format_event_id(self.event_count() + 1),
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
        return event


__all__ = ["RunStore"]
