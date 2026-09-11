from __future__ import annotations

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


def test_subcommand_is_a_stub() -> None:
    assert main(["init"]) == 0
    assert main(["capabilities", "list"]) == 0
