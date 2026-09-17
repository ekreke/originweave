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


class _FakeModel:
    name = "fake"

    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.calls: list[list[ChatMessage]] = []

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        return self._reply


class _FakeSearch:
    name = "fake"

    async def search(self, query: str, *, num_results: int = 8) -> str:
        return ""


class _FakePrompt:
    name = "fake"

    async def get(self, name: str) -> PromptTemplate:
        return PromptTemplate(name=name, text="BOOTSTRAP")


def _origin() -> Fact:
    return Fact.from_dict({"id": "origin", "kind": "origin", "label": "Document A"})


def _goal() -> Fact:
    return Fact.from_dict({"id": "goal", "kind": "goal", "label": "Every sub-claim is sourced"})


def _engine(store: RunStore, reply: str) -> Engine:
    return Engine(
        model=_FakeModel(reply),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
    )


async def test_bootstrap_produces_a_main_claim(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    reply = json.dumps(
        {
            "facts": [
                {
                    "label": "Copilot cut task time by 55%.",
                    "kind": "fact",
                    "role": "main-claim",
                    "status": "open",
                    "confidence": 0.7,
                }
            ],
            "intents": [],
            "complete": None,
        }
    )
    model = _FakeModel(reply)
    engine = Engine(
        model=model,
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    assert board.origin.kind == "origin"
    assert board.goal.kind == "goal"
    main = [fact for fact in board.facts if fact.role == "main-claim"]
    assert [fact.id for fact in main] == ["f1"]
    assert main[0].kind == "fact"
    assert main[0].confidence == 0.7

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
        "REASON",
        "INTENT",
        "EXECUTE",
        "CONCLUDE",
        "REASON",
    ]

    assert len(model.calls) == 1
    assert model.calls[0][0].role == "system"


async def test_bootstrap_allows_multiple_main_claims(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    reply = json.dumps(
        {
            "facts": [
                {"label": "Claim one", "kind": "fact", "role": "main-claim"},
                {"label": "Claim two", "kind": "fact", "role": "main-claim"},
            ],
            "intents": [],
            "complete": None,
        }
    )
    board = await _engine(store, reply).run(origin=_origin(), goal=_goal())
    assert [fact.id for fact in board.facts] == ["f1", "f2"]
    assert all(fact.role == "main-claim" for fact in board.facts)


async def test_board_is_deterministic(tmp_path: Path) -> None:
    reply = json.dumps(
        {
            "facts": [{"label": "A claim", "kind": "fact", "role": "main-claim"}],
            "intents": [],
            "complete": None,
        }
    )
    store = RunStore(tmp_path / "a")
    first = await _engine(store, reply).run(origin=_origin(), goal=_goal())
    # The reducer is a pure fold: the same events always yield the same board.
    assert render_canonical(first) == render_canonical(reduce(store.read_events()))

    second = await _engine(RunStore(tmp_path / "b"), reply).run(origin=_origin(), goal=_goal())
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
