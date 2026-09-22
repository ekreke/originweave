from __future__ import annotations

import json
from pathlib import Path

import pytest

from originweave.blackboard import BlackboardError
from originweave.persistence import Project, ProjectRegistry, allocate_run_id
from originweave.workspace import WorkspaceStore


@pytest.fixture()
def workspace(tmp_path: Path) -> WorkspaceStore:
    return WorkspaceStore(tmp_path / "originweave.db")


def test_run_meta_roundtrip_and_upsert(workspace: WorkspaceStore) -> None:
    assert workspace.get_run_meta("run_001") is None
    workspace.upsert_run_meta("run_001", {"id": "run_001", "project_id": "p", "title": "First"})
    workspace.upsert_run_meta("run_002", {"id": "run_002", "project_id": "p"})
    assert workspace.has_run("run_001")
    assert not workspace.has_run("run_009")

    # A second upsert replaces the row (CreateRun retries, bootstrap idempotence).
    workspace.upsert_run_meta("run_001", {"id": "run_001", "project_id": "p", "title": "Renamed"})
    meta = workspace.get_run_meta("run_001")
    assert meta is not None and meta["title"] == "Renamed"
    assert meta["project_id"] == "p"

    assert workspace.run_ids() == {"run_001", "run_002"}
    assert workspace.max_run_seq() == 2


def test_project_roundtrip_and_list(workspace: WorkspaceStore) -> None:
    workspace.upsert_project("alpha", name="Alpha", description="d", accent="red")
    workspace.upsert_project("beta", name="Beta")
    assert [p["id"] for p in workspace.list_projects()] == ["alpha", "beta"]
    got = workspace.get_project("alpha")
    assert got == {"id": "alpha", "name": "Alpha", "description": "d", "accent": "red"}
    assert workspace.get_project("gamma") is None


def test_project_run_stats_join_events(tmp_path: Path, workspace: WorkspaceStore) -> None:
    from originweave.events import Event
    from originweave.sqlite_backend import SqliteEventLog

    # Same database file: the events table lives next to the metadata tables.
    log_a = SqliteEventLog(workspace.path, "run_001")
    log_a.append(Event(id="e0001", at="2026-09-21T00:00:00+00:00", type="PROJECT", payload={}))
    log_a.append(Event(id="e0002", at="2026-09-21T00:00:05+00:00", type="REASON", payload={}))
    log_a.close()
    workspace.upsert_run_meta("run_001", {"id": "run_001", "project_id": "p"})
    workspace.upsert_run_meta("run_002", {"id": "run_002", "project_id": "p"})
    workspace.upsert_run_meta("run_003", {"id": "run_003", "project_id": "other"})

    count, latest = workspace.project_run_stats("p")
    assert count == 2
    assert latest == "2026-09-21T00:00:05+00:00"
    assert workspace.project_run_stats("empty") == (0, "")


def test_bootstrap_imports_legacy_directories_idempotently(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    runs = tmp_path / "runs"
    (projects / "alpha").mkdir(parents=True)
    (projects / "alpha" / "project.json").write_text(
        json.dumps({"id": "alpha", "name": "Alpha"}), encoding="utf-8"
    )
    (runs / "run_001").mkdir(parents=True)
    (runs / "run_001" / "run.json").write_text(
        json.dumps({"id": "run_001", "project_id": "alpha", "title": "T"}),
        encoding="utf-8",
    )
    # Stray entries the registry would never create must be ignored.
    (projects / ".tmp").write_text("junk", encoding="utf-8")
    (runs / "not_a_run").mkdir()

    workspace = WorkspaceStore(tmp_path / "originweave.db")
    workspace.bootstrap_from_dirs(projects, runs)
    workspace.bootstrap_from_dirs(projects, runs)  # second pass is a no-op

    assert workspace.has_run("run_001")
    assert workspace.get_run_meta("run_001") == {
        "id": "run_001",
        "project_id": "alpha",
        "title": "T",
    }
    assert workspace.get_project("alpha") is not None
    workspace.close()


def test_bootstrap_skips_corrupt_entries(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    runs = tmp_path / "runs"
    (projects / "bad").mkdir(parents=True)
    (projects / "bad" / "project.json").write_text("not json", encoding="utf-8")
    (runs / "run_bad").mkdir(parents=True)
    (runs / "run_bad" / "run.json").write_text("[]", encoding="utf-8")

    workspace = WorkspaceStore(tmp_path / "originweave.db")
    workspace.bootstrap_from_dirs(projects, runs)
    assert workspace.list_projects() == []
    assert workspace.run_ids() == set()
    workspace.close()


def test_registry_writes_to_both_stores(tmp_path: Path, workspace: WorkspaceStore) -> None:
    registry = ProjectRegistry(tmp_path / "projects", tmp_path / "runs", workspace=workspace)
    registry.write(Project(id="alpha", name="Alpha"))
    assert (tmp_path / "projects" / "alpha" / "project.json").is_file()
    assert workspace.get_project("alpha") is not None


def test_registry_prefers_database_but_falls_back_to_directories(
    tmp_path: Path, workspace: WorkspaceStore
) -> None:
    # Directory-only project (no workspace row).
    dir_only = tmp_path / "projects" / "legacy"
    dir_only.mkdir(parents=True)
    (dir_only / "project.json").write_text(
        json.dumps({"id": "legacy", "name": "Legacy"}), encoding="utf-8"
    )
    # Database-only project (no directory entry).
    workspace.upsert_project("modern", name="Modern")

    registry = ProjectRegistry(tmp_path / "projects", tmp_path / "runs", workspace=workspace)
    assert [p.id for p in registry.list()] == ["legacy", "modern"]
    assert registry.get("modern") is not None
    assert registry.get("legacy") is not None


def test_registry_usage_merges_database_and_directory_runs(
    tmp_path: Path, workspace: WorkspaceStore
) -> None:
    from originweave.events import Event
    from originweave.sqlite_backend import SqliteEventLog

    # A server-created run: metadata + events in the workspace database.
    log = SqliteEventLog(workspace.path, "run_001")
    log.append(Event(id="e0001", at="2026-09-21T01:00:00+00:00", type="PROJECT", payload={}))
    log.close()
    workspace.upsert_run_meta("run_001", {"id": "run_001", "project_id": "alpha"})
    # A legacy run: run.json + events.jsonl on disk only.
    legacy = tmp_path / "runs" / "run_002"
    legacy.mkdir(parents=True)
    (legacy / "run.json").write_text(
        json.dumps({"id": "run_002", "project_id": "alpha"}), encoding="utf-8"
    )
    with (legacy / "events.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "id": "e0001",
                    "at": "2026-09-21T02:00:00+00:00",
                    "type": "PROJECT",
                    "payload": {},
                    "message": "",
                    "tone": "info",
                }
            )
            + "\n"
        )

    registry = ProjectRegistry(tmp_path / "projects", tmp_path / "runs", workspace=workspace)
    workspace.upsert_project("alpha", name="Alpha")
    project = registry.get("alpha")
    assert project is not None
    assert project.run_count == 2
    assert project.updated_at == "2026-09-21T02:00:00+00:00"


