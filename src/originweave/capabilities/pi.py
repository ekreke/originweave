"""Pi-backed Worker implementation for isolated agent sessions (M6 P2)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from pi_py_sdk import (
    AgentStartEvent,
    Event,
    MessageUpdateEvent,
    PiAgent,
    PiConfig,
    PiError,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    TurnEndEvent,
)

from ..blackboard import Board
from ..config import ModelConfig
from .base import MissingCredentialError, PromptTemplate, ProviderError, ProviderUnavailableError
from .model import BASE_URL_ENV_VAR, ENV_VAR
from .worker import TaskKind, WorkerReply, WorkerStep, render_messages

_PI_PROVIDER = "originweave-openai"
_PI_PACKAGE_NAME = "@earendil-works/pi-coding-agent"
_PI_BUILTIN_TOOLS: frozenset[str] = frozenset(
    {"read", "bash", "edit", "write", "grep", "find", "ls"}
)
# The TS extension the ``search`` tool lives in (packaged as package data).
_EXTENSION_NAME = "search.ts"
_AGENT_DIR_ENV_SUFFIX = "_CODING_AGENT_DIR"
# Upstream/default Pi agent-config-dir variable; a rebranded build uses another name.
_DEFAULT_AGENT_DIR_ENV = "PI_CODING_AGENT_DIR"
# Where the Pi TS ``search`` extension calls back the originweave server (M6 P4).
SERVER_URL_ENV = "ORIGINWEAVE_SERVER_URL"
DEFAULT_SERVER_URL = "http://127.0.0.1:8765"


class PiAgentClient(Protocol):
    """The subset of :class:`pi_py_sdk.PiAgent` used by :class:`PiWorker`."""

    async def __aenter__(self) -> PiAgentClient: ...

    async def __aexit__(self, *exc: object) -> None: ...

    def prompt_stream(self, message: str) -> AsyncIterator[Event]: ...

    async def get_last_assistant_text(self) -> str | None: ...


PiAgentFactory = Callable[[PiConfig], PiAgentClient]


def _make_pi_agent(config: PiConfig) -> PiAgent:
    return PiAgent(config=config)


def _require_runtime() -> None:
    """Reject implicit npx installation; live runs require explicit Node and Pi."""
    missing = [name for name in ("node", "pi") if shutil.which(name) is None]
    if missing:
        names = ", ".join(missing)
        raise ProviderUnavailableError(
            f"Pi worker requires {names} on PATH. Install Node.js from https://nodejs.org "
            "and Pi with `npm i -g @earendil-works/pi-coding-agent`."
        )


def _is_pi_package(package: Mapping[str, Any]) -> bool:
    """True when a ``package.json`` is the Pi coding agent (not an unrelated ancestor).

    A Pi package declares ``piConfig.configDir`` (legacy ``n.configDir``) or carries the
    upstream package name; a random ancestor that merely happens to have a ``piConfig``
    field is rejected.
    """
    if package.get("name") == _PI_PACKAGE_NAME:
        return True
    for key in ("piConfig", "n"):
        section = package.get(key)
        if isinstance(section, dict) and "configDir" in section:
            return True
    return False


def _pi_package_json(bin: str | None = None) -> dict[str, Any] | None:
    """Read the ``pi`` package's own ``package.json`` (``None`` when unresolvable).

    Only a Pi-looking package is accepted, so an unrelated ``package.json`` higher up
    the tree cannot hijack the name. Shim installs (pnpm/npx/Windows ``.cmd``) resolve
    to a script rather than into the package, so no file is found and the caller falls
    back to the upstream variable name.
    """
    resolved = shutil.which(bin or "pi")
    if resolved is None:
        return None
    for parent in Path(resolved).resolve().parents:
        candidate = parent / "package.json"
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # ValueError covers JSONDecodeError/UnicodeDecodeError
            continue
        if isinstance(data, dict) and _is_pi_package(data):
            return data
    return None


def resolve_agent_dir_env_name(bin: str | None = None) -> str:
    """Derive Pi's agent-config-dir env var name for the resolved ``pi`` binary.

    Pi names the variable after ``piConfig.name`` (legacy ``n.name``) in its
    ``package.json``; a rebranded build (e.g. ``"ekreke"``) reads
    ``EKREKE_CODING_AGENT_DIR`` instead of hard-coding ``PI_CODING_AGENT_DIR``. Falls
    back to the upstream name when the binary is a shim/npx install with no local Pi
    metadata (or exposes no name).
    """
    package = _pi_package_json(bin)
    name = ""
    if package is not None:
        for key in ("piConfig", "n"):
            section = package.get(key)
            if isinstance(section, dict) and isinstance(section.get("name"), str):
                name = section["name"]
                if name:
                    break
    return f"{(name or 'pi').upper()}{_AGENT_DIR_ENV_SUFFIX}"


def _extension_path() -> Path:
    """The packaged ``search`` TS extension (package data, fixed known path)."""
    return Path(__file__).resolve().parent.parent / "pi_extensions" / _EXTENSION_NAME


def _render_value(value: Any) -> str:
    """Make a readable, lossless-enough step payload without assuming Pi event shapes."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class PiWorker:
    """Run one Worker task in a fresh, ephemeral Pi RPC session."""

    name = "pi"

    def __init__(
        self,
        *,
        model: ModelConfig,
        tools: tuple[str, ...],
        cwd: Path | None = None,
        extension_path: Path | None = None,
        agent_factory: PiAgentFactory = _make_pi_agent,
        runtime_checker: Callable[[], None] = _require_runtime,
    ) -> None:
        self._model = model
        self._tools = tools
        self._cwd = (Path.cwd() if cwd is None else cwd).resolve()
        self._extension_path = (
            Path(extension_path) if extension_path is not None else _extension_path()
        )
        self._agent_factory = agent_factory
        self._runtime_checker = runtime_checker

    @property
    def model(self) -> str:
        return self._model.model

    @property
    def tools(self) -> frozenset[str]:
        """The configured tool allowlist (the engine uses this to pick who searches)."""
        return frozenset(self._tools)

    def _endpoint(self) -> str:
        endpoint = (os.environ.get(BASE_URL_ENV_VAR) or self._model.base_url).rstrip("/")
        if not endpoint:
            raise MissingCredentialError(f"{BASE_URL_ENV_VAR} is not set")
        return endpoint

    def _server_url(self) -> str:
        return (os.environ.get(SERVER_URL_ENV) or DEFAULT_SERVER_URL).rstrip("/")

    def _tools_args(self) -> list[str]:
        tools = [tool for tool in self._tools if tool in _PI_BUILTIN_TOOLS or tool == "search"]
        return ["--no-tools"] if not tools else ["--tools", ",".join(tools)]

    def _extension_args(self) -> list[str]:
        if "search" not in self._tools:
            return []
        return ["-e", str(self._extension_path)]

    def _pi_config(self, *, config_dir: str, template: PromptTemplate) -> PiConfig:
        return PiConfig(
            provider=_PI_PROVIDER,
            model=self._model.model,
            cwd=str(self._cwd),
            env={
                resolve_agent_dir_env_name(): config_dir,
                # Belt-and-braces for the upstream/npx fallback where the name is "pi".
                _DEFAULT_AGENT_DIR_ENV: config_dir,
                SERVER_URL_ENV: self._server_url(),
            },
            no_session=True,
            extra_args=[
                "--no-extensions",
                *self._extension_args(),
                "--no-skills",
                "--no-context-files",
                "--system-prompt",
                template.text,
                *self._tools_args(),
            ],
        )

    def _write_models_config(self, config_dir: str) -> None:
        payload = {
            "providers": {
                _PI_PROVIDER: {
                    "baseUrl": self._endpoint(),
                    "api": "openai-completions",
                    "apiKey": f"${ENV_VAR}",
                    "authHeader": True,
                    "models": [{"id": self._model.model}],
                }
            }
        }
        path = Path(config_dir) / "models.json"
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    async def run(
        self,
        task: TaskKind,
        template: PromptTemplate,
        board: Board,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> WorkerReply:
        if not os.environ.get(ENV_VAR):
            raise MissingCredentialError(f"{ENV_VAR} is not set")
        self._runtime_checker()
        messages = render_messages(task, template, board, extra=extra)
        steps: list[WorkerStep] = []

        try:
            with tempfile.TemporaryDirectory(prefix="originweave-pi-") as config_dir:
                self._write_models_config(config_dir)
                pi_config = self._pi_config(config_dir=config_dir, template=template)
                agent = self._agent_factory(pi_config)
                async with agent:
                    async for event in agent.prompt_stream(messages[1].content):
                        self._append_step(steps, event)
                    text = await agent.get_last_assistant_text()
        except PiError as exc:
            raise ProviderError(f"Pi worker failed: {exc}") from exc

        if text is None:
            raise ProviderError("Pi worker completed without an assistant response")
        return WorkerReply(
            text=text,
            input={"system": messages[0].content, "user": messages[1].content},
            steps=steps,
        )

    @staticmethod
    def _append_step(steps: list[WorkerStep], event: Event) -> None:
        """Project Pi RPC lifecycle events onto the stable WorkerStep contract."""

        def append(kind: str, *, name: str = "", text: str = "", ok: bool | None = None) -> None:
            steps.append(WorkerStep(seq=len(steps) + 1, kind=kind, name=name, text=text, ok=ok))

        if isinstance(event, AgentStartEvent):
            append("turn-start")
        elif isinstance(event, MessageUpdateEvent):
            update = event.assistantMessageEvent
            if update is not None and update.type == "text_delta" and update.delta:
                append("message", text=update.delta)
        elif isinstance(event, ToolExecutionStartEvent):
            append("tool-call", name=event.toolName or "", text=_render_value(event.args))
        elif isinstance(event, ToolExecutionEndEvent):
            append(
                "tool-result",
                name=event.toolName or "",
                text=_render_value(event.result),
                ok=not event.isError,
            )
        elif isinstance(event, TurnEndEvent):
            append("turn-end")


__all__ = [
    "DEFAULT_SERVER_URL",
    "SERVER_URL_ENV",
    "PiAgentClient",
    "PiAgentFactory",
    "PiWorker",
    "resolve_agent_dir_env_name",
]
