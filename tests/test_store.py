from __future__ import annotations

from pathlib import Path

import pytest

from originweave.blackboard import BlackboardError
from originweave.store import RunStore


def test_init_layout_creates_directories(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    store.init_layout()
    assert store.input_dir.is_dir()
    assert store.sources_dir.is_dir()
    assert store.capabilities_dir.is_dir()
    assert store.root.is_dir()


def test_append_assigns_monotonic_ids_and_reads_back(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    first = store.append_event("PROJECT", {"originId": "origin"}, at="2026-09-16T00:00:00+00:00")
    second = store.append_event("REASON", {"phase": "start"}, at="2026-09-16T00:00:01+00:00")
    assert first.id == "e0001"
    assert second.id == "e0002"

    events = store.read_events()
    assert [e.id for e in events] == ["e0001", "e0002"]
    assert events[0].type == "PROJECT"
    assert store.event_count() == 2
    assert store.events_path.read_text(encoding="utf-8").count("\n") == 2


def test_read_events_preserves_order_and_content(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    store.append_event("HINT", {"hint": {"id": "h1", "text": "look here"}}, at="t1")
    store.append_event("COMPLETE", {"verdict": "部分偏差"}, at="t2")
    events = store.read_events()
    assert events[0].payload["hint"]["text"] == "look here"
    assert events[1].payload["verdict"] == "部分偏差"


def test_read_events_skips_blank_lines(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    store.init_layout()
    store.events_path.write_text(
        '{"id":"e0001","at":"t","type":"REASON","payload":{}}\n\n',
        encoding="utf-8",
    )
    assert len(store.read_events()) == 1


def test_read_events_rejects_malformed_line(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    store.init_layout()
    store.events_path.write_text("not json\n", encoding="utf-8")
    with pytest.raises(BlackboardError):
        store.read_events()


def test_event_count_is_zero_without_log(tmp_path: Path) -> None:
    assert RunStore(tmp_path / "absent").event_count() == 0
