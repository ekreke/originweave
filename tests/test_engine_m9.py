"""M9 tests: anti-explosion brakes (decompose two levels, dispatch width, fanout)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from originweave.blackboard import Board, Fact
from originweave.capabilities.base import PromptTemplate
from originweave.capabilities.model import ChatMessage
from originweave.capabilities.worker import LocalWorker
from originweave.engine import Engine
from originweave.store import RunStore

NO_REASON = json.dumps({"facts": [], "intents": [], "complete": None})


class _FakeModel:
    name = "fake"

    def __init__(self, *replies: str) -> None:
        if not replies:
            raise ValueError("at least one reply is required")
        self._replies = list(replies)

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        if self._replies:
            return self._replies.pop(0)
        return NO_REASON


class _FakeSearch:
    name = "fake"

    async def search(self, query: str, *, num_results: int = 8) -> str:
        return ""


class _FakePrompt:
    name = "fake"

    async def get(self, name: str) -> PromptTemplate:
        return PromptTemplate(name=name, text=name.upper())


def _engine(
    store: RunStore,
    *replies: str,
    dispatch_width: int = 6,
    max_fanout: int = 8,
    max_rounds: int = 10,
) -> Engine:
    return Engine(
        worker=LocalWorker(model=_FakeModel(*replies)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
        dispatch_width=dispatch_width,
        max_fanout=max_fanout,
        max_rounds=max_rounds,
    )


def _fact(fid: str, kind: str = "fact", **kwargs: object) -> Fact:
    return Fact.from_dict({"id": fid, "kind": kind, "label": fid, **kwargs})


def _bootstrap_reply(*claims: str) -> str:
    return json.dumps(
        {
            "facts": [
                {
                    "key": f"c{index}",
                    "label": label,
                    "kind": "fact",
                    "role": "main-claim",
                    "status": "open",
                    "confidence": 0.6,
                }
                for index, label in enumerate(claims, start=1)
            ],
            "edges": [],
            "intents": [],
            "complete": None,
        }
    )


def _reason_reply(*intents: dict[str, object]) -> str:
    return json.dumps({"facts": [], "intents": list(intents), "complete": None})


def _keep(*indexes: int) -> str:
    return json.dumps({"keep": list(indexes), "drop": []})


def _decompose_reply(*labels: str) -> str:
    return json.dumps(
        {
            "facts": [
                {
                    "key": f"k{index}",
                    "label": label,
                    "kind": "fact",
                    "role": "sub-claim",
                    "status": "open",
                    "confidence": 0.5,
                }
                for index, label in enumerate(labels, start=1)
            ],
            "intents": [],
            "complete": None,
        }
    )


def _explore_reply() -> str:
    return json.dumps({"facts": [], "edges": [], "intents": [], "complete": None})


# --------------------------------------------------------------- M9a decompose


async def test_decompose_off_a_sub_claim_is_dropped_not_fatal(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "decompose", "from": "f1", "question": "split"}),
        _keep(0),
        _decompose_reply("sub one"),  # f2 appears
        # A runaway subdivision: decompose a sub-claim (f2). The engine drops it, and
        # because it is the only candidate, Validate is not even consulted.
        _reason_reply({"type": "decompose", "from": "f2", "question": "split again"}),
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status == "stopped"  # dead-end, not failed
    decomposes = [intent for intent in board.intents if intent.type == "decompose"]
    assert [intent.status for intent in decomposes] == ["done", "dropped"]
    assert [intent.from_ for intent in decomposes] == ["f1", "f2"]
    dropped = [event for event in store.read_events() if event.type == "INTENT"]
    assert any("non main-claim" in event.message for event in dropped)


async def test_decompose_off_the_origin_is_dropped(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "decompose", "from": "origin", "question": "split origin"}),
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status == "stopped"
    assert [intent.status for intent in board.intents if intent.type == "decompose"] == ["dropped"]


async def test_decompose_off_a_main_claim_still_runs(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "decompose", "from": "f1", "question": "split"}),
        _keep(0),
        _decompose_reply("sub one", "sub two"),
        NO_REASON,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    decomposes = [intent for intent in board.intents if intent.type == "decompose"]
    assert [intent.status for intent in decomposes] == ["done"]
    assert sorted(fact.role for fact in board.facts) == ["main-claim", "sub-claim", "sub-claim"]


# ------------------------------------------------------------ M9b dispatch width


async def test_dispatch_width_caps_a_round_and_later_dispatches_the_rest(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply(
            {"type": "explore", "from": "f1", "question": "a"},
            {"type": "explore", "from": "f1", "question": "b"},
            {"type": "explore", "from": "f1", "question": "c"},
        ),
        _keep(0, 1, 2),
        _explore_reply(),  # round 1, first dispatched pass
        _explore_reply(),  # round 1, second dispatched pass
        _reason_reply(),  # round 2: Reason offers nothing new
        _explore_reply(),  # round 2: the throttled pass finally runs
        dispatch_width=2,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    # i1 is Bootstrap's own Intent; i2/i3 run in round 1; i4 is throttled to round 2.
    executed = [
        event.payload["intentId"] for event in store.read_events() if event.type == "EXECUTE"
    ]
    assert executed == ["i1", "i2", "i3", "i4"]
    # i1 (Bootstrap) plus the three Reason Intents all completed -- none was left open.
    explores = [intent for intent in board.intents if intent.type == "explore"]
    assert [intent.status for intent in explores] == ["done", "done", "done", "done"]
    assert board.status == "stopped"  # nothing left to run -> stalled


# --------------------------------------------------------------- M9b fanout cap


async def test_decompose_fanout_keeps_the_first_n_in_reply_order(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "decompose", "from": "f1", "question": "split"}),
        _keep(0),
        _decompose_reply(*[f"sub {i}" for i in range(10)]),
        NO_REASON,
        max_fanout=3,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    sub_claims = [fact for fact in board.facts if fact.role == "sub-claim"]
    assert [fact.label for fact in sub_claims] == ["sub 0", "sub 1", "sub 2"]
    conclude = [event for event in store.read_events() if event.type == "CONCLUDE"][-1]
    assert "capped at 3" in conclude.message


async def test_fanout_cap_drops_edges_to_surplus_facts_without_failing(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    # A decompose reply that also carries an edge to a surplus fact key: capping must drop
    # that edge, not turn the reply into a terminal FAILED.
    reply = json.dumps(
        {
            "facts": [
                {
                    "key": f"k{i + 1}",
                    "label": f"sub {i}",
                    "kind": "fact",
                    "role": "sub-claim",
                    "status": "open",
                    "confidence": 0.5,
                }
                for i in range(4)
            ],
            "edges": [{"source": "f1", "target": "k4", "relation": "dependency"}],
            "intents": [],
            "complete": None,
        }
    )
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "decompose", "from": "f1", "question": "split"}),
        _keep(0),
        reply,
        NO_REASON,
        max_fanout=2,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status != "failed"
    assert len([fact for fact in board.facts if fact.role == "sub-claim"]) == 2


# ------------------------------------------------------------- M9 determinism


async def test_brakes_are_deterministic(tmp_path: Path) -> None:
    def structure(board: Board) -> dict[str, object]:
        return {
            "status": board.status,
            "facts": [(f.id, f.role) for f in board.facts],
            "intents": [(i.id, i.type, i.status) for i in board.intents],
        }

    async def run_once(name: str) -> dict[str, object]:
        store = RunStore(tmp_path / name)
        engine = _engine(
            store,
            _bootstrap_reply("A claim"),
            _reason_reply(
                {"type": "decompose", "from": "f1", "question": "split"},
                {"type": "decompose", "from": "f1", "question": "split again"},
            ),
            _keep(0, 1),
            # round 1 dispatches i2 (width=1); its 3 sub-claims are capped to 2.
            _decompose_reply("s1", "s2", "s3"),
            _reason_reply(),  # round 2: Reason offers nothing new
            _decompose_reply("s4"),  # round 2 dispatches i3
            NO_REASON,  # round 3: nothing left -> stalled
            dispatch_width=1,
            max_fanout=2,
        )
        board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
        return structure(board)

    assert await run_once("a") == await run_once("b")


# ------------------------------------------------------------- M9 param guards


def test_engine_rejects_non_positive_brakes(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    with pytest.raises(ValueError, match="dispatch_width"):
        _engine(store, NO_REASON, dispatch_width=0)
    with pytest.raises(ValueError, match="max_fanout"):
        _engine(store, NO_REASON, max_fanout=0)
