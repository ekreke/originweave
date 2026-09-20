from __future__ import annotations

import pytest

from originweave.blackboard import BlackboardError
from originweave.events import (
    DEFAULT_TONE,
    EVENT_TYPES,
    Event,
    format_event_id,
    now_iso,
)


def test_event_roundtrip() -> None:
    event = Event(
        id="e0001",
        at="2026-09-16T00:00:00+00:00",
        type="INTENT",
        payload={"intentId": "i001"},
        message="intent added",
        tone="info",
    )
    assert Event.from_dict(event.to_dict()) == event


def test_event_from_dict_defaults_message_and_tone() -> None:
    event = Event.from_dict(
        {"id": "e0002", "at": "t", "type": "COMPLETE", "payload": {"verdict": "ok"}}
    )
    assert event.message == ""
    assert event.tone == DEFAULT_TONE["COMPLETE"]


def test_event_rejects_unknown_type() -> None:
    with pytest.raises(BlackboardError):
        Event.from_dict({"id": "e1", "at": "t", "type": "NOPE", "payload": {}})


def test_event_rejects_bad_tone() -> None:
    with pytest.raises(BlackboardError):
        Event.from_dict({"id": "e1", "at": "t", "type": "PROJECT", "tone": "loud", "payload": {}})


def test_event_rejects_non_table_payload() -> None:
    with pytest.raises(BlackboardError):
        Event.from_dict({"id": "e1", "at": "t", "type": "PROJECT", "payload": 3})


def test_every_event_type_has_a_default_tone() -> None:
    assert set(DEFAULT_TONE) == set(EVENT_TYPES)


def test_validate_event_is_known() -> None:
    assert DEFAULT_TONE["VALIDATE"] == "info"


def test_terminal_events_are_known() -> None:
    assert DEFAULT_TONE["FAILED"] == "danger"
    assert DEFAULT_TONE["STOPPED"] == "warning"
    failed = Event.from_dict({"id": "e1", "at": "t", "type": "FAILED", "payload": {"reason": "x"}})
    stopped = Event.from_dict(
        {"id": "e2", "at": "t", "type": "STOPPED", "payload": {"reason": "x"}}
    )
    assert failed.tone == "danger"
    assert stopped.tone == "warning"


def test_format_event_id_is_zero_padded() -> None:
    assert format_event_id(1) == "e0001"
    assert format_event_id(42) == "e0042"


def test_entity_and_relation_events_are_known() -> None:
    assert "ENTITY" in EVENT_TYPES
    assert "RELATION" in EVENT_TYPES
    assert DEFAULT_TONE["ENTITY"] == "info"
    assert DEFAULT_TONE["RELATION"] == "info"
    entity = Event.from_dict(
        {"id": "e1", "at": "t", "type": "ENTITY", "payload": {"entity": {"id": "n1"}}}
    )
    relation = Event.from_dict(
        {"id": "e2", "at": "t", "type": "RELATION", "payload": {"relation": {"id": "r1"}}}
    )
    assert entity.tone == "info"
    assert relation.type == "RELATION"


def test_now_iso_is_parseable() -> None:
    from datetime import datetime

    assert datetime.fromisoformat(now_iso())
