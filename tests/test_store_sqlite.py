from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from originweave.blackboard import BlackboardError
from originweave.events import Event
from originweave.sqlite_backend import SCHEMA_VERSION, SqliteEventLog
from originweave.store import RunStore, open_run_store, run_has_events
from originweave.workspace import WorkspaceStore


def make_store(root: Path, run_id: str = "run_001") -> RunStore:
    """A SQLite-backed store whose database lives outside the run directory."""
    return RunStore(root, log=SqliteEventLog(root.parent / "workspace.db", run_id))


def test_roundtrip_preserves_content(tmp_path: Path) -> None:
    store = make_store(tmp_path / "run_001")
    first = store.append_event("PROJECT", {"originId": "origin"}, at="2026-09-16T00:00:00+00:00")
    second = store.append_event(
        "COMPLETE", {"verdict": "部分偏差", "nested": {"a": [1, 2]}}, at="t2"
    )
    assert first.id == "e0001"
    assert second.id == "e0002"

    events = store.read_events()
    assert [e.id for e in events] == ["e0001", "e0002"]
    assert events[0].type == "PROJECT"
    assert events[1].payload["verdict"] == "部分偏差"
    assert events[1].payload["nested"] == {"a": [1, 2]}
    assert events[1].tone == "success"
    assert store.event_count() == 2


def test_runs_are_isolated_within_one_database(tmp_path: Path) -> None:
    first = RunStore(tmp_path / "run_001", log=SqliteEventLog(tmp_path / "global.db", "run_001"))
    second = RunStore(tmp_path / "run_002", log=SqliteEventLog(tmp_path / "global.db", "run_002"))
    first.append_event("PROJECT", {}, at="t1")
    second.append_event("PROJECT", {}, at="t2")
    second.append_event("REASON", {}, at="t3")

    assert first.event_count() == 1
    assert second.event_count() == 2
    assert [e.id for e in first.read_events()] == ["e0001"]
    assert [e.id for e in second.read_events()] == ["e0001", "e0002"]


def test_count_type_scopes_to_run_and_type(tmp_path: Path) -> None:
    store = make_store(tmp_path / "run_001")
    other = RunStore(tmp_path / "run_002", log=SqliteEventLog(tmp_path / "workspace.db", "run_002"))
    store.append_event("HINT", {}, at="t1")
    store.append_event("REASON", {}, at="t2")
    other.append_event("HINT", {}, at="t3")
    assert store.next_hint_id() == "h2"
    assert other.next_hint_id() == "h2"


def test_next_hint_id_matches_jsonl_backend(tmp_path: Path) -> None:
    jsonl = RunStore(tmp_path / "jsonl")
    sqlite = make_store(tmp_path / "sqlite")
    for store in (jsonl, sqlite):
        store.append_event("REASON", {}, at="t1")
        store.append_event("HINT", {}, at="t2")
        assert store.next_hint_id() == "h2"
        store.append_event("HINT", {}, at="t3")
        assert store.next_hint_id() == "h3"


def test_reopen_preserves_events_and_continues_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "global.db"
    store = RunStore(tmp_path / "run_001", log=SqliteEventLog(db_path, "run_001"))
    store.append_event("PROJECT", {}, at="t1")
    store.close()

    reopened = RunStore(tmp_path / "run_001", log=SqliteEventLog(db_path, "run_001"))
    assert reopened.event_count() == 1
    event = reopened.append_event("REASON", {}, at="t2")
    assert event.id == "e0002"
    assert [e.id for e in reopened.read_events()] == ["e0001", "e0002"]
    reopened.close()


def test_close_is_idempotent_and_reconnects_on_use(tmp_path: Path) -> None:
    log = SqliteEventLog(tmp_path / "global.db", "run_001")
    log.append(Event(id="e0001", at="t1", type="PROJECT", payload={}))
    log.close()
    log.close()  # second close is a no-op

    # Post-close operations transparently reconnect and see prior data.
    assert log.count() == 1
    log.append(Event(id="e0002", at="t2", type="REASON", payload={}))
    assert log.count() == 2
    log.close()


def test_event_id_format_holds_beyond_four_digits(tmp_path: Path) -> None:
    db_path = tmp_path / "global.db"
    log = SqliteEventLog(db_path, "run_001")
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO events (run_id, seq, id, at, type, message, tone, payload) "
        "VALUES ('run_001', ?, ?, 't', 'REASON', '', 'info', '{}')",
        [(seq, f"e{seq:04d}") for seq in range(1, 10_000)],
    )
    conn.commit()
    conn.close()

    log.append(Event(id="e10000", at="t", type="REASON", payload={}))
    assert log.count() == 10_000
    assert list(log.iter_events())[-1].id == "e10000"
    log.close()


def test_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    db_path = tmp_path / "global.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('schema_version', '999')")
    conn.commit()
    conn.close()

    with pytest.raises(BlackboardError, match="schema version"):
        SqliteEventLog(db_path, "run_001")


def test_rejects_non_database_file(tmp_path: Path) -> None:
    junk = tmp_path / "global.db"
    junk.write_text("definitely not sqlite", encoding="utf-8")
    with pytest.raises(BlackboardError, match="not a valid event database"):
        SqliteEventLog(junk, "run_001")


