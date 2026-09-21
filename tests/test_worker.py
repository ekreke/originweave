from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from pi_py_sdk import (
    AgentStartEvent,
    AssistantMessageEvent,
    MessageUpdateEvent,
    PiProcessError,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    TurnEndEvent,
)

from originweave import config
from originweave.blackboard import Fact
from originweave.capabilities import PiWorker, ProviderUnavailableError, build_worker
from originweave.capabilities.base import MissingCredentialError, PromptTemplate, ProviderError
from originweave.capabilities.model import ChatMessage
from originweave.capabilities.pi import PiAgentClient, resolve_agent_dir_env_name
from originweave.capabilities.worker import (
    STEP_TEXT_LIMIT,
    LocalWorker,
    Worker,
    WorkerReply,
    WorkerStep,
    render_messages,
)
from originweave.engine import Engine
from originweave.reduce import reduce, render_canonical
from originweave.store import RunStore


class _FakeModel:
    name = "fake"

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.calls: list[list[ChatMessage]] = []

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        # Once scripted replies run out, a no-op Reason lets the I6 loop terminate.
        if self._replies:
            return self._replies.pop(0)
        return json.dumps({"facts": [], "intents": [], "complete": None})


class _FakeSearch:
    name = "fake"

    async def search(self, query: str, *, num_results: int = 8) -> str:
        return ""


class _FakePrompt:
    name = "fake"

    async def get(self, name: str) -> PromptTemplate:
        return PromptTemplate(name=name, text=name.upper())


def _origin() -> Fact:
    return Fact.from_dict({"id": "origin", "kind": "origin", "label": "Document A"})


def _goal() -> Fact:
    return Fact.from_dict({"id": "goal", "kind": "goal", "label": "Sourced"})


_BOOTSTRAP = json.dumps(
    {
        "facts": [{"label": "A claim", "kind": "fact", "role": "main-claim", "status": "open"}],
        "intents": [],
        "complete": None,
    }
)
_NO_REASON = json.dumps({"facts": [], "intents": [], "complete": None})


