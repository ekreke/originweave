"""M5 tests: the extract/relate passes, entity merging and the entity-relation graph."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from originweave.blackboard import Board, Fact, canonical_name
from originweave.capabilities.base import PromptTemplate
from originweave.capabilities.model import ChatMessage
from originweave.capabilities.worker import LocalWorker
from originweave.engine import Engine, EngineError, parse_result
from originweave.store import RunStore

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


def _engine(store: RunStore, *replies: str, analysis: str = "relation") -> Engine:
    return Engine(
        worker=LocalWorker(model=_FakeModel(*replies)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
        analysis=analysis,
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


def _complete_reply(verdict: str) -> str:
    return json.dumps({"facts": [], "intents": [], "complete": {"verdict": verdict}})


def _entity(name: str, etype: str = "organization", **kwargs: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": name,
        "type": etype,
        "status": "open",
        "confidence": 0.8,
    }
    body.update(kwargs)
    return body


def _extract_reply(*entities: dict[str, object]) -> str:
    return json.dumps(
        {
            "entities": list(entities),
            "relations": [],
            "facts": [],
            "intents": [],
            "complete": None,
        }
    )


def _relation(
    source: str, target: str, rtype: str = "acquires", **kwargs: object
) -> dict[str, object]:
    body: dict[str, object] = {
        "source": source,
        "target": target,
        "type": rtype,
        "status": "verified",
        "confidence": 0.7,
        "inferred": False,
        "evidence": [
            {
                "quote": "q",
                "sourceTitle": "A",
                "url": "https://example.com/a",
                "locator": "p.1",
            }
        ],
    }
    body.update(kwargs)
    return body


def _relate_reply(*relations: dict[str, object]) -> str:
    return json.dumps(
        {
            "relations": list(relations),
            "entities": [],
            "facts": [],
            "intents": [],
            "complete": None,
        }
    )


def _graph_run_replies(
    entities: tuple[dict[str, object], ...],
    relations: tuple[dict[str, object], ...],
    *,
    complete: str | None = "graph judged",
) -> tuple[str, ...]:
    """A full relation-analysis script: bootstrap, extract, relate, then converge."""
    relate_intents: list[dict[str, object]] = [
        {"type": "relate", "from": f"n{i}", "question": "judge"}
        for i in range(1, len(entities) + 1)
    ]
    replies: list[str] = [
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "extract", "from": "origin", "question": "extract entities"}),
        _keep(0),
        _extract_reply(*entities),
        _reason_reply(*relate_intents),
        _keep(*range(len(entities))),
        # One worker call per relate Intent: judge every relation on the first pass and
        # leave the rest empty (id order keeps the relation ids deterministic).
        _relate_reply(*relations),
        *(_relate_reply() for _ in range(max(0, len(entities) - 1))),
    ]
    if complete is not None:
        replies.append(_complete_reply(complete))
    return tuple(replies)


# ------------------------------------------------------------- M5-1 canonical_name


def test_canonical_name_folds_case_and_whitespace() -> None:
    assert canonical_name("  GitHub,  Inc. ") == canonical_name("github, inc.")
    # NFKC folds full-width latin into its ASCII form.
    assert canonical_name("ＡＣＭＥ") == canonical_name("acme")


# --------------------------------------------------------------- M5-1 parse


def test_parse_result_reads_entities() -> None:
    result = parse_result(
        json.dumps({"entities": [_entity("GitHub", aliases=["GitHub, Inc."])]}),
        allow_entities=True,
    )
    assert len(result.entities) == 1
    assert result.entities[0].name == "GitHub"
    assert result.entities[0].aliases == ["GitHub, Inc."]
    assert result.entities[0].id == "?"  # assigned by the engine


def test_parse_result_rejects_entities_when_not_allowed() -> None:
    with pytest.raises(EngineError, match="must not carry 'entities'"):
        parse_result(json.dumps({"entities": [_entity("X")]}))


def test_parse_result_reads_relations() -> None:
    result = parse_result(json.dumps({"relations": [_relation("n1", "n2")]}), allow_relations=True)
    assert result.relations[0].source == "n1"
    assert result.relations[0].type == "acquires"


def test_parse_result_rejects_relations_when_not_allowed() -> None:
    with pytest.raises(EngineError, match="must not carry 'relations'"):
        parse_result(json.dumps({"relations": [_relation("n1", "n2")]}))


def test_parse_result_rejects_inferred_relation_without_confidence() -> None:
    inferred = _relation("n1", "n2", status="inferred", inferred=True, confidence=0.0)
    with pytest.raises(EngineError, match="confidence"):
        parse_result(json.dumps({"relations": [inferred]}), allow_relations=True)


def test_parse_result_rejects_unknown_entity_type() -> None:
    with pytest.raises(EngineError, match="entity.type"):
        parse_result(json.dumps({"entities": [_entity("X", etype="alien")]}), allow_entities=True)


# --------------------------------------------------------- M5-2 extract/relate run


async def test_relation_run_builds_entity_graph(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        *_graph_run_replies(
            (_entity("GitHub"), _entity("Microsoft")),
            (
                _relation("n1", "n2"),
                _relation(
                    "n2",
                    "n1",
                    "competes-with",
                    status="inferred",
                    inferred=True,
                    confidence=0.5,
                    evidence=[],
                ),
            ),
        ),
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status == "completed"
    assert [(e.id, e.name, e.type) for e in board.entities] == [
        ("n1", "GitHub", "organization"),
        ("n2", "Microsoft", "organization"),
    ]
    assert [(r.id, r.source, r.target, r.type, r.inferred) for r in board.relations] == [
        ("r1", "n1", "n2", "acquires", False),
        ("r2", "n2", "n1", "competes-with", True),
    ]
    # Relation-only analysis completes without a provenance compare pass.
    assert all(fact.kind != "compare" for fact in board.facts)


async def test_entity_graph_json_matches_the_board(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        *_graph_run_replies(
            (_entity("GitHub"), _entity("Microsoft")),
            (_relation("n1", "n2"),),
        ),
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    payload = json.loads(store.entity_graph_path.read_text(encoding="utf-8"))
    assert [e["id"] for e in payload["entities"]] == [e.id for e in board.entities]
    assert [r["id"] for r in payload["relations"]] == [r.id for r in board.relations]


async def test_extract_merges_same_canonical_name(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "extract", "from": "origin", "question": "extract"}),
        _keep(0),
        # "github" is a case variant (same canonical); "GitHub, Inc." is a distinct alias.
        _extract_reply(
            _entity("GitHub"),
            _entity("github"),
            _entity("GitHub", aliases=["GitHub, Inc."]),
        ),
        NO_REASON,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status == "stopped"  # Reason proposed nothing after the extract round
    assert len(board.entities) == 1
    entity = board.entities[0]
    assert entity.id == "n1"
    assert entity.name == "GitHub"  # first-seen wins
    assert entity.aliases == ["GitHub, Inc."]  # the case variant is not restated


async def test_extract_merge_across_passes_accumulates_aliases(tmp_path: Path) -> None:
    """A second extract pass that renames an entity merges into the first (id stable)."""
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "extract", "from": "origin", "question": "extract"}),
        _keep(0),
        _extract_reply(_entity("GitHub")),
        # A later round extracts a variant name and an alias; both must merge into n1.
        _reason_reply({"type": "extract", "from": "origin", "question": "extract more"}),
        _keep(0),
        _extract_reply(_entity("github", aliases=["GH"])),
        NO_REASON,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert [(e.id, e.name) for e in board.entities] == [("n1", "GitHub")]
    assert board.entities[0].aliases == ["GH"]  # "github" folds into the name's canonical


async def test_inferred_relation_is_normalized_to_inferred_status(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        *_graph_run_replies(
            (_entity("A"), _entity("B")),
            (
                _relation(
                    "n1",
                    "n2",
                    "partners-with",
                    status="open",
                    inferred=True,
                    confidence=0.4,
                    evidence=[],
                ),
            ),
        ),
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status == "completed"
    assert board.relations[0].status == "inferred"
    assert board.relations[0].inferred is True


# ------------------------------------------------------------ M5-2 failure paths


async def test_provenance_run_rejects_an_extract_intent(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "extract", "from": "origin", "question": "extract"}),
        analysis="provenance",
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status == "failed"
    reason = [event for event in store.read_events() if event.type == "FAILED"][-1]
    assert "requires analysis=relation" in reason.payload["reason"]


async def test_relate_intent_off_an_unknown_entity_fails(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "relate", "from": "n99", "question": "judge"}),
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status == "failed"
    assert (
        "is not a known entity id"
        in [event.payload["reason"] for event in store.read_events() if event.type == "FAILED"][-1]
    )


async def test_relation_referencing_an_unknown_entity_fails_at_commit(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "extract", "from": "origin", "question": "extract"}),
        _keep(0),
        _extract_reply(_entity("GitHub")),
        _reason_reply({"type": "relate", "from": "n1", "question": "judge"}),
        _keep(0),
        _relate_reply(_relation("n1", "n7")),
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status == "failed"
    assert (
        "relation.target 'n7' is not a known entity id"
        in [event.payload["reason"] for event in store.read_events() if event.type == "FAILED"][-1]
    )


async def test_extract_reply_carrying_a_fact_fails(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    bad_extract = json.dumps(
        {
            "entities": [_entity("GitHub")],
            "facts": [{"label": "x", "kind": "fact", "role": "none"}],
            "intents": [],
            "complete": None,
        }
    )
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "extract", "from": "origin", "question": "extract"}),
        _keep(0),
        bad_extract,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status == "failed"
    assert "must not produce facts" in [
        event.payload["reason"] for event in store.read_events() if event.type == "FAILED"
    ][-1]


async def test_relate_reply_carrying_entities_fails(tmp_path: Path) -> None:
    """A relate pass must not produce entities (the extract pass owns them)."""
    store = RunStore(tmp_path / "run_001")
    bad_relate = json.dumps(
        {
            "relations": [],
            "entities": [_entity("GitHub")],
            "facts": [],
            "intents": [],
            "complete": None,
        }
    )
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "extract", "from": "origin", "question": "extract"}),
        _keep(0),
        _extract_reply(_entity("GitHub")),
        _reason_reply({"type": "relate", "from": "n1", "question": "judge"}),
        _keep(0),
        bad_relate,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status == "failed"
    assert "must not produce entities" in [
        event.payload["reason"] for event in store.read_events() if event.type == "FAILED"
    ][-1]


async def test_relation_self_loop_fails(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "extract", "from": "origin", "question": "extract"}),
        _keep(0),
        _extract_reply(_entity("GitHub")),
        _reason_reply({"type": "relate", "from": "n1", "question": "judge"}),
        _keep(0),
        _relate_reply(_relation("n1", "n1")),
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status == "failed"
    assert "self-loop" in [
        event.payload["reason"] for event in store.read_events() if event.type == "FAILED"
    ][-1]


def test_parse_result_rejects_status_inferred_without_the_flag() -> None:
    inconsistent = _relation("n1", "n2", status="inferred", inferred=False)
    with pytest.raises(EngineError, match="inferred is false"):
        parse_result(json.dumps({"relations": [inconsistent]}), allow_relations=True)


async def test_merge_upgrades_type_and_takes_max_confidence(tmp_path: Path) -> None:
    """A second pass with a more specific type / higher confidence folds into n1."""
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "extract", "from": "origin", "question": "extract"}),
        _keep(0),
        _extract_reply(_entity("Acme", etype="other", confidence=0.3, aliases=["ACME Corp"])),
        _reason_reply({"type": "extract", "from": "origin", "question": "extract more"}),
        _keep(0),
        _extract_reply(_entity("acme", etype="organization", confidence=0.9)),
        NO_REASON,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert len(board.entities) == 1
    entity = board.entities[0]
    assert entity.id == "n1"
    assert entity.type == "organization"  # upgraded from "other"
    assert entity.confidence == 0.9  # max
    assert entity.aliases == ["ACME Corp"]
    assert board.status == "stopped"


# ------------------------------------------------------------- M5-2 stop condition


async def test_both_analysis_needs_the_provenance_chain_too(tmp_path: Path) -> None:
    """A ``both`` run does not complete on the relation graph alone (TODO M5 decision)."""
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        *_graph_run_replies(
            (_entity("GitHub"), _entity("Microsoft")),
            (_relation("n1", "n2"),),
        ),
        analysis="both",
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    # Reason said complete and the relation condition held, but no compare pass scored
    # the provenance side, so the run stops at a dead-end instead of completing.
    assert board.status == "stopped"
    assert all(fact.kind != "compare" for fact in board.facts)


# ------------------------------------------------------------- M5-2 determinism


async def test_entity_graph_run_is_deterministic(tmp_path: Path) -> None:
    def structure(board: Board) -> dict[str, object]:
        return {
            "status": board.status,
            "entities": [(e.id, e.name, tuple(e.aliases)) for e in board.entities],
            "relations": [(r.id, r.source, r.target, r.type, r.status) for r in board.relations],
        }

    async def run_once(name: str) -> dict[str, object]:
        store = RunStore(tmp_path / name)
        engine = _engine(
            store,
            *_graph_run_replies(
                (_entity("GitHub"), _entity("Microsoft"), _entity("github")),
                (_relation("n1", "n2"),),
            ),
        )
        board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
        return structure(board)

    assert await run_once("a") == await run_once("b")


async def test_restore_counters_resumes_entity_and_relation_ids(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        *_graph_run_replies(
            (_entity("GitHub"), _entity("Microsoft")),
            (_relation("n1", "n2"),),
        ),
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
    events = store.read_events()

    # A fresh Engine over the same run must not reuse n1/n2/r1 on resume.
    resumed = _engine(store, NO_REASON)
    resumed._restore_counters(board, events)
    assert resumed._next_entity_id() == "n3"
    assert resumed._next_relation_id() == "r2"


async def test_bootstrap_rejects_a_non_main_claim_fact(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    reply = json.dumps(
        {
            "facts": [{"label": "x", "kind": "fact", "role": "none", "status": "open"}],
            "intents": [],
            "complete": None,
        }
    )
    engine = _engine(store, reply)
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
    assert board.status == "failed"
