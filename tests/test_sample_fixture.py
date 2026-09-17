from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import ModuleType

import pytest

from originweave.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "examples" / "copilot_productivity"
BUILDER_PATH = REPO_ROOT / "scripts" / "build_sample_fixtures.py"


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_sample_fixtures", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_sample_fixtures"] = module
    spec.loader.exec_module(module)
    return module


def _read_board(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    assert main(["replay", str(SAMPLE), "--json"]) == 0
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


def test_fixtures_are_up_to_date(tmp_path: Path) -> None:
    builder = _load_builder()
    builder.build(tmp_path / "sample")
    assert (tmp_path / "sample" / "events.jsonl").read_bytes() == (
        SAMPLE / "events.jsonl"
    ).read_bytes()