def _engine(store: RunStore, *replies: str) -> Engine:
    return Engine(
        worker=LocalWorker(model=_FakeModel(*replies)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )


async def test_local_worker_returns_reply_and_raw_input(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    await _engine(store, _BOOTSTRAP, _NO_REASON).run(origin=_origin(), goal=_goal())
    board = reduce(store.read_events())

    worker = LocalWorker(model=_FakeModel('{"facts": [], "intents": [], "complete": null}'))
    template = PromptTemplate(name="bootstrap", text="SYSTEM PROMPT")
    reply = await worker.run("Bootstrap", template, board)

    assert worker.name == "local"
    assert reply.text == '{"facts": [], "intents": [], "complete": null}'
    assert reply.steps == []
    assert reply.input["system"] == "SYSTEM PROMPT"
    assert '"board"' in reply.input["user"]


async def test_render_messages_is_deterministic(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    await _engine(store, _BOOTSTRAP, _NO_REASON).run(origin=_origin(), goal=_goal())
    board = reduce(store.read_events())

    template = PromptTemplate(name="reason", text="SYS")
    first = render_messages("Reason", template, board, extra={"candidates": [{"index": 0}]})
    second = render_messages("Reason", template, board, extra={"candidates": [{"index": 0}]})
    assert [m.content for m in first] == [m.content for m in second]
    assert first[0].role == "system"
    assert '"candidates"' in first[1].content


async def test_engine_persists_session_snapshot(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(store, _BOOTSTRAP, _NO_REASON).run(origin=_origin(), goal=_goal())

    session_path = store.sessions_dir / "sess_001.json"
    assert session_path.is_file()
    session = json.loads(session_path.read_text(encoding="utf-8"))
    assert session["id"] == "sess_001"
    assert session["task"] == "Bootstrap"
    assert session["intentId"] == "i1"
    assert session["worker"] == "worker-1"
    assert session["output"] == _BOOTSTRAP
    assert session["input"]["system"] == "BOOTSTRAP"
    assert session["steps"] == []
    # Both worker calls produced a session snapshot, in order.
    assert (store.sessions_dir / "sess_002.json").is_file()

    # Session events are an index only: dropping them yields the identical board.
    events = store.read_events()
    stripped = [event for event in events if event.type not in {"SESSION", "WORKER_STEP"}]
    assert render_canonical(board) == render_canonical(reduce(stripped))
    assert not any(event.type == "WORKER_STEP" for event in events)


def test_build_worker_defaults_to_pi() -> None:
    assert isinstance(build_worker(config.Config()), PiWorker)


def test_build_worker_explicit_local() -> None:
    cfg = config.Config(worker=config.WorkerConfig(provider="local"))
    assert isinstance(build_worker(cfg), LocalWorker)


def test_build_worker_explicit_pi() -> None:
    cfg = config.Config(worker=config.WorkerConfig(provider="pi"))
    assert isinstance(build_worker(cfg), PiWorker)


def test_worker_step_truncates_event_text_not_snapshot() -> None:
    step = WorkerStep(seq=1, kind="tool-result", name="search", text="x" * (STEP_TEXT_LIMIT + 50))
    payload = step.to_dict()
    assert len(payload["text"]) == STEP_TEXT_LIMIT
    full = step.to_session_dict()
    assert len(full["text"]) == STEP_TEXT_LIMIT + 50


# --------------------------------------------------------------- fake workers


class _FakePiAgent:
    """An in-memory Pi session used to test PiWorker without Node or Pi."""

    def __init__(self, events: list[object], text: str | None = _BOOTSTRAP) -> None:
        self._events = events
        self._text = text
        self.entered = False
        self.exited = False
        self.prompt: str | None = None

    async def __aenter__(self) -> PiAgentClient:
        self.entered = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.exited = True

    async def prompt_stream(self, message: str):
        self.prompt = message
        for event in self._events:
            yield event

    async def get_last_assistant_text(self) -> str | None:
        return self._text


class _FakePiFactory:
    def __init__(self, agent: _FakePiAgent) -> None:
        self.agent = agent
        self.configs: list[object] = []
        self.models: list[dict[str, object]] = []

    def __call__(self, pi_config: object) -> PiAgentClient:
        from pi_py_sdk import PiConfig

        assert isinstance(pi_config, PiConfig)
        self.configs.append(pi_config)
        config_dir = Path(pi_config.env["PI_CODING_AGENT_DIR"])
        self.models.append(json.loads((config_dir / "models.json").read_text(encoding="utf-8")))
        return self.agent


async def _board(tmp_path: Path):
    store = RunStore(tmp_path / "run_001")
    await _engine(store, _BOOTSTRAP, _NO_REASON).run(origin=_origin(), goal=_goal())
    return reduce(store.read_events())


async def test_pi_worker_maps_session_and_tool_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    events = [
        AgentStartEvent(type="agent_start"),
        MessageUpdateEvent(
            type="message_update",
            assistantMessageEvent=AssistantMessageEvent(type="text_delta", delta="hello"),
        ),
        ToolExecutionStartEvent(type="tool_execution_start", toolName="read", args={"path": "a"}),
        ToolExecutionEndEvent(
            type="tool_execution_end", toolName="read", result={"text": "ok"}, isError=False
        ),
        TurnEndEvent(type="turn_end"),
    ]
    agent = _FakePiAgent(events, text='{"facts": [], "intents": [], "complete": null}')
    factory = _FakePiFactory(agent)
    worker = PiWorker(
        model=config.ModelConfig(model="test-model", base_url="https://model.example/v1"),
        tools=("read",),
        cwd=tmp_path,
        agent_factory=factory,
        runtime_checker=lambda: None,
    )

    reply = await worker.run(
        "Bootstrap", PromptTemplate(name="bootstrap", text="SYSTEM"), await _board(tmp_path)
    )

    assert reply.text == '{"facts": [], "intents": [], "complete": null}'
    assert reply.input["system"] == "SYSTEM"
    assert agent.entered and agent.exited
    assert [step.kind for step in reply.steps] == [
        "turn-start",
        "message",
        "tool-call",
        "tool-result",
        "turn-end",
    ]
    assert reply.steps[1].text == "hello"
    assert reply.steps[2].name == "read"
    assert reply.steps[3].ok is True
    pi_config = factory.configs[0]
    assert pi_config.provider == "originweave-openai"
    assert pi_config.model == "test-model"
    assert pi_config.cwd == str(tmp_path.resolve())
    assert pi_config.no_session is True
    assert "--tools" in pi_config.extra_args
    assert "read" in pi_config.extra_args
    assert "--no-context-files" in pi_config.extra_args
    provider = factory.models[0]["providers"]["originweave-openai"]
    assert provider["baseUrl"] == "https://model.example/v1"
    assert provider["apiKey"] == "$OPENAI_API_KEY"


def _text_delta(delta: str) -> MessageUpdateEvent:
    return MessageUpdateEvent(
        type="message_update",
        assistantMessageEvent=AssistantMessageEvent(type="text_delta", delta=delta),
    )


async def test_pi_worker_folds_streaming_deltas_into_one_message_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    events = [
        AgentStartEvent(type="agent_start"),
        _text_delta("hel"),
        _text_delta("lo"),
        _text_delta(" "),
        _text_delta("world"),
        TurnEndEvent(type="turn_end"),
    ]
    agent = _FakePiAgent(events, text="hello world")
    worker = PiWorker(
        model=config.ModelConfig(model="test-model", base_url="https://model.example/v1"),
        tools=(),
        cwd=tmp_path,
        agent_factory=_FakePiFactory(agent),
        runtime_checker=lambda: None,
    )

    reply = await worker.run(
        "Bootstrap", PromptTemplate(name="bootstrap", text="SYSTEM"), await _board(tmp_path)
    )

    assert [step.kind for step in reply.steps] == ["turn-start", "message", "turn-end"]
    message = reply.steps[1]
    assert message.text == "hello world"
    assert message.seq == 2


async def test_pi_worker_splits_message_steps_around_tool_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    events = [
        AgentStartEvent(type="agent_start"),
        _text_delta("think"),
        _text_delta("ing"),
        ToolExecutionStartEvent(type="tool_execution_start", toolName="read", args={"path": "a"}),
        _text_delta("after"),
        _text_delta(" tool"),
        TurnEndEvent(type="turn_end"),
    ]
    agent = _FakePiAgent(events, text="thinkingafter tool")
    worker = PiWorker(
        model=config.ModelConfig(model="test-model", base_url="https://model.example/v1"),
        tools=("read",),
        cwd=tmp_path,
        agent_factory=_FakePiFactory(agent),
        runtime_checker=lambda: None,
    )

    reply = await worker.run(
        "Bootstrap", PromptTemplate(name="bootstrap", text="SYSTEM"), await _board(tmp_path)
    )

    assert [step.kind for step in reply.steps] == [
        "turn-start",
        "message",
        "tool-call",
        "message",
        "turn-end",
    ]
    assert reply.steps[1].text == "thinking"
    assert reply.steps[3].text == "after tool"


async def test_pi_worker_keeps_message_steps_separate_across_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    events = [
        AgentStartEvent(type="agent_start"),
        _text_delta("first"),
        TurnEndEvent(type="turn_end"),
        _text_delta("second"),
        TurnEndEvent(type="turn_end"),
    ]
    agent = _FakePiAgent(events, text="firstsecond")
    worker = PiWorker(
        model=config.ModelConfig(model="test-model", base_url="https://model.example/v1"),
        tools=(),
        cwd=tmp_path,
        agent_factory=_FakePiFactory(agent),
        runtime_checker=lambda: None,
    )

    reply = await worker.run(
        "Bootstrap", PromptTemplate(name="bootstrap", text="SYSTEM"), await _board(tmp_path)
    )

    assert [step.kind for step in reply.steps] == [
        "turn-start",
        "message",
        "turn-end",
        "message",
        "turn-end",
    ]
    assert [step.text for step in reply.steps if step.kind == "message"] == ["first", "second"]
    assert [step.seq for step in reply.steps] == [1, 2, 3, 4, 5]


async def test_pi_worker_disables_tools_when_none_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    agent = _FakePiAgent([])
    factory = _FakePiFactory(agent)
    worker = PiWorker(
        model=config.ModelConfig(base_url="https://model.example/v1"),
        tools=(),
        agent_factory=factory,
        runtime_checker=lambda: None,
    )

    await worker.run("Reason", PromptTemplate(name="reason", text="SYSTEM"), await _board(tmp_path))

    assert "--no-tools" in factory.configs[0].extra_args


async def test_pi_worker_wires_the_search_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ORIGINWEAVE_SERVER_URL", "http://server.example:8765/")
    agent = _FakePiAgent([])
    factory = _FakePiFactory(agent)
    extension = tmp_path / "search.ts"
    worker = PiWorker(
        model=config.ModelConfig(base_url="https://model.example/v1"),
        tools=("search", "read"),
        extension_path=extension,
        agent_factory=factory,
        runtime_checker=lambda: None,
    )

    await worker.run("Reason", PromptTemplate(name="reason", text="SYSTEM"), await _board(tmp_path))

    pi_config = factory.configs[0]
    # The extension is loaded explicitly and `search` is enabled alongside the built-ins.
    assert pi_config.extra_args[pi_config.extra_args.index("-e") + 1] == str(extension)
    assert "--tools" in pi_config.extra_args
    assert pi_config.extra_args[pi_config.extra_args.index("--tools") + 1] == "search,read"
    # The server address is injected, trailing slash stripped.
    assert pi_config.env["ORIGINWEAVE_SERVER_URL"] == "http://server.example:8765"
    # The (default) agent-config-dir variable is always present as a fallback.
    assert "PI_CODING_AGENT_DIR" in pi_config.env


async def test_pi_worker_search_uses_the_server_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("ORIGINWEAVE_SERVER_URL", raising=False)
    agent = _FakePiAgent([])
    factory = _FakePiFactory(agent)
    worker = PiWorker(
        model=config.ModelConfig(base_url="https://model.example/v1"),
        tools=("search",),
        extension_path=tmp_path / "search.ts",
        agent_factory=factory,
        runtime_checker=lambda: None,
    )

    await worker.run("Reason", PromptTemplate(name="reason", text="SYSTEM"), await _board(tmp_path))

    assert factory.configs[0].env["ORIGINWEAVE_SERVER_URL"] == "http://127.0.0.1:8765"


async def test_pi_worker_without_search_does_not_load_the_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    agent = _FakePiAgent([])
    factory = _FakePiFactory(agent)
    worker = PiWorker(
        model=config.ModelConfig(base_url="https://model.example/v1"),
        tools=("read",),
        agent_factory=factory,
        runtime_checker=lambda: None,
    )

    await worker.run("Reason", PromptTemplate(name="reason", text="SYSTEM"), await _board(tmp_path))

    assert "-e" not in factory.configs[0].extra_args


def _fake_pi_install(root: Path, package: dict[str, object]) -> Path:
    """Write a fake ``pi`` install and return its binary path."""
    binary = root / "pi-coding-agent" / "dist" / "bundle" / "cli.js"
    binary.parent.mkdir(parents=True)
    binary.write_text("// cli", encoding="utf-8")
    (binary.parents[2] / "package.json").write_text(json.dumps(package), encoding="utf-8")
    return binary


@pytest.mark.parametrize(
    ("package", "expected"),
    [
        ({"piConfig": {"name": "ekreke", "configDir": ".pi"}}, "EKREKE_CODING_AGENT_DIR"),
        ({"n": {"name": "tau", "configDir": ".pi"}}, "TAU_CODING_AGENT_DIR"),
        ({"piConfig": {"configDir": ".pi"}}, "PI_CODING_AGENT_DIR"),
        ({}, "PI_CODING_AGENT_DIR"),
    ],
)
def test_resolve_agent_dir_env_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, package: dict[str, object], expected: str
) -> None:
    binary = _fake_pi_install(tmp_path, package)
    monkeypatch.setattr("shutil.which", lambda name: str(binary))
    assert resolve_agent_dir_env_name() == expected


def test_resolve_agent_dir_env_name_without_pi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert resolve_agent_dir_env_name() == "PI_CODING_AGENT_DIR"


def test_resolve_agent_dir_env_name_ignores_unrelated_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A package.json higher up the tree (not the Pi package) must not hijack the name.
    binary = tmp_path / "shim" / "pi"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "someone-else", "piConfig": {"name": "hijack"}}), encoding="utf-8"
    )
    monkeypatch.setattr("shutil.which", lambda name: str(binary))
    assert resolve_agent_dir_env_name() == "PI_CODING_AGENT_DIR"


