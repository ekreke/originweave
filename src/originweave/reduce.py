"""Reduce an append-only event log back into blackboard state.

``reduce`` is a pure fold: the same events always produce the same :class:`Board`.
Structural edges (``spawns``/``resolves``/``decomposes``) are derived from Intent
fields; semantic edges (``main-chain``/``dependency``/``goal-derived``) must be
carried explicitly in event payloads. See ``docs/overview/blackboard-protocol.md``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from .blackboard import (
    Board,
    Edge,
    Entity,
    Fact,
    Hint,
    HumanDecision,
    Intent,
    Relation,
    WaitingFor,
)
from .events import Event

STRUCTURAL_RELATIONS = ("spawns", "resolves", "decomposes")


class ReduceError(ValueError):
    """Raised when an event log cannot be reduced into a well-formed board."""


def _upsert_entity(entities: list[Entity], entity: Entity) -> None:
    """Insert an entity, or replace the same-id one in place (M5 merge/alias upsert).

    The engine re-emits an existing entity with accumulated ``aliases``; replacing in
    place keeps first-seen order, so replay stays deterministic.
    """
    for index, existing in enumerate(entities):
        if existing.id == entity.id:
            entities[index] = entity
            return
    entities.append(entity)


def _object(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ReduceError(f"event payload {key!r} must be a table")
    return value


def _string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ReduceError(f"event payload {key!r} must be a string")
    return value


def _require_string(payload: Mapping[str, Any], key: str) -> None:
    """Validate that ``payload[key]`` is a string; raise :class:`ReduceError` otherwise."""
    _string(payload, key)


def _edges(payload: Mapping[str, Any]) -> list[Edge]:
    raw = payload.get("edges", [])
    if not isinstance(raw, list):
        raise ReduceError("event payload 'edges' must be a list")
    result: list[Edge] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ReduceError("each edge must be a table")
        result.append(Edge.from_dict(item))
    return result


def _require_intent(intents: list[Intent], intent_id: str) -> Intent:
    for intent in intents:
        if intent.id == intent_id:
            return intent
    raise ReduceError(f"event references unknown intent {intent_id!r}")


def reduce(events: Iterable[Event]) -> Board:
    """Fold ``events`` into a :class:`Board`; requires a leading ``PROJECT``."""
    origin: Fact | None = None
    goal: Fact | None = None
    status = "queued"
    facts: list[Fact] = []
    intents: list[Intent] = []
    hints: list[Hint] = []
    edges: list[Edge] = []
    entities: list[Entity] = []
    relations: list[Relation] = []
    decisions: list[HumanDecision] = []
    waiting: WaitingFor | None = None
    verdict: str | None = None

    for event in events:
        payload = event.payload
        if event.type == "PROJECT":
            origin = Fact.from_dict(_object(payload, "origin"))
            goal = Fact.from_dict(_object(payload, "goal"))
            status = "running"
        elif event.type == "INTENT":
            intent = Intent.from_dict(_object(payload, "intent"))
            intents.append(intent)
            edges.append(
                Edge(
                    id=f"{intent.from_}->{intent.id}",
                    source=intent.from_,
                    target=intent.id,
                    relation="spawns",
                )
            )
            edges.extend(_edges(payload))
        elif event.type == "EXECUTE":
            intent = _require_intent(intents, _string(payload, "intentId"))
            intent.status = "claimed"
            intent.claimedBy = str(payload.get("worker", ""))
            intent.heartbeatAt = event.at
        elif event.type == "HEARTBEAT":
            intent = _require_intent(intents, _string(payload, "intentId"))
            intent.heartbeatAt = event.at
        elif event.type == "RELEASE":
            intent = _require_intent(intents, _string(payload, "intentId"))
            intent.status = "open"
            intent.claimedBy = None
        elif event.type == "CONCLUDE":
            intent_id = _string(payload, "intentId")
            intent = _require_intent(intents, intent_id)
            raw_facts = payload.get("facts", [])
            if not isinstance(raw_facts, list):
                raise ReduceError("event payload 'facts' must be a list")
            produced: list[Fact] = []
            for item in raw_facts:
                if not isinstance(item, dict):
                    raise ReduceError("each produced fact must be a table")
                produced.append(Fact.from_dict(item))
            facts.extend(produced)
            intent.status = "done"
            intent.producedFacts = [f.id for f in produced]
            for produced_fact in produced:
                edges.append(
                    Edge(
                        id=f"{intent_id}->{produced_fact.id}",
                        source=intent_id,
                        target=produced_fact.id,
                        relation="resolves",
                    )
                )
                if intent.type == "decompose":
                    edges.append(
                        Edge(
                            id=f"{intent.from_}->{produced_fact.id}",
                            source=intent.from_,
                            target=produced_fact.id,
                            relation="decomposes",
                        )
                    )
            edges.extend(_edges(payload))
        elif event.type == "HINT":
            hints.append(Hint.from_dict(_object(payload, "hint")))
        elif event.type == "ENTITY":
            _upsert_entity(entities, Entity.from_dict(_object(payload, "entity")))
        elif event.type == "RELATION":
            # Write-once: the engine assigns a fresh id per judged relation, so a plain
            # append is deterministic (unlike ENTITY, which is re-emitted to add aliases).
            relations.append(Relation.from_dict(_object(payload, "relation")))
        elif event.type == "REQUEST_HUMAN":
            status = "awaiting_human"
            waiting = WaitingFor(
                gate=_string(payload, "gate"),
                question=str(payload.get("question", "")),
            )
        elif event.type == "HUMAN_INPUT":
            decisions.append(
                HumanDecision.from_dict(
                    {
                        "gate": payload.get("gate", ""),
                        "decision": payload.get("decision", ""),
                        "text": payload.get("text", ""),
                        "targets": payload.get("targets", []),
                        "author": payload.get("author", "human"),
                        "at": event.at,
                    }
                )
            )
            status = "running"
            waiting = None
        elif event.type == "COMPLETE":
            verdict = str(payload.get("verdict", "")) or None
            status = "completed"
            waiting = None
        elif event.type == "FAILED":
            _require_string(payload, "reason")  # a malformed terminal event should fail loudly
            status = "failed"
            waiting = None
        elif event.type == "STOPPED":
            _require_string(payload, "reason")
            status = "stopped"
            waiting = None
        elif event.type == "PAUSED":
            # Recoverable pause (M3b): RESUMED brings the run back to running.
            status = "paused"
            waiting = None
        elif event.type == "RESUMED":
            status = "running"
            waiting = None
        # REASON carries no derivable state in M0c.

    if origin is None or goal is None:
        raise ReduceError("run has no PROJECT event")

    return Board(
        origin=origin,
        goal=goal,
        status=status,
        facts=facts,
        intents=intents,
        hints=hints,
        edges=edges,
        entities=entities,
        relations=relations,
        decisions=decisions,
        waitingFor=waiting,
        verdict=verdict,
    )


def render_canonical(board: Board) -> str:
    """Return a deterministic JSON rendering of ``board`` (stable across replays)."""
    return json.dumps(board.to_dict(), sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def render_summary(board: Board) -> str:
    """Return a short human-readable summary of ``board``."""
    counts = {"open": 0, "claimed": 0, "done": 0, "dropped": 0, "awaiting_human": 0}
    for intent in board.intents:
        counts[intent.status] = counts.get(intent.status, 0) + 1
    lines = [
        f"status: {board.status}",
        f"origin: {board.origin.label or board.origin.id} ({board.origin.id})",
        f"goal: {board.goal.label or board.goal.id} ({board.goal.id})",
        f"facts: {len(board.facts)}  intents: {len(board.intents)} "
        f"(open {counts['open']}, claimed {counts['claimed']}, done {counts['done']}, "
        f"dropped {counts['dropped']})  hints: {len(board.hints)}  edges: {len(board.edges)}",
    ]
    if board.waitingFor is not None:
        lines.append(f"waitingFor: {board.waitingFor.gate} - {board.waitingFor.question}")
    if board.verdict is not None:
        lines.append(f"verdict: {board.verdict}")
    return "\n".join(lines) + "\n"


__all__ = ["ReduceError", "reduce", "render_canonical", "render_summary"]
