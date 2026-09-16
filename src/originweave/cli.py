"""Command line entry point.

M0b wires ``init`` and ``capabilities list``. ``trace`` / ``ui`` / ``replay`` /
``mcp`` and ``capabilities install-obscura`` remain placeholders until later
milestones.
"""

from __future__ import annotations

import argparse
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import config
from .capabilities import ENV_VARS, LANGFUSE_ENV_VARS, PROMPT_PROVIDERS, SEARCH_PROVIDERS

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

    trace = sub.add_parser("trace", help="trace a document A back to its sources")
    trace.add_argument("target", help="URL or file path of document A")
    trace.add_argument("--out", default="report.md")
    trace.add_argument("--run", default=None)
    trace.add_argument("--provider", choices=["exa", "parallel"], default=None)
    trace.add_argument("--prompt-provider", choices=["local", "langfuse"], default=None)
    trace.add_argument("--max-steps", type=int, default=None)
    trace.add_argument("--max-wall", default=None)
    trace.add_argument("--max-cost", type=float, default=None)
    trace.add_argument("--auto", action="store_true", help="full auto; skip HITL gates")
    trace.add_argument("--json", action="store_true")

    ui = sub.add_parser("ui", help="serve the read-only run view")
    ui.add_argument("--run", default=None)
    ui.add_argument("--port", type=int, default=8765)

    replay = sub.add_parser("replay", help="replay a run directory")
    replay.add_argument("run_dir")

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
    print(_NOT_IMPLEMENTED.format(command=args.command), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
