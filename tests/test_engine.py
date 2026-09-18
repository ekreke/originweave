from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from originweave.blackboard import Fact
from originweave.capabilities.base import PromptTemplate
from originweave.capabilities.model import ChatMessage
from originweave.engine import Engine, EngineError, parse_result
from originweave.reduce import reduce, render_canonical
from originweave.store import RunStore

REPO_ROOT = Path(__file__).resolve().parents[1]

# A Reason reply that proposes nothing, so a test can focus on the Bootstrap pass.
NO_REASON = json.dumps({"facts": [], "intents": [], "complete": None})


class _FakeModel:
    name = "fake"

    def __init__(self, *replies: str) -> None:
        if not replies:
            raise ValueError("at least one reply is required")
        self._replies = list(replies)
        self.calls: list[list[ChatMessage]] = []

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        # Consume queued replies in order, then keep returning the last one.
        if len(self._replies) > 1:
            return self._replies.pop(0)
        return self._replies[0]


class _FakeSearch:
    name = "fake"

    async def search(self, query: str, *, num_results: int = 8) -> str:
        return ""


class _FakePrompt:
    name = "fake"

    async def get(self, name: str) -> PromptTemplate:
        return PromptTemplate(name=name, text=name.upper())


def _origin() -> Fact:
    return Fact.from_dict({"id": "origin", "kind": "origin", "label": "Document A"})


def _goal() -> Fact:
    return Fact.from_dict({"id": "goal", "kind": "goal", "label": "Every sub-claim is sourced"})


def _engine(store: RunStore, *replies: str) -> Engine:
    return Engine(
        model=_FakeModel(*replies),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
    )


def _bootstrap(*labels: str) -> str:
    return json.dumps(
        {
            "facts": [
                {"label": label, "kind": "fact", "role": "main-claim", "status": "open"}
                for label in labels
            ],
            "intents": [],
            "complete": None,
        }
    )


def _reason(*intents: dict[str, object]) -> str:
    return json.dumps({"facts": [], "intents": list(intents), "complete": None})


