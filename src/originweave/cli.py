"""Command line entry point.

``init`` / ``capabilities list`` (M0b) and ``replay`` (M0c) are wired.
``ui`` / ``mcp`` and ``capabilities install-obscura`` remain placeholders until
later milestones. A run is started through the server / proto API, not the CLI
(see ``docs/overview/product-overview.md`` section 5).
"""

from __future__ import annotations

import argparse
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import config
from .capabilities import ENV_VARS, LANGFUSE_ENV_VARS, PROMPT_PROVIDERS, SEARCH_PROVIDERS
from .model import ModelError
from .reduce import ReduceError, reduce, render_canonical, render_summary
from .store import RunStore

FALLBACK_VERSION = "0.0.0"

_NOT_IMPLEMENTED = "originweave {command}: not implemented yet"


def _version() -> str:
    try:
        return version("originweave")
    except PackageNotFoundError:
        return FALLBACK_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="originweave", description=__doc__)
    parser.add_argument("--version", action="version", version=_version())
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    ui = sub.add_parser("ui", help="serve the read-only run view")
    ui.add_argument("--run", default=None)
    ui.add_argument("--port", type=int, default=8765)

    replay = sub.add_parser("replay", help="replay a run directory")
    replay.add_argument("run_dir")
    replay.add_argument("--json", action="store_true", help="emit the canonical board as JSON")

    capabilities = sub.add_parser("capabilities", help="inspect or install capabilities")
    capabilities.add_argument("action", choices=["list", "install-obscura"])

    mcp = sub.add_parser("mcp", help="expose capabilities over MCP")
    mcp.add_argument("--run", default=None)

    init = sub.add_parser("init", help="generate a default config")
    init.add_argument("--force", action="store_true", help="overwrite an existing config")

    return parser


def _cmd_init(args: argparse.Namespace) -> int:
    try:
        path = config.write_default(force=bool(args.force))
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"wrote {path}")
    return 0


def _cmd_capabilities(args: argparse.Namespace) -> int:
    if args.action != "list":
        print(_NOT_IMPLEMENTED.format(command=f"capabilities {args.action}"), file=sys.stderr)
        return 0

    try:
        cfg = config.load()
    except config.ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    source = "found" if Path(config.CONFIG_FILENAME).is_file() else "defaults"
    print(f"config: {config.CONFIG_FILENAME} ({source})")

    print("search:")
    for name in sorted(SEARCH_PROVIDERS):
        env = ENV_VARS[name]
        state = "ready" if os.environ.get(env) else f"missing {env}"
        mark = "*" if name == cfg.capability.search.provider else " "
        print(f" {mark} {name:<9} {state}")

    print("prompt:")
    for name in sorted(PROMPT_PROVIDERS):
        if name == "local":
            state = f"dir={cfg.capability.prompt.directory}"
        else:
            missing = [var for var in LANGFUSE_ENV_VARS if not os.environ.get(var)]
            state = "ready" if not missing else "missing " + ", ".join(missing)
        mark = "*" if name == cfg.capability.prompt.provider else " "
        print(f" {mark} {name:<9} {state}")

    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    store = RunStore(Path(args.run_dir))
    if not store.events_path.is_file():
        print(f"no event log at {store.events_path}", file=sys.stderr)
        return 1
    try:
        board = reduce(store.read_events())
    except (ModelError, ReduceError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    sys.stdout.write(render_canonical(board) if args.json else render_summary(board))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "capabilities":
        return _cmd_capabilities(args)
    if args.command == "replay":
        return _cmd_replay(args)
    print(_NOT_IMPLEMENTED.format(command=args.command), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
