"""Workspace database: runs/projects metadata for the whole server workspace.

One SQLite file (``[storage].db``) holds the workspace metadata:

- ``runs``   — one row per run: ``id``, denormalised ``project_id`` (indexed for
  per-project listing) and the full static ``run.json`` payload as canonical JSON.
- ``projects`` — the project registry's static fields.

Both tables are *static* data: every derived field (status, counts,
``updated_at``) is still folded from the event log, never stored here.

The same file can also hold a run's event log (the ``events`` table, created by
:class:`~originweave.sqlite_backend.SqliteEventLog`). The live server writes
``events.jsonl``; runs migrated into SQLite (or imported from a bundled
``events.db``) share this file, which is why ``project_run_stats`` can fold the
event timestamps of database-backed runs.

``bootstrap_from_dirs`` imports the legacy directory registry
(``projects/<id>/project.json`` + ``runs/<id>/run.json``) at server startup,
so existing workspaces and scripts that write the directory layout keep
working. Imports are ``INSERT OR IGNORE``: the database is authoritative once
a row exists.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .blackboard import BlackboardError
from .sqlite_backend import EVENT_SCHEMA, check_schema_version

# The full workspace schema: the event log (meta/events, shared with
# SqliteEventLog) plus the runs/projects metadata tables. Creating every table
# on every connect keeps open order irrelevant (e.g. listing projects before
# the first run exists must not fail on a missing ``events`` table).
_SCHEMA = (
    EVENT_SCHEMA
    + """
CREATE TABLE IF NOT EXISTS runs (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    meta       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id);
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    accent      TEXT NOT NULL DEFAULT ''
);
"""
)


def _meta_to_json(meta: Mapping[str, Any]) -> str:
    return json.dumps(dict(meta), sort_keys=True, ensure_ascii=False)


class WorkspaceStore:
    """Metadata tables (runs/projects) for one workspace's global database."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._connect()

    @property
    def path(self) -> Path:
        return self._db_path

    # -- lifecycle ---------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.executescript(_SCHEMA)
            check_schema_version(conn, self._db_path)
            conn.commit()
        except BlackboardError:
            if conn is not None:
                conn.close()
            raise
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                conn.close()
            raise BlackboardError(
                f"{self._db_path}: not a valid workspace database: {exc}"
            ) from exc
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- runs --------------------------------------------------------------

    def upsert_run_meta(self, run_id: str, meta: Mapping[str, Any]) -> None:
        """Insert or replace the static metadata row for ``run_id``."""
        conn = self._connect()
        project_id = meta.get("project_id")
        conn.execute(
            "INSERT INTO runs (id, project_id, meta) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET project_id = excluded.project_id, "
            "meta = excluded.meta",
            (run_id, project_id if isinstance(project_id, str) else "", _meta_to_json(meta)),
        )
        conn.commit()

    def get_run_meta(self, run_id: str) -> dict[str, Any] | None:
        """The stored static metadata for ``run_id``, or ``None``."""
        conn = self._connect()
        row = conn.execute("SELECT meta FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        if not isinstance(data, dict):
            raise BlackboardError(f"workspace: stored run metadata for {run_id!r} is corrupt")
        return data

    def has_run(self, run_id: str) -> bool:
        conn = self._connect()
        return conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is not None

    def run_ids(self) -> set[str]:
        conn = self._connect()
        return {str(row[0]) for row in conn.execute("SELECT id FROM runs")}

    def max_run_seq(self) -> int:
        """The highest ``run_00N`` sequence in the workspace (0 when empty).

        Considers both metadata rows and event rows, so a run whose events were
        imported into the database without a ``runs`` row still reserves its id
        (two runs must never share one event stream).
        """
        conn = self._connect()
        row = conn.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(id, 5) AS INTEGER)), 0) FROM ("
            "  SELECT id FROM runs WHERE id GLOB 'run_[0-9]*'"
            "  UNION"
            "  SELECT DISTINCT run_id AS id FROM events WHERE run_id GLOB 'run_[0-9]*'"
            ")"
        ).fetchone()
        return int(row[0])

    def project_run_stats(self, project_id: str) -> tuple[int, str]:
        """(run_count, latest event ``at``) for one project, from the database.

        ``latest`` is the newest event timestamp across the project's runs ('' when
        there is none). It only reflects events stored *in this database*; callers
        that also need runs whose events live on disk (the live JSONL backend)
        must fold those separately.
        """
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(DISTINCT r.id), COALESCE(MAX(e.at), '') FROM runs r "
            "LEFT JOIN events e ON e.run_id = r.id WHERE r.project_id = ?",
            (project_id,),
        ).fetchone()
        return int(row[0]), str(row[1])

    # -- projects ----------------------------------------------------------

    def upsert_project(
        self, project_id: str, *, name: str, description: str = "", accent: str = ""
    ) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO projects (id, name, description, accent) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, "
            "description = excluded.description, accent = excluded.accent",
            (project_id, name, description, accent),
        )
        conn.commit()

    def get_project(self, project_id: str) -> dict[str, str] | None:
        conn = self._connect()
        row = conn.execute(
            "SELECT id, name, description, accent FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "name": row[1], "description": row[2], "accent": row[3]}

    def list_projects(self) -> list[dict[str, str]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, name, description, accent FROM projects ORDER BY id"
        ).fetchall()
        return [
            {"id": row[0], "name": row[1], "description": row[2], "accent": row[3]} for row in rows
        ]

    # -- legacy directory bootstrap ---------------------------------------

    def bootstrap_from_dirs(self, projects_dir: Path, runs_dir: Path) -> None:
        """Idempotently import the legacy directory registry (``INSERT OR IGNORE``).

        Runs the same schema checks as the directory readers: only valid entries
        are imported, and a corrupt one is skipped rather than failing startup.
        """
        conn = self._connect()
        if projects_dir.is_dir():
            for entry in sorted(projects_dir.iterdir()):
                path = entry / "project.json"
                if not entry.is_dir() or not path.is_file():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if not isinstance(data, dict) or not isinstance(data.get("id"), str):
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO projects (id, name, description, accent) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        data["id"],
                        str(data.get("name") or ""),
                        str(data.get("description") or ""),
                        str(data.get("accent") or ""),
                    ),
                )
        if runs_dir.is_dir():
            for entry in sorted(runs_dir.iterdir()):
                path = entry / "run.json"
                if not entry.is_dir() or not path.is_file():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if not isinstance(data, dict) or not isinstance(data.get("id"), str):
                    continue
                # Key rows by the directory name (the id every reader looks up); a
                # run.json whose id disagrees is malformed and stays directory-only.
                if data["id"] != entry.name:
                    continue
                project_id = data.get("project_id")
                conn.execute(
                    "INSERT OR IGNORE INTO runs (id, project_id, meta) VALUES (?, ?, ?)",
                    (
                        data["id"],
                        project_id if isinstance(project_id, str) else "",
                        _meta_to_json(data),
                    ),
                )
        conn.commit()


__all__ = ["WorkspaceStore"]
