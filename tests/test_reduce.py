from __future__ import annotations

import pytest

from originweave.events import Event
from originweave.reduce import ReduceError, reduce, render_canonical

ORIGIN = {"id": "origin", "kind": "origin", "label": "资料 A"}
GOAL = {"id": "goal", "kind": "goal", "label": "停止条件"}


def ev(seq: int, event_type: str, payload: dict[str, object]) -> Event:
    return Event(id=f"e{seq:04d}", at=f"t{seq}", type=event_type, payload=dict(payload))


def project() -> Event:
    return ev(1, "PROJECT", {"origin": ORIGIN, "goal": GOAL})


def test_project_initialises_board() -> None:
    board = reduce([project()])
    assert board.status == "running"
    assert board.origin.id == "origin"
    assert board.goal.kind == "goal"
    assert board.facts == []
    assert board.edges == []


def test_intent_derives_spawns_edge() -> None:
    board = reduce(
        [
            project(),
            ev(2, "INTENT", {"intent": {"id": "i001", "type": "explore", "from": "origin"}}),
        ]
    )
    assert board.intents[0].id == "i001"
    assert board.edges[0].source == "origin"
    assert board.edges[0].target == "i001"
    assert board.edges[0].relation == "spawns"


def test_intent_duplicate_of_roundtrips() -> None:
    board = reduce(
        [
            project(),
            ev(2, "INTENT", {"intent": {"id": "i001", "type": "explore"}}),
            ev(
                3,
                "INTENT",
                {
                    "intent": {
                        "id": "i002",
                        "type": "explore",
                        "status": "dropped",
                        "duplicateOf": "i001",
                    }
                },
            ),
        ]
    )
    assert board.intents[1].status == "dropped"
    assert board.intents[1].duplicateOf == "i001"


def test_execute_heartbeat_release_transitions() -> None:
    base = [project(), ev(2, "INTENT", {"intent": {"id": "i001", "type": "explore"}})]
    claimed = reduce([*base, ev(3, "EXECUTE", {"intentId": "i001", "worker": "w1"})])
    assert claimed.intents[0].status == "claimed"
    assert claimed.intents[0].claimedBy == "w1"
    assert claimed.intents[0].heartbeatAt == "t3"

    beaten = reduce([*base, ev(3, "HEARTBEAT", {"intentId": "i001"})])
    assert beaten.intents[0].heartbeatAt == "t3"

    released = reduce(
        [
            *base,
            ev(3, "EXECUTE", {"intentId": "i001", "worker": "w1"}),
            ev(4, "RELEASE", {"intentId": "i001"}),
        ]
    )
    assert released.intents[0].status == "open"
    assert released.intents[0].claimedBy is None


def test_conclude_derives_resolves_edge_and_done() -> None:
    board = reduce(
        [
            project(),
            ev(2, "INTENT", {"intent": {"id": "i001", "type": "explore", "from": "origin"}}),
            ev(3, "CONCLUDE", {"intentId": "i001", "facts": [{"id": "s1", "kind": "source"}]}),
        ]
    )
    intent = board.intents[0]
    assert intent.status == "done"
    assert intent.producedFacts == ["s1"]
    assert [f.id for f in board.facts] == ["s1"]
    relations = {(e.source, e.target, e.relation) for e in board.edges}
    assert ("i001", "s1", "resolves") in relations


def test_decompose_adds_decomposes_edge() -> None:
    board = reduce(
        [
            project(),
            ev(2, "INTENT", {"intent": {"id": "i001", "type": "decompose", "from": "f1"}}),
            ev(3, "CONCLUDE", {"intentId": "i001", "facts": [{"id": "f2", "kind": "fact"}]}),
        ]
    )
    relations = {(e.source, e.target, e.relation) for e in board.edges}
    assert ("f1", "f2", "decomposes") in relations