async def test_pi_worker_uses_the_derived_agent_dir_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    binary = _fake_pi_install(
        tmp_path / "install", {"piConfig": {"name": "ekreke", "configDir": ".pi"}}
    )
    monkeypatch.setattr("shutil.which", lambda name: str(binary))
    factory = _FakePiFactory(_FakePiAgent([]))
    worker = PiWorker(
        model=config.ModelConfig(base_url="https://model.example/v1"),
        tools=(),
        agent_factory=factory,
        runtime_checker=lambda: None,
    )

    await worker.run("Reason", PromptTemplate(name="reason", text="SYSTEM"), await _board(tmp_path))

    env = factory.configs[0].env
    assert "EKREKE_CODING_AGENT_DIR" in env
    assert env["EKREKE_CODING_AGENT_DIR"] == env["PI_CODING_AGENT_DIR"]


def test_packaged_search_extension_exists() -> None:
    from originweave.capabilities.pi import _extension_path

    assert _extension_path().is_file()


async def test_pi_worker_requires_runtime_and_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = PiWorker(
        model=config.ModelConfig(base_url="https://model.example/v1"),
        tools=(),
        runtime_checker=lambda: (_ for _ in ()).throw(ProviderUnavailableError("install Pi")),
    )
    board = await _board(tmp_path)

    with pytest.raises(MissingCredentialError, match="OPENAI_API_KEY"):
        await worker.run("Reason", PromptTemplate(name="reason", text="SYSTEM"), board)

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with pytest.raises(ProviderUnavailableError, match="install Pi"):
        await worker.run("Reason", PromptTemplate(name="reason", text="SYSTEM"), board)


