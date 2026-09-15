"""Command line entry point.

M0 scaffold: subcommands are declared and wired but dispatch to placeholder
implementations. Real behaviour lands in the M0b-M4 sub-issues.
"""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version

FALLBACK_VERSION = "0.0.0"

_NOT_IMPLEMENTED = "originweave {command}: not implemented yet (M0 scaffold)"


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

    sub.add_parser("init", help="generate a default config")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    print(_NOT_IMPLEMENTED.format(command=args.command), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