async def test_bootstrap_produces_a_main_claim(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    model = _FakeModel(_bootstrap("Copilot cut task time by 55%."), NO_REASON)
    engine = Engine(model=model, search=_FakeSearch(), prompt=_FakePrompt(), store=store)
    board = await engine.run(origin=_origin(), goal=_goal())

    assert board.origin.kind == "origin"
    assert board.goal.kind == "goal"
    main = [fact for fact in board.facts if fact.role == "main-claim"]
    assert [fact.id for fact in main] == ["f1"]
    assert main[0].kind == "fact"

    assert [intent.id for intent in board.intents] == ["i1"]
    assert board.intents[0].status == "done"
    assert board.intents[0].type == "explore"
    assert board.intents[0].producedFacts == ["f1"]

    relations = {(edge.source, edge.target, edge.relation) for edge in board.edges}
    assert ("origin", "i1", "spawns") in relations
    assert ("i1", "f1", "resolves") in relations

    events = store.read_events()
    assert [event.id for event in events] == [f"e{i:04d}" for i in range(1, len(events) + 1)]
    assert [event.type for event in events] == [
        "PROJECT",
        "INTENT",
        "EXECUTE",
        "CONCLUDE",
        "REASON",
        "REASON",
    ]

    assert len(model.calls) == 2
    assert model.calls[0][0].role == "system"


async def test_bootstrap_allows_multiple_main_claims(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(store, _bootstrap("Claim one", "Claim two"), NO_REASON).run(
        origin=_origin(), goal=_goal()
    )
    assert [fact.id for fact in board.facts] == ["f1", "f2"]
    assert all(fact.role == "main-claim" for fact in board.facts)


async def test_reason_writes_candidate_intents(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("A claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split into sub-claims."}),
    ).run(origin=_origin(), goal=_goal())

    assert [intent.id for intent in board.intents] == ["i1", "i2"]
    proposed = board.intents[1]
    assert proposed.type == "decompose"
    assert proposed.from_ == "f1"
    assert proposed.status == "open"
    relations = {(edge.source, edge.target, edge.relation) for edge in board.edges}
    assert ("f1", "i2", "spawns") in relations


async def test_reason_rejects_facts(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    bad_reason = json.dumps(
        {"facts": [{"label": "x", "kind": "fact", "role": "none"}], "intents": [], "complete": None}
    )
    with pytest.raises(EngineError):
        await _engine(store, _bootstrap("A claim"), bad_reason).run(origin=_origin(), goal=_goal())


async def test_reason_rejects_unknown_from(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    with pytest.raises(EngineError):
        await _engine(
            store,
            _bootstrap("A claim"),
            _reason({"type": "decompose", "from": "f9", "question": "?"}),
        ).run(origin=_origin(), goal=_goal())


async def test_reason_assigns_sequential_ids(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("Claim one", "Claim two"),
        _reason(
            {"type": "decompose", "from": "f1", "question": "Split f1."},
            {"type": "explore", "from": "f2", "question": "Source f2."},
        ),
    ).run(origin=_origin(), goal=_goal())

    assert [intent.id for intent in board.intents] == ["i1", "i2", "i3"]
    assert [intent.type for intent in board.intents[1:]] == ["decompose", "explore"]
    assert all(intent.status == "open" for intent in board.intents[1:])


async def test_reason_rejects_goal_as_from(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    with pytest.raises(EngineError):
        await _engine(
            store,
            _bootstrap("A claim"),
            _reason({"type": "explore", "from": "goal", "question": "?"}),
        ).run(origin=_origin(), goal=_goal())


async def test_reason_bad_from_writes_nothing(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    reason = _reason(
        {"type": "decompose", "from": "f1", "question": "ok"},
        {"type": "explore", "from": "f9", "question": "bad"},
    )
    with pytest.raises(EngineError):
        await _engine(store, _bootstrap("A claim"), reason).run(origin=_origin(), goal=_goal())
    # The good candidate must not be half-written when a later one is rejected.
    assert sum(event.type == "INTENT" for event in store.read_events()) == 1


async def test_reason_intents_are_deterministic(tmp_path: Path) -> None:
    bootstrap = _bootstrap("A claim")
    reason = _reason({"type": "decompose", "from": "f1", "question": "Split it."})
    first = await _engine(RunStore(tmp_path / "a"), bootstrap, reason).run(
        origin=_origin(), goal=_goal()
    )
    second = await _engine(RunStore(tmp_path / "b"), bootstrap, reason).run(
        origin=_origin(), goal=_goal()
    )
    assert [(i.id, i.type, i.from_, i.status) for i in first.intents] == [
        (i.id, i.type, i.from_, i.status) for i in second.intents
    ]
    assert [(e.source, e.target, e.relation) for e in first.edges] == [
        (e.source, e.target, e.relation) for e in second.edges
    ]


async def test_reason_complete_writes_complete(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    reason = json.dumps({"facts": [], "intents": [], "complete": {"verdict": "部分偏差"}})
    board = await _engine(store, _bootstrap("A claim"), reason).run(origin=_origin(), goal=_goal())

    assert board.status == "completed"
    assert board.verdict == "部分偏差"
    events = store.read_events()
    assert events[-1].type == "COMPLETE"
    assert events[-2].type == "REASON"
    assert events[-2].payload == {"phase": "end"}


async def test_reason_rejects_intents_and_complete_together(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    reason = json.dumps(
        {
            "facts": [],
            "intents": [{"type": "decompose", "from": "f1", "question": "?"}],
            "complete": {"verdict": "done"},
        }
    )
    with pytest.raises(EngineError):
        await _engine(store, _bootstrap("A claim"), reason).run(origin=_origin(), goal=_goal())


async def test_board_is_deterministic(tmp_path: Path) -> None:
    bootstrap = _bootstrap("A claim")
    store = RunStore(tmp_path / "a")
    first = await _engine(store, bootstrap, NO_REASON).run(origin=_origin(), goal=_goal())
    # The reducer is a pure fold: the same events always yield the same board.
    assert render_canonical(first) == render_canonical(reduce(store.read_events()))

    second = await _engine(RunStore(tmp_path / "b"), bootstrap, NO_REASON).run(
        origin=_origin(), goal=_goal()
    )
    # Across two runs only volatile timestamps differ; the structure is identical.
    assert [(f.id, f.kind, f.role) for f in first.facts] == [
        (f.id, f.kind, f.role) for f in second.facts
    ]
    assert [(i.id, i.type, i.status) for i in first.intents] == [
        (i.id, i.type, i.status) for i in second.intents
    ]
    assert [(e.source, e.target, e.relation) for e in first.edges] == [
        (e.source, e.target, e.relation) for e in second.edges
    ]


def test_parse_result_reads_fields_and_ids_evidence() -> None:
    result = parse_result(
        json.dumps(
            {
                "facts": [
                    {
                        "label": "x",
                        "kind": "fact",
                        "role": "main-claim",
                        "confidence": 0.5,
                        "evidence": [
                            {"quote": "q", "sourceTitle": "t", "url": "u", "locator": "l"}
                        ],
                    }
                ],
                "intents": [{"type": "decompose", "from": "f1", "question": "split it"}],
                "complete": {"verdict": "partial"},
            }
        )
    )
    assert result.complete == "partial"
    assert result.facts[0].evidence[0].id == "ev1"
    assert result.facts[0].evidence[0].quote == "q"
    assert result.intents[0].type == "decompose"


def test_parse_result_rejects_non_json() -> None:
    with pytest.raises(EngineError):
        parse_result("not json")


def test_parse_result_rejects_unknown_fact_kind() -> None:
    with pytest.raises(EngineError):
        parse_result(json.dumps({"facts": [{"label": "x", "kind": "nope", "role": "main-claim"}]}))


def test_parse_result_rejects_unknown_intent_type() -> None:
    with pytest.raises(EngineError):
        parse_result(json.dumps({"intents": [{"type": "guess", "question": "q"}]}))


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
async def test_live_bootstrap_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from originweave import config
    from originweave.capabilities import build_model, build_prompt, build_search

    monkeypatch.chdir(REPO_ROOT)
    cfg = config.Config()
    document = (REPO_ROOT / "examples/copilot_productivity/input/document.md").read_text(
        encoding="utf-8"
    )
    origin = Fact.from_dict(
        {"id": "origin", "kind": "origin", "label": "Document A", "note": document}
    )
    engine = Engine(
        model=build_model(cfg),
        search=build_search(cfg),
        prompt=build_prompt(cfg),
        store=RunStore(tmp_path / "live"),
    )
    board = await engine.run(origin=origin, goal=_goal())
    assert any(fact.role == "main-claim" for fact in board.facts)