async def test_pi_worker_requires_node_and_pi_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("originweave.capabilities.pi.shutil.which", lambda name: None)
    worker = PiWorker(model=config.ModelConfig(base_url="https://model.example/v1"), tools=())

    with pytest.raises(ProviderUnavailableError, match="node, pi on PATH"):
        await worker.run(
            "Reason", PromptTemplate(name="reason", text="SYSTEM"), await _board(tmp_path)
        )


async def test_pi_worker_requires_openai_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    worker = PiWorker(
        model=config.ModelConfig(base_url=""),
        tools=(),
        agent_factory=_FakePiFactory(_FakePiAgent([])),
        runtime_checker=lambda: None,
    )

    with pytest.raises(MissingCredentialError, match="OPENAI_BASE_URL"):
        await worker.run(
            "Reason", PromptTemplate(name="reason", text="SYSTEM"), await _board(tmp_path)
        )


async def test_pi_worker_wraps_sdk_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class _FailingPiAgent(_FakePiAgent):
        async def __aenter__(self) -> PiAgentClient:
            raise PiProcessError("launch failed")

    worker = PiWorker(
        model=config.ModelConfig(base_url="https://model.example/v1"),
        tools=(),
        agent_factory=_FakePiFactory(_FailingPiAgent([])),
        runtime_checker=lambda: None,
    )

    with pytest.raises(ProviderError, match="Pi worker failed"):
        await worker.run(
            "Reason", PromptTemplate(name="reason", text="SYSTEM"), await _board(tmp_path)
        )