def test_rejects_event_id_sequence_mismatch(tmp_path: Path) -> None:
    log = SqliteEventLog(tmp_path / "global.db", "run_001")
    log.append(Event(id="e0001", at="t1", type="PROJECT", payload={}))
    with pytest.raises(BlackboardError, match="does not match next sequence"):
        log.append(Event(id="e0009", at="t2", type="REASON", payload={}))
    log.close()


def test_corrupt_payload_raises_blackboard_error(tmp_path: Path) -> None:
    db_path = tmp_path / "global.db"
    log = SqliteEventLog(db_path, "run_001")
    log.append(Event(id="e0001", at="t1", type="PROJECT", payload={}))
    log.close()

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE events SET payload = 'not json'")
    conn.commit()
    conn.close()

    reopened = SqliteEventLog(db_path, "run_001")
    with pytest.raises(BlackboardError, match="invalid payload JSON"):
        list(reopened.iter_events())


def test_corrupt_type_or_tone_raises_like_jsonl(tmp_path: Path) -> None:
    db_path = tmp_path / "global.db"
    log = SqliteEventLog(db_path, "run_001")
    log.append(Event(id="e0001", at="t1", type="PROJECT", payload={}))
    log.close()

    for column, value in (("type", "BOGUS"), ("tone", "nope")):
        conn = sqlite3.connect(db_path)
        conn.execute(f"UPDATE events SET {column} = '{value}'")
        conn.commit()
        conn.close()
        with pytest.raises(BlackboardError):
            list(SqliteEventLog(db_path, "run_001").iter_events())


def test_jsonl_and_sqlite_backends_are_equivalent(tmp_path: Path) -> None:
    operations: list[tuple[str, dict[str, object], str]] = [
        ("PROJECT", {"originId": "o"}, "t1"),
        ("HINT", {"hint": {"id": "h1"}}, "t2"),
        ("INTENT", {"intent": {"id": "i1", "task": "decompose"}}, "t3"),
        ("COMPLETE", {"verdict": "基本一致"}, "t4"),
    ]
    jsonl = RunStore(tmp_path / "jsonl")
    sqlite = make_store(tmp_path / "sqlite")
    for store in (jsonl, sqlite):
        for event_type, payload, at in operations:
            store.append_event(event_type, payload, at=at)

    assert jsonl.read_events() == sqlite.read_events()
    assert jsonl.event_count() == sqlite.event_count()
    assert jsonl.next_hint_id() == sqlite.next_hint_id()


def test_open_run_store_prefers_bundled_db(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_001"
    bundled = SqliteEventLog(run_dir / "events.db", "run_001")
    bundled.append(Event(id="e0001", at="t1", type="PROJECT", payload={}))
    bundled.close()
    global_db = tmp_path / "workspace.db"
    global_log = SqliteEventLog(global_db, "run_001")
    global_log.append(Event(id="e0001", at="t2", type="REASON", payload={}))
    global_log.close()

    store = open_run_store(run_dir, db_path=global_db)
    assert [e.type for e in store.read_events()] == ["PROJECT"]


def test_open_run_store_uses_global_db_when_no_bundled(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_001"
    run_dir.mkdir()
    global_db = tmp_path / "workspace.db"
    log = SqliteEventLog(global_db, "run_001")
    log.append(Event(id="e0001", at="t1", type="PROJECT", payload={}))
    log.close()

    store = open_run_store(run_dir, db_path=global_db)
    assert [e.type for e in store.read_events()] == ["PROJECT"]


def test_open_run_store_falls_back_to_jsonl_without_db(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_001"
    store = open_run_store(run_dir)
    store.append_event("PROJECT", {}, at="t1")
    assert store.events_path.is_file()
    assert open_run_store(run_dir).event_count() == 1


def test_open_run_store_falls_back_to_jsonl_on_missing_db_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_001"
    store = open_run_store(run_dir, db_path=tmp_path / "absent.db")
    store.append_event("PROJECT", {}, at="t1")
    # The explicit path does not exist, so the legacy backend was used.
    assert store.events_path.is_file()


def test_schema_version_is_recorded(tmp_path: Path) -> None:
    db_path = tmp_path / "global.db"
    SqliteEventLog(db_path, "run_001").close()
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    conn.close()
    assert row == (str(SCHEMA_VERSION),)


def test_workspace_metadata_does_not_shadow_legacy_jsonl(tmp_path: Path) -> None:
    """A workspace metadata row is not an event store.

    The live server keeps writing ``events.jsonl`` while recording the run in the
    database; opening that run must still read the JSONL log, not silently bind an
    empty database table.
    """
    run_dir = tmp_path / "run_001"
    RunStore(run_dir).append_event("PROJECT", {}, at="t1")
    workspace = WorkspaceStore(tmp_path / "workspace.db")
    workspace.upsert_run_meta("run_001", {"id": "run_001", "project_id": "p"})

    reopened = open_run_store(run_dir, db_path=workspace.path)
    assert [event.type for event in reopened.read_events()] == ["PROJECT"]
    assert run_has_events(run_dir, db_path=workspace.path)


def test_run_has_events_probe_is_read_only(tmp_path: Path) -> None:
    # No log anywhere: the probe reports absence without creating a database.
    run_dir = tmp_path / "run_001"
    run_dir.mkdir()
    db_path = tmp_path / "absent.db"
    assert not run_has_events(run_dir, db_path=db_path)
    assert not db_path.exists()
