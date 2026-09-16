from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from originweave.cli import main
from originweave.store import RunStore

ORIGIN = {"id": "origin", "kind": "origin", "label": "资料 A"}
GOAL = {"id": "goal", "kind": "goal", "label": "停止条件"}


def seed(tmp_path: Path) -> Path:
    store = RunStore(tmp_path / "run_001")
    store.init_layout()
    store.append_event("PROJECT", {"origin": ORIGIN, "goal": GOAL}, at="t1")
    store.append_event("INTENT", {"intent": {"id": "i001", "type": "explore"}}, at="t2")
    store.append_event(
        "CONCLUDE", {"intentId": "i001", "facts": [{"id": "s1", "kind": "source"}]}, at="t3"
    )
    store.append_event("COMPLETE", {"verdict": "部分偏差"}, at="t4")
    return store.root


def test_replay_prints_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = seed(tmp_path)
    assert main(["replay", str(root)]) == 0
    out = capsys.readouterr().out
    assert "status: completed" in out
    assert "verdict: 部分偏差" in out


def test_replay_json_is_canonical(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = seed(tmp_path)
    assert main(["replay", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "completed"
    assert data["intents"][0]["id"] == "i001"
    assert data["verdict"] == "部分偏差"
    assert data["goal"]["kind"] == "goal"


def test_replay_missing_run_dir_returns_error(tmp_path: Path) -> None:
    assert main(["replay", str(tmp_path / "absent")]) == 1


def test_replay_is_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = seed(tmp_path)

    def _no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted during replay")

    monkeypatch.setattr(socket, "socket", _no_network)
    assert main(["replay", str(root), "--json"]) == 0


def test_replay_is_deterministic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = seed(tmp_path)
    assert main(["replay", str(root), "--json"]) == 0
    first = capsys.readouterr().out
    assert main(["replay", str(root), "--json"]) == 0
    assert capsys.readouterr().out == first