class _SteppingWorker:
    """Returns fixed replies and a fixed step chain for each call."""

    name = "stepping"
    model = "stepping-model"

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)

    async def run(
        self,
        task: str,
        template: PromptTemplate,
        board: object,
        *,
        extra: object = None,
    ) -> WorkerReply:
        text = self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]
        return WorkerReply(
            text=text,
            input={"system": template.text, "user": "{}"},
            steps=[
                WorkerStep(seq=1, kind="turn-start"),
                WorkerStep(seq=2, kind="tool-call", name="search", text="query"),
                WorkerStep(seq=3, kind="tool-result", ok=True),
                WorkerStep(seq=4, kind="turn-end"),
            ],
        )


class _BoomWorker:
    name = "boom"

    async def run(
        self,
        task: str,
        template: PromptTemplate,
        board: object,
        *,
        extra: object = None,
    ) -> WorkerReply:
        raise ProviderError("worker exploded")


def _reason(*intents: dict[str, object]) -> str:
    return json.dumps({"facts": [], "intents": list(intents), "complete": None})


def _validate(*keep: int) -> str:
    return json.dumps({"keep": list(keep), "drop": []})


async def test_engine_indexes_worker_steps(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=_SteppingWorker(_BOOTSTRAP, _NO_REASON),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    await engine.run(origin=_origin(), goal=_goal())

    events = store.read_events()
    types = [event.type for event in events]
    # The SESSION index precedes its WORKER_STEP index entries.
    assert types.index("SESSION") < types.index("WORKER_STEP")

    steps = [event for event in events if event.type == "WORKER_STEP"]
    assert len(steps) == 8  # four per call (Bootstrap + Reason)
    assert steps[0].payload["sessionId"] == "sess_001"
    assert steps[0].payload["kind"] == "turn-start"
    tool_call = next(s for s in steps if s.payload["kind"] == "tool-call")
    assert tool_call.payload["name"] == "search"

    session = json.loads((store.sessions_dir / "sess_001.json").read_text(encoding="utf-8"))
    assert len(session["steps"]) == 4
    assert session["model"] == "stepping-model"


async def test_session_ids_follow_invocation_order(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(
        store,
        _BOOTSTRAP,
        _reason({"type": "decompose", "from": "f1", "question": "split"}),
        _validate(0),
    )
    await engine.run(origin=_origin(), goal=_goal())

    by_task = {
        event.payload["sessionId"]: event.payload["task"]
        for event in store.read_events()
        if event.type == "SESSION"
    }
    assert by_task == {
        "sess_001": "Bootstrap",
        "sess_002": "Reason",
        "sess_003": "Validate",
        "sess_004": "Explore",
    }


async def test_bootstrap_worker_failure_is_terminal(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=_BoomWorker(),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    assert store.read_events()[-1].type == "FAILED"
    # Reason must not run on a dead board.
    assert not any(event.type == "REASON" for event in store.read_events())


def test_build_worker_rejects_unknown_provider() -> None:
    from originweave.capabilities import CapabilityError

    cfg = config.Config(worker=config.WorkerConfig(provider="ghost"))
    try:
        build_worker(cfg)
    except CapabilityError:
        return
    raise AssertionError("expected CapabilityError")


def test_worker_protocol_is_runtime_checkable() -> None:
    assert isinstance(_SteppingWorker(), Worker)