def test_allocate_run_id_considers_both_stores(tmp_path: Path, workspace: WorkspaceStore) -> None:
    runs_dir = tmp_path / "runs"
    (runs_dir / "run_005").mkdir(parents=True)
    workspace.upsert_run_meta("run_009", {"id": "run_009"})
    assert allocate_run_id(runs_dir) == "run_006"
    assert allocate_run_id(runs_dir, workspace) == "run_010"


def test_max_run_seq_considers_event_only_runs(tmp_path: Path, workspace: WorkspaceStore) -> None:
    """An id must stay reserved even when only its events (no metadata row) are stored."""
    from originweave.events import Event
    from originweave.sqlite_backend import SqliteEventLog

    log = SqliteEventLog(workspace.path, "run_007")
    log.append(Event(id="e0001", at="t", type="PROJECT", payload={}))
    log.close()

    assert workspace.run_ids() == set()  # no metadata row
    assert workspace.max_run_seq() == 7
    assert allocate_run_id(tmp_path / "runs", workspace) == "run_008"


def test_registry_survives_a_run_with_an_unsupported_bundled_schema(
    tmp_path: Path, workspace: WorkspaceStore
) -> None:
    """A single unreadable ``events.db`` must not break ``get()``/``list()``."""
    import sqlite3

    from originweave.events import Event
    from originweave.sqlite_backend import SqliteEventLog

    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run_001"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"id": "run_001", "project_id": "alpha"}), encoding="utf-8"
    )
    bundled = SqliteEventLog(run_dir / "events.db", "run_001")
    bundled.append(Event(id="e0001", at="t", type="PROJECT", payload={}))
    bundled.close()
    conn = sqlite3.connect(run_dir / "events.db")
    conn.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    workspace.upsert_project("alpha", name="Alpha")

    registry = ProjectRegistry(tmp_path / "projects", runs_dir, workspace=workspace)
    project = registry.get("alpha")
    assert project is not None
    assert [p.id for p in registry.list()] == ["alpha"]


def test_registry_usage_folds_bootstrapped_run_with_jsonl_events(
    tmp_path: Path, workspace: WorkspaceStore
) -> None:
    """A bootstrapped run has a database metadata row but its events stay on disk.

    The registry must count it once and derive ``updated_at`` from the JSONL log,
    not report an empty timestamp just because a database row exists.
    """
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / "run_001"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"id": "run_001", "project_id": "alpha"}), encoding="utf-8"
    )
    with (run_dir / "events.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "id": "e0001",
                    "at": "2026-09-21T03:00:00+00:00",
                    "type": "PROJECT",
                    "payload": {},
                    "message": "",
                    "tone": "info",
                }
            )
            + "\n"
        )
    projects_dir = tmp_path / "projects"
    workspace.bootstrap_from_dirs(projects_dir, runs_dir)
    workspace.upsert_project("alpha", name="Alpha")

    registry = ProjectRegistry(projects_dir, runs_dir, workspace=workspace)
    project = registry.get("alpha")
    assert project is not None
    assert project.run_count == 1
    assert project.updated_at == "2026-09-21T03:00:00+00:00"


def test_rejects_non_database_file(tmp_path: Path) -> None:
    junk = tmp_path / "originweave.db"
    junk.write_text("junk", encoding="utf-8")
    with pytest.raises(BlackboardError, match="not a valid workspace database"):
        WorkspaceStore(junk)
