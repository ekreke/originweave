from __future__ import annotations

from pathlib import Path

import pytest

import originweave
from originweave.cli import build_parser, main


def test_version_is_available() -> None:
    assert isinstance(originweave.__version__, str)
    assert originweave.__version__


def test_parser_builds() -> None:
    parser = build_parser()
    assert parser.prog == "originweave"


def test_no_command_prints_help() -> None:
    assert main([]) == 0


def test_unimplemented_subcommand_returns_zero() -> None:
    assert main(["mcp"]) == 0


def test_init_writes_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    assert (tmp_path / "originweave.toml").is_file()
    assert main(["init"]) == 1
    assert main(["init", "--force"]) == 0


def test_capabilities_list_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["capabilities", "list"]) == 0
