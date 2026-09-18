"""Blackboard domain model.

Field names and semantics are frozen in ``docs/overview/blackboard-protocol.md``.
Instances are plain, mutable dataclasses so the reducer can evolve them; every
type knows how to serialise to and from JSON-able dicts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

# Value domains for blackboard fields; frozen in docs/overview/blackboard-protocol.md.
# Static layer only: mypy enforces these where a field is annotated with an alias, while
# runtime validation uses the matching frozensets below. The two are kept in sync by hand.

# Node kind. origin/goal are the two board anchors; the rest are derived findings.
FactKind = Literal[
    "origin", "goal", "fact", "citation", "source", "boundary", "compare", "deviation"
]
# Provenance role: the single core claim, its sub-claims, or none.
FactRole = Literal["main-claim", "sub-claim", "none"]
# Verification state of a fact.
FactStatus = Literal["verified", "open", "flagged", "review"]
# What an Intent asks a worker to do (the three OODA task directives).
IntentType = Literal["decompose", "explore", "verify"]
# Intent lifecycle; claimed/awaiting_human are transient coordination states.
IntentStatus = Literal["open", "claimed", "done", "dropped", "awaiting_human"]
# DAG edge semantics. Structural edges (decomposes/spawns/resolves) are derived by the
# reducer; semantic edges (main-chain/dependency/goal-derived) must be in the payload.
EdgeRelation = Literal[
    "main-chain", "dependency", "goal-derived", "decomposes", "spawns", "resolves"
]
# Whole-run lifecycle.
RunStatus = Literal[
    "queued", "running", "awaiting_human", "paused", "stopped", "completed", "failed"
]
# Author of a Hint or a human decision.
Author = Literal["human", "agent"]

# Runtime validation sets: from_dict() checks values against these via _choice().
# They are the enforced counterpart of the Literal aliases above; keep members in sync.
FACT_KINDS: frozenset[str] = frozenset(  # FactKind
    {"origin", "goal", "fact", "citation", "source", "boundary", "compare", "deviation"}
)
FACT_ROLES: frozenset[str] = frozenset({"main-claim", "sub-claim", "none"})  # FactRole
FACT_STATUSES: frozenset[str] = frozenset({"verified", "open", "flagged", "review"})  # FactStatus
INTENT_TYPES: frozenset[str] = frozenset({"decompose", "explore", "verify"})  # IntentType
INTENT_STATUSES: frozenset[str] = frozenset(  # IntentStatus
    {"open", "claimed", "done", "dropped", "awaiting_human"}
)
EDGE_RELATIONS: frozenset[str] = frozenset(  # EdgeRelation
    {"main-chain", "dependency", "goal-derived", "decomposes", "spawns", "resolves"}
)
RUN_STATUSES: frozenset[str] = frozenset(  # RunStatus
    {"queued", "running", "awaiting_human", "paused", "stopped", "completed", "failed"}
)
AUTHORS: frozenset[str] = frozenset({"human", "agent"})  # Author


class BlackboardError(ValueError):
    """Raised when blackboard data is malformed."""


def _require_str(data: Mapping[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise BlackboardError(f"{where}.{key} must be a string")
    return value


def _opt_str(data: Mapping[str, Any], key: str, where: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BlackboardError(f"{where}.{key} must be a string or null")
    return value


def _str(data: Mapping[str, Any], key: str, default: str = "") -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise BlackboardError(f"{key} must be a string")
    return value


def _float(data: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BlackboardError(f"{key} must be a number")
    return float(value)


def _list(data: Mapping[str, Any], key: str) -> list[Any]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise BlackboardError(f"{key} must be a list")
    return value


def _dict(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise BlackboardError(f"{key} must be a table")
    return value


def _choice(value: str, allowed: frozenset[str], where: str) -> str:
    if value not in allowed:
        raise BlackboardError(f"{where} must be one of {sorted(allowed)}; got {value!r}")
    return value


@dataclass
class Evidence:
    id: str
    quote: str
    sourceTitle: str
    url: str
    locator: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "quote": self.quote,
            "sourceTitle": self.sourceTitle,
            "url": self.url,
            "locator": self.locator,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Evidence:
        return cls(
            id=_require_str(data, "id", "evidence"),
            quote=_str(data, "quote"),
            sourceTitle=_str(data, "sourceTitle"),
            url=_str(data, "url"),
            locator=_str(data, "locator"),
        )


@dataclass
class Fact:
    id: str
    kind: str
    role: str = "none"
    label: str = ""
    subtitle: str = ""
    status: str = "open"
    confidence: float = 0.0
    note: str = ""
    position: dict[str, float] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "role": self.role,
            "label": self.label,
            "subtitle": self.subtitle,
            "status": self.status,
            "confidence": self.confidence,
            "note": self.note,
            "position": dict(self.position),
            "evidence": [e.to_dict() for e in self.evidence],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Fact:
        position_raw = _dict(data, "position")
        position = {
            str(k): float(v)
            for k, v in position_raw.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        evidence = [Evidence.from_dict(e) for e in _list(data, "evidence") if isinstance(e, dict)]
        return cls(
            id=_require_str(data, "id", "fact"),
            kind=_choice(_str(data, "kind"), FACT_KINDS, "fact.kind"),
            role=_choice(_str(data, "role", "none"), FACT_ROLES, "fact.role"),
            label=_str(data, "label"),
            subtitle=_str(data, "subtitle"),
            status=_choice(_str(data, "status", "open"), FACT_STATUSES, "fact.status"),
            confidence=_float(data, "confidence"),
            note=_str(data, "note"),
            position=position,
            evidence=evidence,
        )


@dataclass
class Intent:
    id: str
    type: str
    status: str = "open"
    from_: str = "origin"
    question: str = ""
    producedFacts: list[str] = field(default_factory=list)
    claimedBy: str | None = None
    heartbeatAt: str | None = None
    createdAt: str = ""
    duplicateOf: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "from": self.from_,
            "question": self.question,
            "producedFacts": list(self.producedFacts),
            "claimedBy": self.claimedBy,
            "heartbeatAt": self.heartbeatAt,
            "createdAt": self.createdAt,
            "duplicateOf": self.duplicateOf,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Intent:
        produced = [p for p in _list(data, "producedFacts") if isinstance(p, str)]
        return cls(
            id=_require_str(data, "id", "intent"),
            type=_choice(_str(data, "type"), INTENT_TYPES, "intent.type"),
            status=_choice(_str(data, "status", "open"), INTENT_STATUSES, "intent.status"),
            from_=_str(data, "from", "origin"),
            question=_str(data, "question"),
            producedFacts=produced,
            claimedBy=_opt_str(data, "claimedBy", "intent"),
            heartbeatAt=_opt_str(data, "heartbeatAt", "intent"),
            createdAt=_str(data, "createdAt"),
            duplicateOf=_opt_str(data, "duplicateOf", "intent"),
        )


@dataclass
class Hint:
    id: str
    text: str
    author: str = "human"
    createdAt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "author": self.author,
            "createdAt": self.createdAt,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Hint:
        return cls(
            id=_require_str(data, "id", "hint"),
            text=_str(data, "text"),
            author=_choice(_str(data, "author", "human"), AUTHORS, "hint.author"),
            createdAt=_str(data, "createdAt"),
        )


@dataclass
class Edge:
    id: str
    source: str
    target: str
    relation: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Edge:
        return cls(
            id=_require_str(data, "id", "edge"),
            source=_require_str(data, "source", "edge"),
            target=_require_str(data, "target", "edge"),
            relation=_choice(_str(data, "relation"), EDGE_RELATIONS, "edge.relation"),
            note=_str(data, "note"),
        )


@dataclass
class HumanDecision:
    gate: str
    decision: str
    text: str = ""
    targets: list[str] = field(default_factory=list)
    author: str = "human"
    at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "decision": self.decision,
            "text": self.text,
            "targets": list(self.targets),
            "author": self.author,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> HumanDecision:
        targets = [t for t in _list(data, "targets") if isinstance(t, str)]
        return cls(
            gate=_require_str(data, "gate", "decision"),
            decision=_require_str(data, "decision", "decision"),
            text=_str(data, "text"),
            targets=targets,
            author=_choice(_str(data, "author", "human"), AUTHORS, "decision.author"),
            at=_str(data, "at"),
        )


@dataclass
class WaitingFor:
    gate: str
    question: str

    def to_dict(self) -> dict[str, Any]:
        return {"gate": self.gate, "question": self.question}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WaitingFor:
        return cls(
            gate=_require_str(data, "gate", "waitingFor"),
            question=_str(data, "question"),
        )


@dataclass
class Board:
    origin: Fact
    goal: Fact
    status: str = "queued"
    facts: list[Fact] = field(default_factory=list)
    intents: list[Intent] = field(default_factory=list)
    hints: list[Hint] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    decisions: list[HumanDecision] = field(default_factory=list)
    waitingFor: WaitingFor | None = None
    verdict: str | None = None

    def fact(self, fact_id: str) -> Fact | None:
        for item in self.facts:
            if item.id == fact_id:
                return item
        return None

    def intent(self, intent_id: str) -> Intent | None:
        for item in self.intents:
            if item.id == intent_id:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "origin": self.origin.to_dict(),
            "goal": self.goal.to_dict(),
            "facts": [f.to_dict() for f in self.facts],
            "intents": [i.to_dict() for i in self.intents],
            "hints": [h.to_dict() for h in self.hints],
            "edges": [e.to_dict() for e in self.edges],
            "decisions": [d.to_dict() for d in self.decisions],
            "waitingFor": None if self.waitingFor is None else self.waitingFor.to_dict(),
            "verdict": self.verdict,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Board:
        waiting_raw = data.get("waitingFor")
        waiting = WaitingFor.from_dict(waiting_raw) if isinstance(waiting_raw, dict) else None
        return cls(
            origin=Fact.from_dict(_dict(data, "origin")),
            goal=Fact.from_dict(_dict(data, "goal")),
            status=_choice(_str(data, "status", "queued"), RUN_STATUSES, "board.status"),
            facts=[Fact.from_dict(f) for f in _list(data, "facts") if isinstance(f, dict)],
            intents=[Intent.from_dict(i) for i in _list(data, "intents") if isinstance(i, dict)],
            hints=[Hint.from_dict(h) for h in _list(data, "hints") if isinstance(h, dict)],
            edges=[Edge.from_dict(e) for e in _list(data, "edges") if isinstance(e, dict)],
            decisions=[
                HumanDecision.from_dict(d) for d in _list(data, "decisions") if isinstance(d, dict)
            ],
            waitingFor=waiting,
            verdict=_opt_str(data, "verdict", "board"),
        )


__all__ = [
    "AUTHORS",
    "EDGE_RELATIONS",
    "FACT_KINDS",
    "FACT_ROLES",
    "FACT_STATUSES",
    "INTENT_STATUSES",
    "INTENT_TYPES",
    "RUN_STATUSES",
    "Author",
    "Board",
    "Edge",
    "EdgeRelation",
    "Evidence",
    "Fact",
    "FactKind",
    "FactRole",
    "FactStatus",
    "Hint",
    "HumanDecision",
    "Intent",
    "IntentStatus",
    "IntentType",
    "BlackboardError",
    "RunStatus",
    "WaitingFor",
]
