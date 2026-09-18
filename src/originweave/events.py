"""Blackboard event protocol.

``type`` + ``payload`` are the only fields the reducer consumes; ``message`` and
``tone`` exist purely for display. See ``docs/overview/blackboard-protocol.md`` §5.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .blackboard import BlackboardError

EVENT_TYPES: tuple[str, ...] = (
    "PROJECT",
    "INTENT",
    "EXECUTE",
    "CONCLUDE",
    "REASON",
    "COMPLETE",
    "HEARTBEAT",
    "RELEASE",
    "HINT",
    "REQUEST_HUMAN",
    "HUMAN_INPUT",
    "FAILED",
    "STOPPED",
)
EVENT_TYPE_SET: frozenset[str] = frozenset(EVENT_TYPES)

TONES: frozenset[str] = frozenset({"info", "success", "warning", "danger"})

DEFAULT_TONE: dict[str, str] = {
    "PROJECT": "info",
    "INTENT": "info",
    "EXECUTE": "info",
    "CONCLUDE": "success",
    "REASON": "info",
    "COMPLETE": "success",
    "HEARTBEAT": "info",
    "RELEASE": "warning",
    "HINT": "info",
    "REQUEST_HUMAN": "warning",
    "HUMAN_INPUT": "success",
    "FAILED": "danger",
    "STOPPED": "warning",
}


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def format_event_id(sequence: int) -> str:
    """Return the canonical event id for a 1-based ``sequence``."""
    return f"e{sequence:04d}"


@dataclass
class Event:
    id: str
    at: str
    type: str
    payload: dict[str, Any]
    message: str = ""
    tone: str = "info"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "at": self.at,
            "type": self.type,
            "message": self.message,
            "tone": self.tone,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Event:
        event_id = data.get("id")
        if not isinstance(event_id, str):
            raise BlackboardError("event.id must be a string")
        at = data.get("at")
        if not isinstance(at, str):
            raise BlackboardError("event.at must be a string")
        event_type = data.get("type")
        if not isinstance(event_type, str) or event_type not in EVENT_TYPE_SET:
            raise BlackboardError(
                f"event.type must be one of {sorted(EVENT_TYPE_SET)}; got {event_type!r}"
            )
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            raise BlackboardError("event.payload must be a table")
        tone = data.get("tone", DEFAULT_TONE[event_type])
        if not isinstance(tone, str) or tone not in TONES:
            raise BlackboardError(f"event.tone must be one of {sorted(TONES)}; got {tone!r}")
        message = data.get("message", "")
        if not isinstance(message, str):
            raise BlackboardError("event.message must be a string")
        return cls(id=event_id, at=at, type=event_type, payload=payload, message=message, tone=tone)


__all__ = [
    "DEFAULT_TONE",
    "EVENT_TYPES",
    "EVENT_TYPE_SET",
    "TONES",
    "Event",
    "format_event_id",
    "now_iso",
]
