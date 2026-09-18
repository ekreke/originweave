from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from originweave import config
from originweave.blackboard import Fact
from originweave.capabilities import ProviderUnavailableError, build_worker
from originweave.capabilities.base import PromptTemplate, ProviderError
from originweave.capabilities.model import ChatMessage
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
        if len(self._replies) > 1:
            return self._replies.pop(0)
        return self._replies[0]


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


def test_build_worker_defaults_to_local() -> None:
    assert isinstance(build_worker(config.Config()), LocalWorker)


def test_build_worker_pi_is_unavailable() -> None:
    cfg = config.Config(worker=config.WorkerConfig(provider="pi"))
    try:
        build_worker(cfg)
    except ProviderUnavailableError:
        return
    raise AssertionError("expected ProviderUnavailableError")


def test_worker_step_truncates_event_text_not_snapshot() -> None:
    step = WorkerStep(seq=1, kind="tool-result", name="search", text="x" * (STEP_TEXT_LIMIT + 50))
    payload = step.to_dict()
    assert len(payload["text"]) == STEP_TEXT_LIMIT
    full = step.to_session_dict()
    assert len(full["text"]) == STEP_TEXT_LIMIT + 50


# --------------------------------------------------------------- fake workers


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
    assert by_task == {"sess_001": "Bootstrap", "sess_002": "Reason", "sess_003": "Validate"}


async def test_bootstrap_worker_failure_is_terminal(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=_BoomWorker(),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
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

