"""Command line entry point.

``init`` / ``capabilities list`` (M0b), ``replay`` (M0c) and ``ui`` (M1c-1 C4) are
wired. ``mcp`` and ``capabilities install-obscura`` remain placeholders until later
milestones. A run is started through the server / proto API, not the CLI (see
``docs/overview/product-overview.md`` section 5).
"""

from __future__ import annotations

import argparse
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import config
from .blackboard import BlackboardError
from .capabilities import (
    ENV_VARS,
    LANGFUSE_ENV_VARS,
    MODEL_PROVIDERS,
    PROMPT_PROVIDERS,
    SEARCH_PROVIDERS,
    WORKER_PROVIDERS,
)
from .capabilities.model import BASE_URL_ENV_VAR as OPENAI_BASE_URL_ENV
from .capabilities.model import ENV_VAR as OPENAI_ENV_VAR
from .reduce import ReduceError, reduce, render_canonical, render_summary
from .store import open_run_store, run_has_events

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

    ui = sub.add_parser("ui", help="serve the run view (read-only with --run)")
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
        state = "free endpoint" + (f" · {env} set" if os.environ.get(env) else f" · {env} optional")
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

    model_cfg = cfg.capability.model
    print("model:")
    for name in sorted(MODEL_PROVIDERS):
        key = "set" if os.environ.get(OPENAI_ENV_VAR) else "not set"
        base = "set" if os.environ.get(OPENAI_BASE_URL_ENV) else "unset"
        mark = "*" if name == model_cfg.provider else " "
        print(
            f" {mark} {name:<9} model={model_cfg.model}"
            f" · {OPENAI_BASE_URL_ENV} {base} · {OPENAI_ENV_VAR} {key}"
        )

    worker_cfg = cfg.worker
    print("worker:")
    for name in sorted(WORKER_PROVIDERS):
        tools = ", ".join(worker_cfg.tools) if worker_cfg.tools else "none"
        mark = "*" if name == worker_cfg.provider else " "
        print(f" {mark} {name:<9} max_concurrency={worker_cfg.max_concurrency} · tools={tools}")

    return 0


def _cmd_ui(args: argparse.Namespace) -> int:
    """Serve the read-only run view (Connect API + built frontend; M1c-1 C4)."""
    try:
        cfg = config.load()
    except config.ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Imported lazily: the server pulls in the generated ``originweave.v1`` package,
    # which does not exist until ``make proto`` has run.
    from .server.app import create_app

    root = Path.cwd()
    run_dir = Path(args.run) if args.run else None
    if run_dir is not None and not run_has_events(run_dir, db_path=root / cfg.storage.db):
        print(f"no event log for {run_dir}", file=sys.stderr)
        return 1
    static_dir = root / "frontend" / "dist"
    if not static_dir.is_dir():
        print(f"note: {static_dir} not found; serving the API only", file=sys.stderr)

    host = "127.0.0.1"
    # The Pi search extension (M6 P4) calls back this server's Search RPC; point it at
    # the actual port unless the operator set an explicit override.
    os.environ.setdefault("ORIGINWEAVE_SERVER_URL", f"http://{host}:{args.port}")
    app = create_app(config=cfg, root=root, run_dir=run_dir, static_dir=static_dir)

    suffix = f" (single run {run_dir})" if run_dir is not None else ""
    print(f"originweave ui on http://{host}:{args.port}{suffix}")

    import uvicorn

    uvicorn.run(app, host=host, port=args.port, log_level="info")
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    try:
        cfg = config.load()
    except config.ConfigError:
        cfg = config.Config()
    store = open_run_store(run_dir, db_path=Path.cwd() / cfg.storage.db)
    if not store.has_events():
        print(f"no event log for {run_dir}", file=sys.stderr)
        return 1
    try:
        board = reduce(store.read_events())
    except (BlackboardError, ReduceError) as exc:
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
    if args.command == "ui":
        return _cmd_ui(args)
    print(_NOT_IMPLEMENTED.format(command=args.command), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
