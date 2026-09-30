from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import ModuleType

import pytest

from originweave.blackboard import Entity, EntityGraph, Relation
from originweave.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "examples" / "copilot_productivity"
RELATION_SAMPLE = REPO_ROOT / "examples" / "organization_relations"
BUILDER_PATH = REPO_ROOT / "scripts" / "build_sample_fixtures.py"


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_sample_fixtures", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_sample_fixtures"] = module
    spec.loader.exec_module(module)
    return module


def _read_board(
    capsys: pytest.CaptureFixture[str], sample: Path = SAMPLE
) -> dict[str, object]:
    assert main(["replay", str(sample), "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def _collapse(text: str) -> str:
    return " ".join(text.split())


def test_replay_reproduces_expected_board(capsys: pytest.CaptureFixture[str]) -> None:
    board = _read_board(capsys)
    assert board["status"] == "completed"
    assert board["verdict"] == "部分偏差"

    facts = {fact["id"]: fact for fact in board["facts"]}  # type: ignore[union-attr]
    assert facts["f1"]["role"] == "main-claim"
    assert {facts["f2"]["role"], facts["f3"]["role"], facts["f4"]["role"]} == {"sub-claim"}

    deviations = [fact for fact in facts.values() if fact["kind"] == "deviation"]
    assert {fact["id"] for fact in deviations} == {f"d{i}" for i in range(1, 7)}
    assert all(fact["evidence"] for fact in deviations)
    assert all(fact["subtitle"].startswith("severity=") for fact in deviations)

    edges = {(edge["source"], edge["target"], edge["relation"]) for edge in board["edges"]}  # type: ignore[union-attr]
    assert ("origin", "f1", "main-chain") in edges
    assert ("f1", "f2", "decomposes") in edges
    assert ("f2", "c1", "main-chain") in edges
    assert ("c1", "s1", "main-chain") in edges
    assert ("origin", "f1", "decomposes") not in edges
    assert all(source == "goal" for source, _, relation in edges if relation == "goal-derived")


def test_replay_is_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    first = json.dumps(_read_board(capsys), sort_keys=True)
    second = json.dumps(_read_board(capsys), sort_keys=True)
    assert first == second


def test_replay_is_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted during replay")

    monkeypatch.setattr(socket, "socket", _no_network)
    assert main(["replay", str(SAMPLE), "--json"]) == 0


def test_evidence_quotes_are_verbatim(capsys: pytest.CaptureFixture[str]) -> None:
    board = _read_board(capsys)
    manifest = json.loads((SAMPLE / "sources" / "manifest.json").read_text(encoding="utf-8"))
    snapshots = {
        entry["url"]: (SAMPLE / "sources" / entry["snapshot"]).read_text(encoding="utf-8")
        for entry in manifest["sources"]
    }
    document_url = json.loads((SAMPLE / "input" / "source.json").read_text(encoding="utf-8"))["url"]
    snapshots[document_url] = (SAMPLE / "input" / "document.md").read_text(encoding="utf-8")

    nodes = [board["origin"], board["goal"], *board["facts"]]  # type: ignore[misc]
    for node in nodes:
        for evidence in node["evidence"]:
            assert _collapse(evidence["quote"]) in _collapse(snapshots[evidence["url"]])


def test_fixture_gate_ids_match_frozen_contract() -> None:
    gates: set[str] = set()
    decisions: set[str] = set()
    lines = (SAMPLE / "events.jsonl").read_text(encoding="utf-8").splitlines()
    for line in lines:
        if not line.strip():
            continue
        event = json.loads(line)
        if event["type"] == "REQUEST_HUMAN":
            gates.add(event["payload"]["gate"])
        elif event["type"] == "HUMAN_INPUT":
            decisions.add(event["payload"]["decision"])
    # Gate ids and decisions are frozen in proto/originweave/v1/originweave.proto.
    assert gates <= {"confirm-claim", "arbitrate", "review"}
    assert decisions <= {"approve", "edit", "reject"}


def test_fixtures_are_up_to_date(tmp_path: Path) -> None:
    builder = _load_builder()
    for sample in builder.SAMPLES:
        target = tmp_path / sample.name
        builder.build(target, sample.events, entity_graph=sample.entity_graph)
        assert (target / "events.jsonl").read_bytes() == (
            sample.root / "events.jsonl"
        ).read_bytes()
        if sample.entity_graph:
            assert (target / "entity-graph.json").read_bytes() == (
                sample.root / "entity-graph.json"
            ).read_bytes()


def test_fixtures_check_passes(capsys: pytest.CaptureFixture[str]) -> None:
    builder = _load_builder()
    assert builder.main(["--check"]) == 0
    assert "fixtures are up to date" in capsys.readouterr().out


def test_fixtures_check_detects_a_stale_sample(tmp_path: Path) -> None:
    builder = _load_builder()
    target = tmp_path / "sample"
    builder.build(target)
    assert builder.main(["--check", "--root", str(target)]) == 0

    (target / "events.jsonl").write_text("{}\n", encoding="utf-8")

    assert builder.main(["--check", "--root", str(target)]) == 1


def test_fixtures_check_flags_an_obsolete_capabilities_dir(tmp_path: Path) -> None:
    builder = _load_builder()
    (tmp_path / "capabilities").mkdir()

    assert builder.main(["--check", "--root", str(tmp_path)]) == 1


# ---------------------------------------------------------------- organization_relations


def _snapshots() -> dict[str, str]:
    manifest = json.loads(
        (RELATION_SAMPLE / "sources" / "manifest.json").read_text(encoding="utf-8")
    )
    snapshots = {
        entry["url"]: (RELATION_SAMPLE / "sources" / entry["snapshot"]).read_text(encoding="utf-8")
        for entry in manifest["sources"]
    }
    document_url = json.loads(
        (RELATION_SAMPLE / "input" / "source.json").read_text(encoding="utf-8")
    )["url"]
    snapshots[document_url] = (RELATION_SAMPLE / "input" / "document.md").read_text(
        encoding="utf-8"
    )
    return snapshots


def test_relation_sample_replay_reproduces_the_graph(
    capsys: pytest.CaptureFixture[str],
) -> None:
    board = _read_board(capsys, RELATION_SAMPLE)
    assert board["status"] == "completed"
    assert board["verdict"] == "组织关系已判定"

    entities = {entity["id"]: entity for entity in board["entities"]}  # type: ignore[union-attr]
    assert set(entities) == {"n1", "n2", "n3", "n4"}
    assert entities["n1"]["name"] == "GitHub"
    assert entities["n1"]["aliases"] == ["GitHub, Inc."]
    assert all(entity["type"] == "organization" for entity in entities.values())

    relations = {relation["id"]: relation for relation in board["relations"]}  # type: ignore[union-attr]
    assert set(relations) == {"r1", "r2", "r3", "r4"}
    assert (relations["r1"]["source"], relations["r1"]["target"]) == ("n1", "n2")
    assert relations["r1"]["type"] == "partners-with"
    assert relations["r1"]["status"] == "verified"

    # A relation must be either sourced or explicitly inferred; ids must resolve.
    for relation in relations.values():
        assert relation["source"] in entities
        assert relation["target"] in entities
        assert relation["source"] != relation["target"]
        if relation["inferred"]:
            assert relation["status"] == "inferred"
            assert relation["evidence"] == []
            assert relation["confidence"] > 0
        else:
            assert relation["status"] == "verified"
            assert relation["evidence"]


def test_relation_sample_inferred_edge(capsys: pytest.CaptureFixture[str]) -> None:
    relations = {r["id"]: r for r in _read_board(capsys, RELATION_SAMPLE)["relations"]}  # type: ignore[union-attr]
    inferred = relations["r2"]
    assert inferred["type"] == "subsidiary-of"
    assert inferred["inferred"] is True
    assert inferred["status"] == "inferred"
    assert inferred["confidence"] == pytest.approx(0.55)
    assert inferred["evidence"] == []


def test_relation_evidence_quotes_are_verbatim(capsys: pytest.CaptureFixture[str]) -> None:
    board = _read_board(capsys, RELATION_SAMPLE)
    snapshots = _snapshots()
    for relation in board["relations"]:  # type: ignore[union-attr]
        for evidence in relation["evidence"]:
            assert _collapse(evidence["quote"]) in _collapse(snapshots[evidence["url"]])


def test_run_json_declares_relation_analysis() -> None:
    meta = json.loads((RELATION_SAMPLE / "run.json").read_text(encoding="utf-8"))
    assert meta["analysis"] == "relation"
    assert meta["id"] == "organization_relations"
    # run.json holds static metadata only; result fields are derived from the events.
    assert "status" not in meta
    assert "facts" not in meta


def test_entity_graph_json_matches_replay(capsys: pytest.CaptureFixture[str]) -> None:
    board_json = _read_board(capsys, RELATION_SAMPLE)
    stored = json.loads((RELATION_SAMPLE / "entity-graph.json").read_text(encoding="utf-8"))
    # Rebuild the derived artifact from the replayed board and compare (sort_keys stable).
    rebuilt = EntityGraph(
        entities=[Entity.from_dict(entity) for entity in board_json["entities"]],  # type: ignore[union-attr]
        relations=[
            Relation.from_dict(relation) for relation in board_json["relations"]  # type: ignore[union-attr]
        ],
    ).to_dict()
    assert stored == rebuilt
