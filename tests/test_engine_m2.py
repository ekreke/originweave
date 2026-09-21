"""M2 tests: verify dispatch, semantic edges, deviation scoring and reports."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from originweave.blackboard import Board, Fact
from originweave.capabilities.base import PromptTemplate
from originweave.capabilities.model import ChatMessage
from originweave.capabilities.worker import LocalWorker
from originweave.cli import main
from originweave.engine import Engine, EngineError, _resolve_edges, parse_result
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


class _RecordingSearch:
    name = "recording"

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, *, num_results: int = 8) -> str:
        self.queries.append(query)
        return ""


class _FakePrompt:
    name = "fake"

    async def get(self, name: str) -> PromptTemplate:
        return PromptTemplate(name=name, text=name.upper())


def _engine(store: RunStore, *replies: str) -> Engine:
    return Engine(
        worker=LocalWorker(model=_FakeModel(*replies)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )


def _fact(fid: str, kind: str = "fact", **kwargs: object) -> Fact:
    return Fact.from_dict({"id": fid, "kind": kind, "label": fid, **kwargs})


def _board(*facts: Fact) -> Board:
    return Board(
        origin=_fact("origin", "origin"),
        goal=_fact("goal", "goal"),
        facts=list(facts),
    )


def _reply(**fields: object) -> str:
    payload: dict[str, object] = {
        "facts": [],
        "intents": [],
        "complete": None,
        "edges": [],
    }
    payload.update(fields)
    return json.dumps(payload)


def _deviation_fact(
    key: str, *, severity: str = "high", confidence: float = 0.9
) -> dict[str, object]:
    return {
        "key": key,
        "label": "attribution error",
        "kind": "deviation",
        "role": "none",
        "status": "flagged",
        "confidence": confidence,
        "subtitle": f"severity={severity} · confidence={confidence:.2f}",
        "evidence": [
            {
                "quote": "55%",
                "sourceTitle": "Lab study",
                "url": "https://example.com/lab",
                "locator": "p.1",
            }
        ],
    }


# ------------------------------------------------------------------ M2-1 parsing


def test_parse_result_reads_edges_and_keys() -> None:
    result = parse_result(
        _reply(
            facts=[_deviation_fact("dev1")],
            edges=[{"source": "f1", "target": "dev1", "relation": "goal-derived", "note": "x"}],
        ),
        allow_edges=True,
    )
    assert result.fact_keys == {"dev1": 0}
    assert result.facts[0].kind == "deviation"
    assert result.edges == [
        {"source": "f1", "target": "dev1", "relation": "goal-derived", "note": "x"}
    ]


def test_parse_result_drops_the_worker_local_key_from_the_fact() -> None:
    result = parse_result(_reply(facts=[_deviation_fact("dev1")]), allow_edges=True)
    assert not hasattr(result.facts[0], "key")
    assert result.facts[0].to_dict().get("key") is None


def test_parse_result_rejects_duplicate_fact_key() -> None:
    with pytest.raises(EngineError, match="duplicate fact.key"):
        parse_result(
            _reply(facts=[_deviation_fact("dup"), _deviation_fact("dup")]), allow_edges=True
        )


def test_parse_result_rejects_empty_fact_key() -> None:
    with pytest.raises(EngineError, match="fact.key"):
        parse_result(_reply(facts=[_deviation_fact("")]), allow_edges=True)


def test_parse_result_rejects_structural_edges() -> None:
    with pytest.raises(EngineError, match="edge.relation"):
        parse_result(
            _reply(edges=[{"source": "f1", "target": "f2", "relation": "spawns"}]),
            allow_edges=True,
        )


def test_parse_result_rejects_edges_when_not_allowed() -> None:
    with pytest.raises(EngineError, match="must not carry 'edges'"):
        parse_result(_reply(edges=[{"source": "f1", "target": "f2", "relation": "main-chain"}]))


def test_parse_result_reads_a_gate_request() -> None:
    result = parse_result(
        _reply(gate={"gate": "arbitrate", "question": "which source?"}), allow_gate=True
    )
    assert result.gate == {"gate": "arbitrate", "question": "which source?"}


def test_parse_result_rejects_gate_when_not_allowed() -> None:
    with pytest.raises(EngineError, match="must not carry 'gate'"):
        parse_result(_reply(gate={"gate": "arbitrate", "question": "q"}))


def test_parse_result_rejects_unknown_gate_name() -> None:
    with pytest.raises(EngineError, match="gate.gate"):
        parse_result(_reply(gate={"gate": "review", "question": "q"}), allow_gate=True)


def test_parse_result_rejects_gate_with_complete() -> None:
    with pytest.raises(EngineError, match="both 'gate' and 'complete'"):
        parse_result(
            _reply(gate={"gate": "arbitrate", "question": "q"}, complete={"verdict": "v"}),
            allow_gate=True,
        )


# --------------------------------------------------------------- M2-1 resolution


def test_resolve_edges_maps_keys_and_board_ids() -> None:
    board = _board(_fact("f1"))
    raw = parse_result(
        _reply(
            facts=[_deviation_fact("dev1")],
            edges=[{"source": "f1", "target": "dev1", "relation": "goal-derived"}],
        ),
        allow_edges=True,
    )
    edges = _resolve_edges(raw.edges, ["d1"], {"dev1": "d1"}, board, intent_id="i1")
    assert [(edge.source, edge.target, edge.relation) for edge in edges] == [
        ("f1", "d1", "goal-derived")
    ]
    assert edges[0].id == "i1-e1"


def test_resolve_edges_accepts_origin_and_goal() -> None:
    board = _board()
    raw = parse_result(
        _reply(edges=[{"source": "goal", "target": "origin", "relation": "goal-derived"}]),
        allow_edges=True,
    )
    edges = _resolve_edges(raw.edges, [], {}, board, intent_id="i2")
    assert edges[0].source == "goal"
    assert edges[0].target == "origin"


def test_resolve_edges_rejects_unknown_reference() -> None:
    board = _board(_fact("f1"))
    raw = parse_result(
        _reply(edges=[{"source": "f1", "target": "nope", "relation": "dependency"}]),
        allow_edges=True,
    )
    with pytest.raises(EngineError, match="edge.target"):
        _resolve_edges(raw.edges, [], {}, board, intent_id="i1")


def test_resolve_edges_rejects_self_loops() -> None:
    board = _board(_fact("f1"))
    raw = parse_result(
        _reply(edges=[{"source": "f1", "target": "f1", "relation": "dependency"}]),
        allow_edges=True,
    )
    with pytest.raises(EngineError, match="self-loop"):
        _resolve_edges(raw.edges, [], {}, board, intent_id="i1")


# ------------------------------------------------------------- M2-2 verify pass


def _bootstrap_reply(*claims: str, edges: list[dict[str, object]] | None = None) -> str:
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
            "edges": edges or [],
            "intents": [],
            "complete": None,
        }
    )


def _reason_reply(*intents: dict[str, object]) -> str:
    return json.dumps({"facts": [], "intents": list(intents), "complete": None})


def _keep(*indexes: int) -> str:
    return json.dumps({"keep": list(indexes), "drop": []})


def _compare_reply(
    *,
    deviations: list[dict[str, object]] | None = None,
    edges: list[dict[str, object]] | None = None,
    gate: dict[str, str] | None = None,
) -> str:
    compare = {
        "key": "cmp",
        "label": "compare (facts x sources x goal)",
        "kind": "compare",
        "role": "none",
        "status": "verified",
        "confidence": 0.8,
    }
    return json.dumps(
        {
            "facts": [compare, *(deviations or [])],
            "edges": edges or [],
            "gate": gate,
            "intents": [],
            "complete": None,
        }
    )


def _source_fact(key: str = "s1") -> dict[str, object]:
    return {
        "key": key,
        "label": "primary source",
        "kind": "source",
        "role": "none",
        "status": "verified",
        "confidence": 0.9,
        "evidence": [
            {
                "quote": "55%",
                "sourceTitle": "Lab study",
                "url": "https://example.com/lab",
                "locator": "p.1",
            }
        ],
    }


def _run(store: RunStore, search: object, *replies: str) -> Engine:
    return Engine(
        worker=LocalWorker(model=_FakeModel(*replies)),
        search=search,  # type: ignore[arg-type]
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )


async def test_verify_pass_writes_compare_deviations_and_edges(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _run(
        store,
        _FakeSearch(),
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "verify", "from": "f1", "question": "Compare f1."}),
        _keep(0),
        _compare_reply(
            deviations=[_deviation_fact("dev1")],
            edges=[
                {"source": "f1", "target": "cmp", "relation": "dependency", "note": "verify"},
                {"source": "goal", "target": "dev1", "relation": "goal-derived", "note": "dev"},
            ],
        ),
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    kinds = [fact.kind for fact in board.facts]
    assert kinds.count("compare") == 1
    assert kinds.count("deviation") == 1
    relations = {(edge.source, edge.target, edge.relation) for edge in board.edges}
    assert ("f1", "p1", "dependency") in relations
    assert ("goal", "d1", "goal-derived") in relations


async def test_verify_pass_does_not_search(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    search = _RecordingSearch()
    engine = _run(
        store,
        search,
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "verify", "from": "f1", "question": "Compare f1."}),
        _keep(0),
        _compare_reply(),
    )
    await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
    assert search.queries == []


async def test_verify_gate_pauses_for_gate_b(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _run(
        store,
        _FakeSearch(),
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "verify", "from": "f1", "question": "Compare f1."}),
        _keep(0),
        _compare_reply(gate={"gate": "arbitrate", "question": "which source?"}),
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
    assert board.status == "awaiting_human"
    assert board.waitingFor is not None
    assert board.waitingFor.gate == "arbitrate"


async def test_verify_deviation_without_evidence_fails(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    bad = _deviation_fact("dev1")
    bad["evidence"] = []
    engine = _run(
        store,
        _FakeSearch(),
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "verify", "from": "f1", "question": "q"}),
        _keep(0),
        _compare_reply(deviations=[bad]),
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
    assert board.status == "failed"


async def test_verify_deviation_severity_status_mismatch_fails(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    bad = _deviation_fact("dev1", severity="high")
    bad["status"] = "review"  # high severity must be flagged
    engine = _run(
        store,
        _FakeSearch(),
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "verify", "from": "f1", "question": "q"}),
        _keep(0),
        _compare_reply(deviations=[bad]),
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
    assert board.status == "failed"


async def test_verify_without_a_compare_node_fails(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    reply = json.dumps(
        {
            "facts": [_deviation_fact("dev1")],
            "edges": [],
            "gate": None,
            "intents": [],
            "complete": None,
        }
    )
    engine = _run(
        store,
        _FakeSearch(),
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "verify", "from": "f1", "question": "q"}),
        _keep(0),
        reply,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
    assert board.status == "failed"


async def test_explore_pass_cannot_request_a_gate(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    reply = json.dumps(
        {
            "facts": [_source_fact()],
            "edges": [],
            "gate": {"gate": "arbitrate", "question": "q"},
            "intents": [],
            "complete": None,
        }
    )
    engine = _run(
        store,
        _FakeSearch(),
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "explore", "from": "f1", "question": "source it"}),
        _keep(0),
        reply,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
    assert board.status == "failed"


async def test_bootstrap_writes_main_chain_edge(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _run(
        store,
        _FakeSearch(),
        _bootstrap_reply(
            "A claim",
            edges=[{"source": "origin", "target": "c1", "relation": "main-chain", "note": "b"}],
        ),
        NO_REASON,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
    relations = {(edge.source, edge.target, edge.relation) for edge in board.edges}
    assert ("origin", "f1", "main-chain") in relations


# ------------------------------------------------------- M2-3 completion + report


def _sub_claim_fact() -> dict[str, object]:
    return {
        "label": "sub claim",
        "kind": "fact",
        "role": "sub-claim",
        "status": "open",
        "confidence": 0.5,
    }


def _complete_reply(verdict: str) -> str:
    return json.dumps({"facts": [], "intents": [], "complete": {"verdict": verdict}})


def _scored_run_replies() -> tuple[str, ...]:
    return (
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "decompose", "from": "f1", "question": "split"}),
        _keep(0),
        json.dumps({"facts": [_sub_claim_fact()], "intents": [], "complete": None}),
        _reason_reply({"type": "verify", "from": "f2", "question": "compare"}),
        _keep(0),
        _compare_reply(deviations=[_deviation_fact("dev1")]),
        _complete_reply("\u90e8\u5206\u504f\u5dee"),
    )


async def test_complete_writes_report_md(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _run(store, _FakeSearch(), *_scored_run_replies())
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status == "completed"
    report = store.report_path.read_text(encoding="utf-8")
    assert "\u90e8\u5206\u504f\u5dee" in report
    assert "d1" in report
    assert "high" in report


async def test_replay_does_not_write_a_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _run(store, _FakeSearch(), *_scored_run_replies())
    await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    # replay is read-only: it reproduces the board and never regenerates report.md.
    store.report_path.unlink()
    assert main(["replay", str(store.root)]) == 0
    capsys.readouterr()
    assert not store.report_path.exists()


async def test_scored_run_is_deterministic(tmp_path: Path) -> None:
    """The same scripted input yields the same DAG structure (SPEC M1 acceptance).

    Wall-clock fields (``createdAt`` / ``heartbeatAt``) differ between live runs, so the
    assertion is on the shape (fact/intent ids and edges), not a byte-for-byte render;
    ``replay`` of one event log stays byte-deterministic (covered by the fixture tests).
    """

    def structure(board: Board) -> dict[str, object]:
        return {
            "status": board.status,
            "verdict": board.verdict,
            "facts": [(fact.id, fact.kind, fact.role, fact.status) for fact in board.facts],
            "intents": [
                (intent.id, intent.type, intent.status, tuple(intent.producedFacts))
                for intent in board.intents
            ],
            "edges": sorted((edge.source, edge.target, edge.relation) for edge in board.edges),
        }

    async def run_once(name: str) -> dict[str, object]:
        store = RunStore(tmp_path / name)
        engine = _run(store, _FakeSearch(), *_scored_run_replies())
        board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
        return structure(board)

    assert await run_once("a") == await run_once("b")


# --------------------------------------------------------- M2 review hardening


def test_resolve_edges_rejects_a_key_that_shadows_a_fact_id() -> None:
    board = _board(_fact("f1"))
    raw = parse_result(
        _reply(facts=[_deviation_fact("f1")]), allow_edges=True
    )
    with pytest.raises(EngineError, match="shadows"):
        _resolve_edges(raw.edges, ["d1"], {"f1": "d1"}, board, intent_id="i1")


async def test_bootstrap_rejects_a_non_main_claim_fact(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    reply = json.dumps(
        {
            "facts": [{"label": "x", "kind": "fact", "role": "none", "status": "open"}],
            "intents": [],
            "complete": None,
        }
    )
    engine = _run(store, _FakeSearch(), reply)
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
    assert board.status == "failed"


async def test_validate_reply_must_not_carry_edges(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    bad_validate = json.dumps(
        {
            "keep": [0],
            "drop": [],
            "edges": [{"source": "a", "target": "b", "relation": "main-chain"}],
        }
    )
    engine = _run(
        store,
        _FakeSearch(),
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "decompose", "from": "f1", "question": "split"}),
        bad_validate,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
    assert board.status == "failed"


async def test_resume_approves_gate_b(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=LocalWorker(
            model=_FakeModel(
                _bootstrap_reply("A claim"),
                _reason_reply({"type": "verify", "from": "f1", "question": "compare"}),
                _keep(0),
                _compare_reply(gate={"gate": "arbitrate", "question": "which source?"}),
                NO_REASON,  # the resumed Reason proposes nothing
            )
        ),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=False,
    )
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))
    assert board.waitingFor is not None and board.waitingFor.gate == "confirm-claim"

    board = await engine.resume(decision="approve")
    assert board.status == "awaiting_human"
    assert board.waitingFor is not None and board.waitingFor.gate == "arbitrate"

    board = await engine.resume(decision="approve")
    # The resumed Reason proposes nothing, so the loop stops on a terminal dead-end.
    assert board.status == "stopped"


async def test_complete_without_deviations_writes_an_empty_scorecard(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    replies = (
        _bootstrap_reply("A claim"),
        _reason_reply({"type": "decompose", "from": "f1", "question": "split"}),
        _keep(0),
        json.dumps({"facts": [_sub_claim_fact()], "intents": [], "complete": None}),
        _reason_reply({"type": "verify", "from": "f2", "question": "compare"}),
        _keep(0),
        _compare_reply(),
        _complete_reply("clean"),
    )
    engine = _run(store, _FakeSearch(), *replies)
    board = await engine.run(origin=_fact("origin", "origin"), goal=_fact("goal", "goal"))

    assert board.status == "completed"
    report = store.report_path.read_text(encoding="utf-8")
    assert "findings: 0" in report