def test_payload_semantic_edges_are_applied() -> None:
    board = reduce(
        [
            project(),
            ev(
                2,
                "INTENT",
                {
                    "intent": {"id": "i001", "type": "explore"},
                    "edges": [
                        {"id": "f1->c1", "source": "f1", "target": "c1", "relation": "main-chain"}
                    ],
                },
            ),
        ]
    )
    assert any(e.relation == "main-chain" for e in board.edges)


def test_hitl_events() -> None:
    board = reduce(
        [
            project(),
            ev(2, "HINT", {"hint": {"id": "h1", "text": "check benchmark", "author": "human"}}),
            ev(3, "REQUEST_HUMAN", {"gate": "confirm-claim", "question": "ok?"}),
        ]
    )
    assert board.hints[0].text == "check benchmark"
    assert board.status == "awaiting_human"
    assert board.waitingFor is not None
    assert board.waitingFor.gate == "confirm-claim"

    resolved = reduce(
        [
            project(),
            ev(2, "REQUEST_HUMAN", {"gate": "confirm-claim", "question": "ok?"}),
            ev(3, "HUMAN_INPUT", {"gate": "confirm-claim", "decision": "approve"}),
        ]
    )
    assert resolved.status == "running"
    assert resolved.waitingFor is None
    assert resolved.decisions[0].decision == "approve"
    assert resolved.decisions[0].author == "human"
    assert resolved.decisions[0].at == "t3"


def test_complete_sets_verdict() -> None:
    board = reduce([project(), ev(2, "COMPLETE", {"verdict": "部分偏差"})])
    assert board.status == "completed"
    assert board.verdict == "部分偏差"


def test_failed_sets_terminal_status() -> None:
    board = reduce([project(), ev(2, "FAILED", {"reason": "validator failed"})])
    assert board.status == "failed"


def test_stopped_clears_waiting() -> None:
    board = reduce(
        [
            project(),
            ev(2, "REQUEST_HUMAN", {"gate": "confirm-claim", "question": "ok?"}),
            ev(3, "STOPPED", {"reason": "max_steps"}),
        ]
    )
    assert board.status == "stopped"
    assert board.waitingFor is None


def test_terminal_keeps_accumulated_state() -> None:
    board = reduce(
        [
            project(),
            ev(2, "INTENT", {"intent": {"id": "i001", "type": "explore"}}),
            ev(3, "FAILED", {"reason": "boom"}),
        ]
    )
    assert board.status == "failed"
    assert [intent.id for intent in board.intents] == ["i001"]


@pytest.mark.parametrize("kind", ["FAILED", "STOPPED"])
@pytest.mark.parametrize("payload", [{}, {"reason": 123}, {"reason": None}])
def test_terminal_requires_string_reason(kind: str, payload: dict[str, object]) -> None:
    with pytest.raises(ReduceError):
        reduce([project(), ev(2, kind, payload)])


def test_terminal_status_follows_last_event_and_keeps_verdict() -> None:
    failed_after_complete = reduce(
        [project(), ev(2, "COMPLETE", {"verdict": "部分偏差"}), ev(3, "FAILED", {"reason": "boom"})]
    )
    assert failed_after_complete.status == "failed"
    assert failed_after_complete.verdict == "部分偏差"

    completed_after_failed = reduce(
        [project(), ev(2, "FAILED", {"reason": "boom"}), ev(3, "COMPLETE", {"verdict": "done"})]
    )
    assert completed_after_failed.status == "completed"


def test_reduce_requires_project() -> None:
    with pytest.raises(ReduceError):
        reduce([ev(1, "REASON", {"phase": "start"})])


def test_reduce_rejects_unknown_intent() -> None:
    with pytest.raises(ReduceError):
        reduce([project(), ev(2, "EXECUTE", {"intentId": "missing"})])


def test_canonical_is_deterministic() -> None:
    events = [
        project(),
        ev(2, "INTENT", {"intent": {"id": "i001", "type": "explore"}}),
        ev(3, "HINT", {"hint": {"id": "h1", "text": "x"}}),
    ]
    assert render_canonical(reduce(events)) == render_canonical(reduce(events))
