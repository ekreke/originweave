"""SQLite event-log backend (workspace storage).

A SQLite-backed event log that keeps the append-only contract of the JSONL log:
one row per ``Event``, keyed by ``(run_id, seq)``, written through
:meth:`originweave.store.RunStore.append_event` (still the only writer). The live
server still writes ``events.jsonl``; this backend is the migration target and is
used for self-contained sample/exports and for runs whose events were explicitly
imported into the workspace database.

One schema serves two bindings of *where* the database file lives:

- a single global database (all runs of a server workspace), and
- a self-contained per-run database (``<run-dir>/events.db``, used by the
  committed sample so the whole run directory stays portable).

``payload`` is stored as canonical JSON text (``sort_keys`` + ``ensure_ascii=False``),
mirroring the JSONL encoding it replaces, so the reducer consumes identical
:class:`~originweave.events.Event` objects regardless of backend.

Concurrency: the server appends from its single asyncio event loop, so a plain
connection with ``check_same_thread=False`` suffices. The default rollback
journal is kept instead of WAL on purpose: appends are low-frequency (a handful
per engine round) and no sidecar ``-wal``/``-shm`` files must appear next to
committed or read-only database files.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .blackboard import BlackboardError
from .events import Event, format_event_id

SCHEMA_VERSION = 1

# Shared by every opener of the workspace database (SqliteEventLog and
# WorkspaceStore); all statements are idempotent so connect order never matters.
EVENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    run_id  TEXT NOT NULL,
    seq     INTEGER NOT NULL,
    id      TEXT NOT NULL,
    at      TEXT NOT NULL,
    type    TEXT NOT NULL,
    message TEXT NOT NULL,
    tone    TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
"""


def _payload_to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _payload_from_json(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise BlackboardError("stored event payload must be a JSON object")
    return data


def read_schema_version(conn: sqlite3.Connection) -> str | None:
    """The stored ``schema_version`` value, or ``None`` when the table is empty."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return None if row is None else str(row[0])


def check_schema_version(conn: sqlite3.Connection, db_path: Path) -> None:
    """Record the schema version on first use, else reject an unsupported one.

    Shared by every opener of a workspace database (``SqliteEventLog`` and
    ``WorkspaceStore``) so whichever connects first still gates the other: a
    version bump must fail loudly on *both* paths, not silently on the metadata
    side. Assumes the ``meta`` table already exists (the caller ran the schema).
    """
    current = read_schema_version(conn)
    if current is None:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    elif current != str(SCHEMA_VERSION):
        raise BlackboardError(
            f"{db_path}: schema version {current!r} is not supported "
            f"(expected {SCHEMA_VERSION}); rebuild the database"
        )


def sqlite_run_has_events(db_path: Path, run_id: str) -> bool:
    """Cheap, read-only existence probe for one run's events.

    Opens the database in read-only mode and asks for a single row, so a probe
    never runs DDL/schema writes and never leaves a connection behind. A missing
    file, a non-database file, or a database without the ``events`` table all
    read as "no events" rather than raising.
    """
    path = Path(db_path)
    if not path.is_file():
        return False
    conn: sqlite3.Connection | None = None
    try:
        # ``timeout`` makes a transient writer lock wait rather than fail; a failure
        # here (corrupt file, no ``events`` table) reads as "no events" by design.
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)
        row = conn.execute(
            "SELECT 1 FROM events WHERE run_id = ? LIMIT 1", (run_id,)
        ).fetchone()
        return row is not None
    except sqlite3.DatabaseError:
        return False
    finally:
        if conn is not None:
            conn.close()


def _has_events_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'events'"
    ).fetchone()
    return row is not None


class SqliteEventLog:
    """Append-only event log for one run inside one SQLite database file.

    Construction eagerly opens the connection so a missing/corrupt database or an
    unsupported schema fails fast at open time (mirroring the JSONL backend's
    read-time validation). Closing mid-iteration aborts the iteration with
    ``sqlite3.ProgrammingError`` — treat close as an ownership-transfer operation,
    unlike the JSONL backend's no-op.
    """

    def __init__(self, db_path: Path, run_id: str) -> None:
        self._db_path = Path(db_path)
        self._run_id = run_id
        self._conn: sqlite3.Connection | None = None
        self._connect()

    # -- lifecycle ---------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA synchronous = NORMAL")
            # Only run the schema DDL when the table is absent: read-only opens of an
            # already-initialised database (polled read RPCs on a bundled/migrated run)
            # must not take a write lock on every call. The version check still runs
            # and fails loudly on an unsupported schema.
            if not _has_events_table(conn):
                conn.executescript(EVENT_SCHEMA)
            check_schema_version(conn, self._db_path)
            conn.commit()
        except BlackboardError:
            if conn is not None:
                conn.close()
            raise
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                conn.close()
            raise BlackboardError(f"{self._db_path}: not a valid event database: {exc}") from exc
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- EventLog protocol -------------------------------------------------

    def append(self, event: Event) -> None:
        conn = self._connect()
        seq = self.count() + 1
        if event.id != format_event_id(seq):
            raise BlackboardError(
                f"event id {event.id!r} does not match next sequence {seq} for run {self._run_id!r}"
            )
        try:
            conn.execute(
                "INSERT INTO events (run_id, seq, id, at, type, message, tone, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._run_id,
                    seq,
                    event.id,
                    event.at,
                    event.type,
                    event.message,
                    event.tone,
                    _payload_to_json(event.payload),
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            # The count→insert window lost a race to another writer on this run.
            raise BlackboardError(
                f"{self._db_path}: run {self._run_id!r} sequence {seq} already taken: {exc}"
            ) from exc

    def iter_events(self) -> Iterator[Event]:
        conn = self._connect()
        cursor = conn.execute(
            "SELECT id, at, type, message, tone, payload FROM events WHERE run_id = ? ORDER BY seq",
            (self._run_id,),
        )
        for event_id, at, event_type, message, tone, raw_payload in cursor:
            try:
                payload = _payload_from_json(raw_payload)
            except json.JSONDecodeError as exc:
                raise BlackboardError(
                    f"{self._db_path}: run {self._run_id!r} event {event_id}: "
                    f"invalid payload JSON: {exc}"
                ) from exc
            # Route through ``Event.from_dict`` so stored rows get the same
            # type/tone validation as JSONL lines (poisoned rows must fail loudly,
            # not slip through the reducer's unknown-type ignore).
            yield Event.from_dict(
                {
                    "id": event_id,
                    "at": at,
                    "type": event_type,
                    "message": message,
                    "tone": tone,
                    "payload": payload,
                }
            )

    def count(self) -> int:
        conn = self._connect()
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM events WHERE run_id = ?", (self._run_id,)
        ).fetchone()
        return int(row[0])

    def count_type(self, event_type: str) -> int:
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ? AND type = ?",
            (self._run_id, event_type),
        ).fetchone()
        return int(row[0])

    def has_events(self) -> bool:
        return self.count() > 0


__all__ = [
    "EVENT_SCHEMA",
    "SCHEMA_VERSION",
    "SqliteEventLog",
    "check_schema_version",
    "read_schema_version",
    "sqlite_run_has_events",
]
