from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from originweave.blackboard import Fact, Hint
from originweave.capabilities.base import PromptTemplate, ProviderError
from originweave.capabilities.model import ChatMessage
from originweave.capabilities.worker import LocalWorker, WorkerReply, render_messages
from originweave.engine import Engine, EngineError, parse_result, parse_validation
from originweave.reduce import reduce, render_canonical
from originweave.store import RunStore

REPO_ROOT = Path(__file__).resolve().parents[1]

# A Reason reply that proposes nothing, so a test can focus on the Bootstrap pass.
NO_REASON = json.dumps({"facts": [], "intents": [], "complete": None})


class _FakeModel:
    name = "fake"

    def __init__(self, *replies: str) -> None:
        if not replies:
            raise ValueError("at least one reply is required")
        self._replies = list(replies)
        self.calls: list[list[ChatMessage]] = []

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        # Consume queued replies in order. Once exhausted, return a no-op Reason so the
        # Stigmergy loop (I6) terminates instead of re-running the last scripted reply.
        if self._replies:
            return self._replies.pop(0)
        return NO_REASON


class _FakeSearch:
    name = "fake"

    async def search(self, query: str, *, num_results: int = 8) -> str:
        return ""


class _RecordingSearch:
    name = "recording"

    def __init__(self, result: str = "") -> None:
        self.result = result
        self.queries: list[str] = []

    async def search(self, query: str, *, num_results: int = 8) -> str:
        self.queries.append(query)
        return self.result


class _SelfSearchWorker:
    """A worker that owns retrieval (declares the ``search`` tool), like Pi."""

    name = "self-search"
    tools = frozenset({"search"})

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)
        self.payloads: list[dict[str, object]] = []

    async def run(
        self,
        task: str,
        template: PromptTemplate,
        board: object,
        *,
        extra: object = None,
    ) -> WorkerReply:
        messages = render_messages(task, template, board, extra=extra)  # type: ignore[arg-type]
        self.payloads.append(json.loads(messages[1].content))
        text = self._replies.pop(0) if self._replies else NO_REASON
        return WorkerReply(
            text=text,
            input={"system": messages[0].content, "user": messages[1].content},
        )


class _ConcurrencyModel:
    """Model that replays replies by task/Intent key and records overlap (I4 tests)."""

    name = "concurrency"

    def __init__(
        self,
        replies: dict[str, str],
        delays: dict[str, float] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self._replies = replies
        self._delays = delays or {}
        self._errors = errors or {}
        self.calls: list[str] = []
        self.completed: list[str] = []
        self.in_flight = 0
        self.peak = 0

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        payload = json.loads(messages[1].content)
        # Explore passes carry an "intent"; the serial passes are keyed by task name.
        key = payload["intent"]["id"] if "intent" in payload else payload["task"]
        self.calls.append(key)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self._delays.get(key, 0.0))
            if key in self._errors:
                raise self._errors[key]
            self.completed.append(key)
            return self._replies[key]
        finally:
            self.in_flight -= 1


class _FakePrompt:
    name = "fake"

    async def get(self, name: str) -> PromptTemplate:
        return PromptTemplate(name=name, text=name.upper())


def _origin() -> Fact:
    return Fact.from_dict({"id": "origin", "kind": "origin", "label": "Document A"})


def _goal() -> Fact:
    return Fact.from_dict({"id": "goal", "kind": "goal", "label": "Every sub-claim is sourced"})


def _engine(store: RunStore, *replies: str) -> Engine:
    return Engine(
        worker=LocalWorker(model=_FakeModel(*replies)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )


def _bootstrap(*labels: str) -> str:
    return json.dumps(
        {
            "facts": [
                {"label": label, "kind": "fact", "role": "main-claim", "status": "open"}
                for label in labels
            ],
            "intents": [],
            "complete": None,
        }
    )


def _reason(*intents: dict[str, object]) -> str:
    return json.dumps({"facts": [], "intents": list(intents), "complete": None})


def _validate(*keep: int, drop: list[dict[str, object]] | None = None) -> str:
    return json.dumps({"keep": list(keep), "drop": drop or []})


def _complete(verdict: str) -> str:
    return json.dumps({"facts": [], "intents": [], "complete": {"verdict": verdict}})


def _complete_with_hint(verdict: str, hint: str) -> str:
    return json.dumps({"facts": [], "intents": [], "complete": {"verdict": verdict}, "hint": hint})


def _explore_reply(*facts: dict[str, object]) -> str:
    return json.dumps({"facts": list(facts), "intents": [], "complete": None})


def _compare_reply(*deviations: dict[str, object]) -> str:
    compare = {
        "label": "compare (facts x sources x goal)",
        "kind": "compare",
        "role": "none",
        "status": "verified",
        "confidence": 0.8,
    }
    return json.dumps({"facts": [compare, *deviations], "intents": [], "complete": None})


def _sub_claim(label: str) -> dict[str, object]:
    return {
        "label": label,
        "kind": "fact",
        "role": "sub-claim",
        "status": "open",
        "confidence": 0.5,
    }


def _source_fact(label: str) -> dict[str, object]:
    return {
        "label": label,
        "kind": "source",
        "role": "none",
        "status": "verified",
        "confidence": 0.9,
        "evidence": [
            {
                "quote": "developers completed tasks 55% faster",
                "sourceTitle": "GitHub Copilot lab study",
                "url": "https://example.com/lab-study",
                "locator": "section 3.1",
            }
        ],
    }


async def test_bootstrap_produces_a_main_claim(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    model = _FakeModel(_bootstrap("Copilot cut task time by 55%."), NO_REASON)
    engine = Engine(
        worker=LocalWorker(model=model),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    assert board.origin.kind == "origin"
    assert board.goal.kind == "goal"
    main = [fact for fact in board.facts if fact.role == "main-claim"]
    assert [fact.id for fact in main] == ["f1"]
    assert main[0].kind == "fact"

    assert [intent.id for intent in board.intents] == ["i1"]
    assert board.intents[0].status == "done"
    assert board.intents[0].type == "explore"
    assert board.intents[0].producedFacts == ["f1"]

    relations = {(edge.source, edge.target, edge.relation) for edge in board.edges}
    assert ("origin", "i1", "spawns") in relations
    assert ("i1", "f1", "resolves") in relations

    events = store.read_events()
    assert [event.id for event in events] == [f"e{i:04d}" for i in range(1, len(events) + 1)]
    assert [event.type for event in events] == [
        "PROJECT",
        "INTENT",
        "EXECUTE",
        "CONCLUDE",
        "SESSION",
        "REASON",
        "REASON",
        "SESSION",
    ]
    bootstrap_session = events[4]
    assert bootstrap_session.payload["task"] == "Bootstrap"
    assert bootstrap_session.payload["intentId"] == "i1"
    assert bootstrap_session.payload["ref"] == "sessions/sess_001.json"

    assert len(model.calls) == 2
    assert model.calls[0][0].role == "system"


async def test_bootstrap_allows_multiple_main_claims(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(store, _bootstrap("Claim one", "Claim two"), NO_REASON).run(
        origin=_origin(), goal=_goal()
    )
    assert [fact.id for fact in board.facts] == ["f1", "f2"]
    assert all(fact.role == "main-claim" for fact in board.facts)


async def test_reason_writes_candidate_intents(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("A claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split into sub-claims."}),
        _validate(0),
        _explore_reply(_sub_claim("Sub claim one")),
    ).run(origin=_origin(), goal=_goal())

    assert [intent.id for intent in board.intents] == ["i1", "i2"]
    proposed = board.intents[1]
    assert proposed.type == "decompose"
    assert proposed.from_ == "f1"
    # The dispatch round executed the kept Intent right after Reason.
    assert proposed.status == "done"
    assert proposed.producedFacts == ["f2"]
    relations = {(edge.source, edge.target, edge.relation) for edge in board.edges}
    assert ("f1", "i2", "spawns") in relations
    assert ("i2", "f2", "resolves") in relations
    assert ("f1", "f2", "decomposes") in relations


async def test_reason_rejects_facts(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    bad_reason = json.dumps(
        {"facts": [{"label": "x", "kind": "fact", "role": "none"}], "intents": [], "complete": None}
    )
    board = await _engine(store, _bootstrap("A claim"), bad_reason).run(
        origin=_origin(), goal=_goal()
    )

    assert board.status == "failed"
    events = store.read_events()
    assert events[-1].type == "FAILED"
    # The unusable reply stays auditable via its session snapshot.
    assert events[-2].type == "SESSION"
    assert events[-2].payload["task"] == "Reason"


async def test_reason_rejects_unknown_from(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("A claim"),
        _reason({"type": "decompose", "from": "f9", "question": "?"}),
    ).run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    assert store.read_events()[-1].type == "FAILED"


async def test_reason_assigns_sequential_ids(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("Claim one", "Claim two"),
        _reason(
            {"type": "decompose", "from": "f1", "question": "Split f1."},
            {"type": "explore", "from": "f2", "question": "Source f2."},
        ),
        _validate(0, 1),
        _explore_reply(_sub_claim("Sub of f1")),
        _explore_reply(_source_fact("Primary source for f2")),
    ).run(origin=_origin(), goal=_goal())

    assert [intent.id for intent in board.intents] == ["i1", "i2", "i3"]
    assert [intent.type for intent in board.intents[1:]] == ["decompose", "explore"]
    # The dispatch round executed both intents in id order.
    assert [intent.status for intent in board.intents[1:]] == ["done", "done"]
    assert board.intents[1].producedFacts == ["f3"]
    assert board.intents[2].producedFacts == ["s1"]


async def test_reason_rejects_goal_as_from(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("A claim"),
        _reason({"type": "explore", "from": "goal", "question": "?"}),
    ).run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    assert store.read_events()[-1].type == "FAILED"


async def test_reason_bad_from_writes_nothing(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    reason = _reason(
        {"type": "decompose", "from": "f1", "question": "ok"},
        {"type": "explore", "from": "f9", "question": "bad"},
    )
    board = await _engine(store, _bootstrap("A claim"), reason).run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    # The good candidate must not be half-written when a later one is rejected.
    assert sum(event.type == "INTENT" for event in store.read_events()) == 1


async def test_reason_intents_are_deterministic(tmp_path: Path) -> None:
    bootstrap = _bootstrap("A claim")
    reason = _reason({"type": "decompose", "from": "f1", "question": "Split it."})
    validate = _validate(0)
    first = await _engine(RunStore(tmp_path / "a"), bootstrap, reason, validate).run(
        origin=_origin(), goal=_goal()
    )
    second = await _engine(RunStore(tmp_path / "b"), bootstrap, reason, validate).run(
        origin=_origin(), goal=_goal()
    )
    assert [(i.id, i.type, i.from_, i.status, i.duplicateOf) for i in first.intents] == [
        (i.id, i.type, i.from_, i.status, i.duplicateOf) for i in second.intents
    ]
    assert [(e.source, e.target, e.relation) for e in first.edges] == [
        (e.source, e.target, e.relation) for e in second.edges
    ]


async def test_validate_drops_duplicate_candidates(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("A claim"),
        _reason(
            {"type": "explore", "from": "origin", "question": "Re-examine the document."},
            {"type": "decompose", "from": "f1", "question": "Split f1."},
        ),
        _validate(1, drop=[{"index": 0, "duplicateOf": "i1", "reason": "same as i1"}]),
        _explore_reply(_sub_claim("Sub claim")),
    ).run(origin=_origin(), goal=_goal())

    assert [intent.id for intent in board.intents] == ["i1", "i2", "i3"]
    dropped = board.intents[1]
    assert dropped.status == "dropped"
    assert dropped.duplicateOf == "i1"
    kept = board.intents[2]
    assert kept.status == "done"  # executed by the dispatch round
    assert kept.type == "decompose"
    assert kept.duplicateOf is None


async def test_validate_skips_when_no_candidates(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    model = _FakeModel(_bootstrap("A claim"), NO_REASON)
    engine = Engine(
        worker=LocalWorker(model=model),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    await engine.run(origin=_origin(), goal=_goal())

    assert len(model.calls) == 2  # bootstrap + reason only; nothing to validate
    assert not any(event.type == "VALIDATE" for event in store.read_events())


async def test_validate_emits_counted_events(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    await _engine(
        store,
        _bootstrap("A claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split it."}),
        _validate(0),
    ).run(origin=_origin(), goal=_goal())

    validate_events = [event for event in store.read_events() if event.type == "VALIDATE"]
    assert [event.payload["phase"] for event in validate_events] == ["start", "end"]
    assert validate_events[0].payload == {"phase": "start", "candidates": 1}
    assert validate_events[1].payload["kept"] == 1
    assert validate_events[1].payload["dropped"] == 0
    assert validate_events[1].payload["drops"] == []


async def test_validate_passes_candidates_to_worker(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    model = _FakeModel(
        _bootstrap("A claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split it."}),
        _validate(0),
    )
    engine = Engine(
        worker=LocalWorker(model=model),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    await engine.run(origin=_origin(), goal=_goal())

    validate_call = model.calls[2]
    assert validate_call[0].content == "VALIDATE"  # _FakePrompt uppercases the name
    assert '"candidates"' in validate_call[1].content


async def test_validate_must_classify_every_candidate(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("A claim"),
        _reason(
            {"type": "decompose", "from": "f1", "question": "one"},
            {"type": "explore", "from": "f1", "question": "two"},
        ),
        _validate(0),  # candidate 1 is left unclassified
    ).run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    assert store.read_events()[-1].type == "FAILED"


async def test_validate_rejects_unknown_duplicate_of(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("A claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split it."}),
        _validate(drop=[{"index": 0, "duplicateOf": "i9", "reason": "nope"}]),
    ).run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    assert store.read_events()[-1].type == "FAILED"


async def test_validate_bad_reply_fails_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("A claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split it."}),
        "not json",
    ).run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    assert store.read_events()[-1].type == "FAILED"


async def test_validate_event_records_drops(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    await _engine(
        store,
        _bootstrap("A claim"),
        _reason({"type": "explore", "from": "origin", "question": "Re-scan."}),
        _validate(drop=[{"index": 0, "duplicateOf": "i1", "reason": "same as i1"}]),
    ).run(origin=_origin(), goal=_goal())

    end = [
        event
        for event in store.read_events()
        if event.type == "VALIDATE" and event.payload["phase"] == "end"
    ][0]
    assert end.payload["kept"] == 0
    assert end.payload["dropped"] == 1
    assert end.payload["drops"] == [{"index": 0, "duplicateOf": "i1", "reason": "same as i1"}]


async def test_validate_rebuilds_candidate_lifecycle_fields(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    reason = json.dumps(
        {
            "facts": [],
            "intents": [
                {
                    "type": "explore",
                    "from": "origin",
                    "question": "Re-scan.",
                    "status": "done",
                    "duplicateOf": "i1",
                    "claimedBy": "evil",
                }
            ],
            "complete": None,
        }
    )
    board = await _engine(store, _bootstrap("A claim"), reason, _validate(0), _explore_reply()).run(
        origin=_origin(), goal=_goal()
    )

    candidate = board.intents[1]
    # The engine rebuilt the candidate's lifecycle fields (the reply claimed
    # done/evil) and the dispatch round then claimed and closed it itself.
    assert candidate.status == "done"
    assert candidate.duplicateOf is None
    assert candidate.claimedBy == "worker-1"
    assert candidate.producedFacts == []


async def test_validate_provider_error_fails_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")

    class _Boom:
        name = "boom"

        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, messages: Sequence[ChatMessage]) -> str:
            self.calls += 1
            if self.calls == 1:
                return _bootstrap("A claim")
            if self.calls == 2:
                return _reason({"type": "decompose", "from": "f1", "question": "Split it."})
            raise ProviderError("validate model exploded")

    engine = Engine(
        worker=LocalWorker(model=_Boom()),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    board = await engine.run(origin=_origin(), goal=_goal())
    assert board.status == "failed"
    assert store.read_events()[-1].type == "FAILED"


async def test_missing_validate_prompt_fails_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")

    class _NoValidate:
        name = "fake"

        async def get(self, name: str) -> PromptTemplate:
            if name == "validate":
                raise FileNotFoundError("no validate template")
            return PromptTemplate(name=name, text=name.upper())

    model = _FakeModel(
        _bootstrap("A claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split it."}),
    )
    engine = Engine(
        worker=LocalWorker(model=model),
        search=_FakeSearch(),
        prompt=_NoValidate(),
        store=store,
        auto=True,
    )
    board = await engine.run(origin=_origin(), goal=_goal())
    assert board.status == "failed"
    assert store.read_events()[-1].type == "FAILED"


async def test_explore_runs_search_and_registers_evidence(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    search = _RecordingSearch(result="Study: 55% faster task completion.")
    model = _FakeModel(
        _bootstrap("Copilot cut task time by 55%."),
        _reason({"type": "explore", "from": "f1", "question": "Find the primary source for f1."}),
        _validate(0),
        _explore_reply(_source_fact("GitHub lab study reports a 55% speedup")),
    )
    engine = Engine(
        worker=LocalWorker(model=model), search=search, prompt=_FakePrompt(), store=store, auto=True
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    # The engine queried the search capability with the intent's question.
    assert search.queries == ["Find the primary source for f1."]

    source = board.facts[1]
    assert source.id == "s1"
    assert source.kind == "source"
    assert [evidence.id for evidence in source.evidence] == ["ev1"]
    assert source.evidence[0].quote == "developers completed tasks 55% faster"
    assert source.evidence[0].url == "https://example.com/lab-study"
    assert source.evidence[0].sourceTitle == "GitHub Copilot lab study"

    intent = board.intents[1]
    assert intent.status == "done"
    assert intent.producedFacts == ["s1"]
    relations = {(edge.source, edge.target, edge.relation) for edge in board.edges}
    assert ("i2", "s1", "resolves") in relations


async def test_explore_passes_intent_and_search_to_worker(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    search = _RecordingSearch(result="S1: the lab study.")
    model = _FakeModel(
        _bootstrap("A claim"),
        _reason({"type": "explore", "from": "f1", "question": "Source f1."}),
        _validate(0),
        _explore_reply(_source_fact("Primary source")),
    )
    engine = Engine(
        worker=LocalWorker(model=model), search=search, prompt=_FakePrompt(), store=store, auto=True
    )
    await engine.run(origin=_origin(), goal=_goal())

    explore_call = model.calls[3]
    assert explore_call[0].content == "EXPLORE"  # _FakePrompt uppercases the name
    payload = json.loads(explore_call[1].content)
    assert payload["intent"] == {
        "id": "i2",
        "type": "explore",
        "from": "f1",
        "question": "Source f1.",
    }
    assert payload["search"] == "S1: the lab study."


async def test_worker_with_search_tool_skips_engine_prefetch(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    search = _RecordingSearch(result="unused")
    worker = _SelfSearchWorker(
        _bootstrap("A claim"),
        _reason({"type": "explore", "from": "f1", "question": "Source f1."}),
        _validate(0),
        _explore_reply(_source_fact("Primary source")),
    )
    engine = Engine(worker=worker, search=search, prompt=_FakePrompt(), store=store, auto=True)
    await engine.run(origin=_origin(), goal=_goal())

    # The worker owns retrieval, so the engine does not call `search` itself.
    assert search.queries == []
    explore_payload = worker.payloads[3]
    assert "search" not in explore_payload
    assert explore_payload["intent"]["question"] == "Source f1."


async def test_explore_decompose_produces_sub_claims(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    search = _RecordingSearch()
    model = _FakeModel(
        _bootstrap("Copilot cut task time by 55%."),
        _reason({"type": "decompose", "from": "f1", "question": "Split into sub-claims."}),
        _validate(0),
        _explore_reply(_sub_claim("Experienced users sped up"), _sub_claim("Novices did not")),
    )
    engine = Engine(
        worker=LocalWorker(model=model), search=search, prompt=_FakePrompt(), store=store, auto=True
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    # A decompose pass never searches.
    assert search.queries == []
    subs = [fact for fact in board.facts if fact.role == "sub-claim"]
    assert [fact.id for fact in subs] == ["f2", "f3"]
    intent = board.intents[1]
    assert intent.status == "done"
    assert intent.producedFacts == ["f2", "f3"]
    relations = {(edge.source, edge.target, edge.relation) for edge in board.edges}
    assert ("i2", "f2", "resolves") in relations
    assert ("i2", "f3", "resolves") in relations
    assert ("f1", "f2", "decomposes") in relations
    assert ("f1", "f3", "decomposes") in relations


async def test_verify_intent_is_dispatched_to_compare(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    compare_reply = json.dumps(
        {
            "facts": [
                {
                    "label": "compare (facts x sources x goal)",
                    "kind": "compare",
                    "role": "none",
                    "status": "verified",
                    "confidence": 0.8,
                }
            ],
            "intents": [],
            "complete": None,
        }
    )
    model = _FakeModel(
        _bootstrap("A claim"),
        _reason({"type": "verify", "from": "f1", "question": "Compare f1 with its source."}),
        _validate(0),
        compare_reply,
    )
    engine = Engine(
        worker=LocalWorker(model=model),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    # M2: a "verify" Intent now runs the compare pass instead of staying open (I3).
    verify = board.intents[1]
    assert verify.type == "verify"
    assert verify.status == "done"
    assert [fact.kind for fact in board.facts].count("compare") == 1
    assert board.status == "running"


async def test_explore_search_failure_fails_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")

    class _BoomSearch:
        name = "boom"

        async def search(self, query: str, *, num_results: int = 8) -> str:
            raise ProviderError("search exploded")

    model = _FakeModel(
        _bootstrap("A claim"),
        _reason({"type": "explore", "from": "f1", "question": "Source f1."}),
        _validate(0),
    )
    engine = Engine(
        worker=LocalWorker(model=model),
        search=_BoomSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    events = store.read_events()
    assert events[-1].type == "FAILED"
    assert events[-1].payload["reason"] == "search exploded"
    # The claim was already written, so the audit shows "claimed, then died".
    assert events[-2].type == "EXECUTE"


async def test_decompose_rejects_citation_facts(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    model = _FakeModel(
        _bootstrap("A claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split f1."}),
        _validate(0),
        _explore_reply(_source_fact("A source, not a sub-claim")),
    )
    engine = Engine(
        worker=LocalWorker(model=model),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    events = store.read_events()
    assert events[-1].type == "FAILED"
    assert "decompose intent" in events[-1].payload["reason"]
    assert events[-2].type == "SESSION"
    assert events[-2].payload["task"] == "Explore"


async def test_dispatch_commit_stops_after_a_failed_intent(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    bad = json.dumps(
        {
            "facts": [{"label": "x", "kind": "citation", "role": "none", "status": "open"}],
            "intents": [],
            "complete": None,
        }
    )
    model = _FakeModel(
        _bootstrap("A claim"),
        _reason(
            {"type": "decompose", "from": "f1", "question": "Split f1."},
            {"type": "decompose", "from": "f1", "question": "Split f1 again."},
        ),
        _validate(0, 1),
        bad,
        _explore_reply(_sub_claim("Committed too late")),
    )
    engine = Engine(
        worker=LocalWorker(model=model),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    # Both claimed Intents run (Bootstrap, Reason, Validate, two Explores); commit stops
    # at the first failure, so no dispatch Intent is concluded.
    assert len(model.calls) == 5
    assert not [
        event
        for event in store.read_events()
        if event.type == "CONCLUDE" and event.payload.get("intentId") in {"i2", "i3"}
    ]
    second = board.intents[2]
    assert second.status == "claimed"
    assert second.producedFacts == []


@pytest.mark.parametrize(
    "reply",
    [
        # Reason's job leaked into an Explore reply.
        _reason({"type": "decompose", "from": "f1", "question": "Reason's job."}),
        # Completion is Reason's job, too.
        json.dumps({"facts": [], "intents": [], "complete": {"verdict": "done"}}),
        # An explore Intent may not produce claim facts.
        json.dumps(
            {
                "facts": [{"label": "x", "kind": "fact", "role": "main-claim", "status": "open"}],
                "intents": [],
                "complete": None,
            }
        ),
        # A citation must not claim a role (it would pollute the main-claim set).
        json.dumps(
            {
                "facts": [
                    {
                        "label": "x",
                        "kind": "citation",
                        "role": "main-claim",
                        "status": "open",
                        "evidence": [{"quote": "q", "sourceTitle": "t", "url": "u"}],
                    }
                ],
                "intents": [],
                "complete": None,
            }
        ),
        # citation/source facts must carry at least one evidence entry.
        json.dumps(
            {
                "facts": [{"label": "x", "kind": "source", "role": "none", "status": "verified"}],
                "intents": [],
                "complete": None,
            }
        ),
        # Malformed JSON.
        "not json",
    ],
)
async def test_explore_bad_reply_fails_run(tmp_path: Path, reply: str) -> None:
    store = RunStore(tmp_path / "run_001")
    model = _FakeModel(
        _bootstrap("A claim"),
        _reason({"type": "explore", "from": "f1", "question": "Source f1."}),
        _validate(0),
        reply,
    )
    engine = Engine(
        worker=LocalWorker(model=model),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    events = store.read_events()
    assert events[-1].type == "FAILED"
    # The unusable reply is still recorded for the audit trail.
    assert events[-2].type == "SESSION"
    assert events[-2].payload["task"] == "Explore"


async def test_explore_records_session_and_event_order(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    model = _FakeModel(
        _bootstrap("A claim"),
        _reason({"type": "explore", "from": "f1", "question": "Source f1."}),
        _validate(0),
        _explore_reply(_source_fact("Primary source")),
    )
    engine = Engine(
        worker=LocalWorker(model=model),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
        max_rounds=1,  # this test pins the single-dispatch event order
    )
    await engine.run(origin=_origin(), goal=_goal())

    events = store.read_events()
    assert [event.type for event in events[-3:]] == ["EXECUTE", "CONCLUDE", "SESSION"]
    session = events[-1]
    assert session.payload["task"] == "Explore"
    assert session.payload["intentId"] == "i2"
    assert session.payload["ref"] == "sessions/sess_004.json"
    snapshot = json.loads((store.root / "sessions" / "sess_004.json").read_text(encoding="utf-8"))
    assert snapshot["intentId"] == "i2"
    assert json.loads(snapshot["input"]["user"])["intent"]["id"] == "i2"


async def test_explore_pipeline_is_deterministic(tmp_path: Path) -> None:
    replies = (
        _bootstrap("A claim"),
        _reason(
            {"type": "decompose", "from": "f1", "question": "Split f1."},
            {"type": "explore", "from": "f1", "question": "Source f1."},
        ),
        _validate(0, 1),
        _explore_reply(_sub_claim("Sub one")),
        _explore_reply(_source_fact("Primary source")),
    )
    first = await _engine(RunStore(tmp_path / "a"), *replies).run(origin=_origin(), goal=_goal())
    second = await _engine(RunStore(tmp_path / "b"), *replies).run(origin=_origin(), goal=_goal())
    # Across two runs only volatile timestamps differ; the structure is identical.
    assert [(f.id, f.kind, f.role) for f in first.facts] == [
        (f.id, f.kind, f.role) for f in second.facts
    ]
    assert [(i.id, i.type, i.status, i.producedFacts) for i in first.intents] == [
        (i.id, i.type, i.status, i.producedFacts) for i in second.intents
    ]
    assert [(e.source, e.target, e.relation) for e in first.edges] == [
        (e.source, e.target, e.relation) for e in second.edges
    ]


def _concurrency_scenario(
    store: RunStore, *, max_concurrency: int, delays: dict[str, float]
) -> tuple[Engine, _ConcurrencyModel]:
    """A Reason pass that yields two dispatchable Intents (i2 decompose, i3 explore)."""
    model = _ConcurrencyModel(
        {
            "Bootstrap": _bootstrap("A claim"),
            "Reason": _reason(
                {"type": "decompose", "from": "f1", "question": "Split f1."},
                {"type": "explore", "from": "f1", "question": "Source f1."},
            ),
            "Validate": _validate(0, 1),
            "i2": _explore_reply(_sub_claim("Sub one")),
            "i3": _explore_reply(_source_fact("Primary source")),
        },
        delays=delays,
    )
    engine = Engine(
        worker=LocalWorker(model=model),
        search=_RecordingSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
        max_concurrency=max_concurrency,
        max_rounds=1,  # these tests pin a single dispatch round
    )
    return engine, model


async def test_dispatch_runs_intents_concurrently(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine, model = _concurrency_scenario(store, max_concurrency=2, delays={"i2": 0.05, "i3": 0.0})
    board = await engine.run(origin=_origin(), goal=_goal())

    assert model.peak == 2  # the two Explore passes overlapped
    assert sorted(model.calls) == ["Bootstrap", "Reason", "Validate", "i2", "i3"]
    assert [intent.status for intent in board.intents[1:]] == ["done", "done"]
    # Worker labels are assigned deterministically in Intent id order (i1 is Bootstrap).
    claims = [
        event.payload["worker"]
        for event in store.read_events()
        if event.type == "EXECUTE" and event.payload["intentId"] != "i1"
    ]
    assert claims == ["worker-1", "worker-2"]


async def test_dispatch_respects_max_concurrency_one(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine, model = _concurrency_scenario(store, max_concurrency=1, delays={"i2": 0.05, "i3": 0.0})
    board = await engine.run(origin=_origin(), goal=_goal())

    assert model.peak == 1  # serialized by the cap
    assert [intent.status for intent in board.intents[1:]] == ["done", "done"]


async def test_concurrent_dispatch_board_is_deterministic(tmp_path: Path) -> None:
    # The two Intents finish in opposite orders across the two runs; the committed
    # Board must still be identical because commit order follows Intent id.
    first_store = RunStore(tmp_path / "a")
    first, first_model = _concurrency_scenario(
        first_store, max_concurrency=2, delays={"i2": 0.05, "i3": 0.0}
    )
    second_store = RunStore(tmp_path / "b")
    second, second_model = _concurrency_scenario(
        second_store, max_concurrency=2, delays={"i2": 0.0, "i3": 0.05}
    )
    first_board = await first.run(origin=_origin(), goal=_goal())
    second_board = await second.run(origin=_origin(), goal=_goal())

    # The dispatch Intents really did finish in opposite orders across the two runs.
    assert [key for key in first_model.completed if key in {"i2", "i3"}] == ["i3", "i2"]
    assert [key for key in second_model.completed if key in {"i2", "i3"}] == ["i2", "i3"]

    assert [(f.id, f.kind, f.role) for f in first_board.facts] == [
        (f.id, f.kind, f.role) for f in second_board.facts
    ]
    assert [(i.id, i.type, i.status, i.producedFacts) for i in first_board.intents] == [
        (i.id, i.type, i.status, i.producedFacts) for i in second_board.intents
    ]
    assert [(e.source, e.target, e.relation) for e in first_board.edges] == [
        (e.source, e.target, e.relation) for e in second_board.edges
    ]


def _single_explore_model(delay: float) -> _ConcurrencyModel:
    return _ConcurrencyModel(
        {
            "Bootstrap": _bootstrap("A claim"),
            "Reason": _reason({"type": "explore", "from": "f1", "question": "Source f1."}),
            "Validate": _validate(0),
            "i2": _explore_reply(_source_fact("Primary source")),
        },
        delays={"i2": delay},
    )


async def test_heartbeat_is_emitted_while_worker_runs(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=LocalWorker(model=_single_explore_model(0.05)),
        search=_RecordingSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
        heartbeat_interval=0.01,
        heartbeat_timeout=5.0,
        max_rounds=1,  # pin the single slow Explore pass under test
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    heartbeats = [event for event in store.read_events() if event.type == "HEARTBEAT"]
    assert heartbeats  # the engine kept the lease alive during the slow call
    assert {event.payload["intentId"] for event in heartbeats} == {"i2"}
    assert board.intents[1].status == "done"
    assert board.status == "running"


async def test_heartbeat_timeout_releases_intent(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=LocalWorker(model=_single_explore_model(1.0)),
        search=_RecordingSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
        heartbeat_interval=0.01,
        heartbeat_timeout=0.05,
        heartbeat_on_timeout="release",
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    events = store.read_events()
    releases = [event for event in events if event.type == "RELEASE"]
    assert releases and releases[-1].payload["intentId"] == "i2"
    assert not any(event.type == "FAILED" for event in events)
    assert board.status == "running"
    intent = board.intents[1]
    # Released back to open; I6 does not retry it because this round added no facts.
    assert intent.status == "open"
    assert intent.claimedBy is None


async def test_heartbeat_timeout_fails_run_when_configured(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=LocalWorker(model=_single_explore_model(1.0)),
        search=_RecordingSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
        heartbeat_interval=0.01,
        heartbeat_timeout=0.05,
        heartbeat_on_timeout="fail",
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    events = store.read_events()
    assert events[-1].type == "FAILED"
    assert "heartbeat_timeout" in events[-1].payload["reason"]


async def test_unexpected_worker_error_is_committed_not_raised(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    model = _ConcurrencyModel(
        {
            "Bootstrap": _bootstrap("A claim"),
            "Reason": _reason(
                {"type": "decompose", "from": "f1", "question": "Split f1."},
                {"type": "decompose", "from": "f1", "question": "Split f1 again."},
            ),
            "Validate": _validate(0, 1),
            "i2": _explore_reply(_sub_claim("Never committed")),
            "i3": _explore_reply(_sub_claim("Never committed either")),
        },
        errors={"i2": RuntimeError("worker bug")},
    )
    engine = Engine(
        worker=LocalWorker(model=model),
        search=_RecordingSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
        max_concurrency=2,
        heartbeat_interval=0.01,
        heartbeat_timeout=5.0,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    # A non-CapabilityError from a worker becomes a committed FAILED, not an escape.
    assert board.status == "failed"
    assert store.read_events()[-1].type == "FAILED"
    # No sibling pass is left writing to the blackboard after run() returned.
    count = len(store.read_events())
    await asyncio.sleep(0.05)
    assert len(store.read_events()) == count


async def test_slow_search_trips_heartbeat_timeout(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")

    class _SlowSearch:
        name = "slow"

        async def search(self, query: str, *, num_results: int = 8) -> str:
            await asyncio.sleep(1.0)
            return "too late"

    engine = Engine(
        worker=LocalWorker(model=_single_explore_model(0.0)),
        search=_SlowSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
        heartbeat_interval=0.01,
        heartbeat_timeout=0.05,
        heartbeat_on_timeout="release",
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    # The lease covers the search phase too, so a hung search does not hold the Intent.
    assert board.status == "running"
    assert any(event.type == "RELEASE" for event in store.read_events())
    assert board.intents[1].status == "open"


def test_engine_rejects_bad_heartbeat_settings(tmp_path: Path) -> None:
    def build(**kwargs: object) -> Engine:
        return Engine(
            worker=LocalWorker(model=_FakeModel('{"facts": [], "intents": [], "complete": null}')),
            search=_FakeSearch(),
            prompt=_FakePrompt(),
            store=RunStore(tmp_path / "run_001"),
            **kwargs,
        )

    with pytest.raises(ValueError):
        build(heartbeat_interval=1.0, heartbeat_timeout=1.0)
    with pytest.raises(ValueError):
        build(heartbeat_on_timeout="explode")
    with pytest.raises(ValueError):
        build(max_rounds=0)


async def test_gate_a_suspends_run_after_bootstrap(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=LocalWorker(model=_FakeModel(_bootstrap("A claim"))),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    assert board.status == "awaiting_human"
    assert board.waitingFor is not None
    assert board.waitingFor.gate == "confirm-claim"
    assert "f1" in board.waitingFor.question
    # Only Bootstrap ran; Reason is held back until the human confirms.
    assert [intent.id for intent in board.intents] == ["i1"]
    assert sum(event.type == "REQUEST_HUMAN" for event in store.read_events()) == 1


async def test_auto_skips_gate_a(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=LocalWorker(model=_FakeModel(_bootstrap("A claim"), NO_REASON)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    assert board.status == "running"
    assert not any(event.type == "REQUEST_HUMAN" for event in store.read_events())


async def test_run_auto_override_skips_gate(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(  # constructor default is human-in-the-loop
        worker=LocalWorker(model=_FakeModel(_bootstrap("A claim"), NO_REASON)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
    )
    board = await engine.run(origin=_origin(), goal=_goal(), auto=True)

    assert board.status == "running"
    assert not any(event.type == "REQUEST_HUMAN" for event in store.read_events())


async def test_run_auto_false_override_pauses(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(  # constructor default is human-in-the-loop
        worker=LocalWorker(model=_FakeModel(_bootstrap("A claim"), NO_REASON)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    board = await engine.run(origin=_origin(), goal=_goal(), auto=False)

    assert board.status == "awaiting_human"


async def test_gate_a_suspends_even_without_main_claims(tmp_path: Path) -> None:
    # Bootstrap finding no claim must not silently bypass the human.
    no_claim = json.dumps({"facts": [], "intents": [], "complete": None})
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=LocalWorker(model=_FakeModel(no_claim)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    assert board.status == "awaiting_human"
    assert board.waitingFor is not None
    assert board.waitingFor.gate == "confirm-claim"
    assert "none were extracted" in board.waitingFor.question


async def test_resume_approve_continues_the_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    model = _FakeModel(
        _bootstrap("A claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split f1."}),
        _validate(0),
        _explore_reply(_sub_claim("Sub claim")),
    )
    engine = Engine(
        worker=LocalWorker(model=model), search=_FakeSearch(), prompt=_FakePrompt(), store=store
    )
    assert (await engine.run(origin=_origin(), goal=_goal())).status == "awaiting_human"

    board = await engine.resume(decision="approve")

    assert board.status == "running"
    decisions = [event for event in store.read_events() if event.type == "HUMAN_INPUT"]
    assert decisions[0].payload["decision"] == "approve"
    assert decisions[0].payload["author"] == "human"
    assert [intent.id for intent in board.intents] == ["i1", "i2"]
    assert board.intents[1].status == "done"
    assert board.intents[1].producedFacts == ["f2"]


async def test_resume_edit_records_decision_and_continues(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    model = _FakeModel(
        _bootstrap("A claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split f1."}),
        _validate(0),
        _explore_reply(_sub_claim("Sub claim")),
    )
    engine = Engine(
        worker=LocalWorker(model=model), search=_FakeSearch(), prompt=_FakePrompt(), store=store
    )
    await engine.run(origin=_origin(), goal=_goal())

    board = await engine.resume(decision="edit", text="tighten the claim", targets=["f1"])

    assert board.status == "running"
    decision = next(event for event in store.read_events() if event.type == "HUMAN_INPUT")
    assert decision.payload["decision"] == "edit"
    assert decision.payload["text"] == "tighten the claim"
    assert decision.payload["targets"] == ["f1"]
    # edit is record-only for now, so the board still decomposes the original claim.
    assert board.decisions[0].targets == ["f1"]


async def test_resume_twice_raises(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=LocalWorker(model=_FakeModel(_bootstrap("A claim"), NO_REASON)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
    )
    await engine.run(origin=_origin(), goal=_goal())
    await engine.resume(decision="approve")

    with pytest.raises(EngineError):
        await engine.resume(decision="approve")


async def test_resume_reject_stops_the_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=LocalWorker(model=_FakeModel(_bootstrap("A claim"))),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
    )
    await engine.run(origin=_origin(), goal=_goal())

    board = await engine.resume(decision="reject", text="not the core claim")

    assert board.status == "stopped"
    events = store.read_events()
    assert events[-1].type == "STOPPED"
    assert "rejected" in events[-1].payload["reason"]
    # A rejected gate never reaches Reason.
    assert not any(event.type == "REASON" for event in events)


async def test_resume_without_pending_gate_raises(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=LocalWorker(model=_FakeModel(_bootstrap("A claim"), NO_REASON)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
    )
    await engine.run(origin=_origin(), goal=_goal())

    with pytest.raises(EngineError):
        await engine.resume(decision="approve")


async def test_resume_rejects_unknown_decision(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=LocalWorker(model=_FakeModel(_bootstrap("A claim"))),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
    )
    await engine.run(origin=_origin(), goal=_goal())

    with pytest.raises(EngineError):
        await engine.resume(decision="maybe")


async def test_resume_on_fresh_engine_rebuilds_id_counters(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    first = Engine(
        worker=LocalWorker(model=_FakeModel(_bootstrap("A claim"))),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
    )
    await first.run(origin=_origin(), goal=_goal())

    # A brand-new Engine over the same run dir resumes as if it had never paused.
    resumed = Engine(
        worker=LocalWorker(
            model=_FakeModel(
                _reason({"type": "decompose", "from": "f1", "question": "Split f1."}),
                _validate(0),
                _explore_reply(_sub_claim("Sub claim")),
            )
        ),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
    )
    board = await resumed.resume(decision="approve")

    assert [intent.id for intent in board.intents] == ["i1", "i2"]
    assert board.intents[1].producedFacts == ["f2"]
    ids = [intent.id for intent in board.intents]
    assert len(ids) == len(set(ids))
    sessions = [
        event.payload["sessionId"] for event in store.read_events() if event.type == "SESSION"
    ]
    assert len(sessions) == len(set(sessions))


async def test_replay_reproduces_human_input(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=LocalWorker(model=_FakeModel(_bootstrap("A claim"), NO_REASON)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
    )
    await engine.run(origin=_origin(), goal=_goal())
    board = await engine.resume(decision="approve")

    replayed = reduce(store.read_events())
    assert replayed.decisions[0].gate == "confirm-claim"
    assert replayed.decisions[0].decision == "approve"
    assert render_canonical(replayed) == render_canonical(board)


async def test_stigmergy_runs_multiple_rounds_until_complete(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("Core claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split f1."}),
        _validate(0),
        _explore_reply(_sub_claim("Sub claim")),
        _reason({"type": "explore", "from": "f2", "question": "Source f2."}),
        _validate(0),
        _explore_reply(_source_fact("Primary source")),
        # M2: the goal is "provenance-complete + deviations scored", so a compare pass
        # must run before Reason may complete.
        _reason({"type": "verify", "from": "f2", "question": "Compare f2."}),
        _validate(0),
        _compare_reply(),
        _complete("部分偏差"),
    ).run(origin=_origin(), goal=_goal())

    assert board.status == "completed"
    assert board.verdict == "部分偏差"
    assert [fact.id for fact in board.facts] == ["f1", "f2", "s1", "p1"]
    assert [(i.id, i.status) for i in board.intents] == [
        ("i1", "done"),
        ("i2", "done"),
        ("i3", "done"),
        ("i4", "done"),
    ]
    # Each Reason round is recorded with only the facts added since the last one.
    triggers = [
        event.payload["triggerFacts"]
        for event in store.read_events()
        if event.type == "REASON" and event.payload["phase"] == "start"
    ]
    assert triggers == [["f1"], ["f2"], ["s1"], ["p1"]]


async def test_stigmergy_stops_at_dead_end(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("Core claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split f1."}),
        _validate(0),
        _explore_reply(_sub_claim("Sub claim")),
        NO_REASON,  # the next round offers no direction
    ).run(origin=_origin(), goal=_goal())

    # Reason added facts, but round 2 proposes nothing: the loop stops (no terminal).
    assert board.status == "running"
    assert [intent.status for intent in board.intents] == ["done", "done"]
    starts = [
        event
        for event in store.read_events()
        if event.type == "REASON" and event.payload["phase"] == "start"
    ]
    assert len(starts) == 2


async def test_stigmergy_dedups_intents_across_rounds(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("Core claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split f1."}),
        _validate(0),
        _explore_reply(_sub_claim("Sub claim")),
        _reason({"type": "decompose", "from": "f1", "question": "Split f1 again."}),
        _validate(drop=[{"index": 0, "duplicateOf": "i2", "reason": "already done"}]),
    ).run(origin=_origin(), goal=_goal())

    dropped = board.intents[2]
    assert board.status == "running"
    assert dropped.id == "i3"
    assert dropped.status == "dropped"
    assert dropped.duplicateOf == "i2"


async def test_stigmergy_respects_max_rounds(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = Engine(
        worker=LocalWorker(
            model=_FakeModel(
                _bootstrap("Core claim"),
                _reason({"type": "decompose", "from": "f1", "question": "Split f1."}),
                _validate(0),
                _explore_reply(_sub_claim("Sub claim")),
                _complete("should never be reached"),
            )
        ),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
        store=store,
        auto=True,
        max_rounds=1,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    # One productive round happened, then the safety valve stopped the loop.
    assert board.status == "running"
    assert [intent.id for intent in board.intents] == ["i1", "i2"]
    starts = [
        event
        for event in store.read_events()
        if event.type == "REASON" and event.payload["phase"] == "start"
    ]
    assert len(starts) == 1


async def test_stigmergy_is_deterministic(tmp_path: Path) -> None:
    replies = (
        _bootstrap("Core claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split f1."}),
        _validate(0),
        _explore_reply(_sub_claim("Sub claim")),
        _reason({"type": "explore", "from": "f2", "question": "Source f2."}),
        _validate(0),
        _explore_reply(_source_fact("Primary source")),
        _complete("done"),
    )
    first = await _engine(RunStore(tmp_path / "a"), *replies).run(origin=_origin(), goal=_goal())
    second = await _engine(RunStore(tmp_path / "b"), *replies).run(origin=_origin(), goal=_goal())
    assert [(f.id, f.kind, f.role) for f in first.facts] == [
        (f.id, f.kind, f.role) for f in second.facts
    ]
    assert [(i.id, i.type, i.status, i.producedFacts) for i in first.intents] == [
        (i.id, i.type, i.status, i.producedFacts) for i in second.intents
    ]
    assert [(e.source, e.target, e.relation) for e in first.edges] == [
        (e.source, e.target, e.relation) for e in second.edges
    ]


async def test_stigmergy_reason_error_after_a_productive_round_fails_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    bad_reason = json.dumps(
        {"facts": [{"label": "x", "kind": "fact", "role": "none"}], "intents": [], "complete": None}
    )
    board = await _engine(
        store,
        _bootstrap("Core claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split f1."}),
        _validate(0),
        _explore_reply(_sub_claim("Sub claim")),
        bad_reason,  # round 2: Reason illegally emits facts
    ).run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    events = store.read_events()
    assert events[-1].type == "FAILED"
    triggers = [
        event.payload["triggerFacts"]
        for event in events
        if event.type == "REASON" and event.payload["phase"] == "start"
    ]
    assert triggers == [["f1"], ["f2"]]


async def test_reason_hint_on_completion_writes_agent_hint(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("Core claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split f1."}),
        _validate(0),
        _explore_reply(_sub_claim("Sub claim")),
        _reason({"type": "explore", "from": "f2", "question": "Source f2."}),
        _validate(0),
        _explore_reply(_source_fact("Primary source")),
        _reason({"type": "verify", "from": "f2", "question": "Compare f2."}),
        _validate(0),
        _compare_reply(),
        # Convergence: the goal is met and Reason leaves a note for later readers.
        _complete_with_hint("部分偏差", "prefer the original lab study over summaries"),
    ).run(origin=_origin(), goal=_goal())

    assert board.status == "completed"
    hints = [event for event in store.read_events() if event.type == "HINT"]
    assert [event.payload["hint"]["id"] for event in hints] == ["h1"]
    assert hints[0].payload["hint"]["author"] == "agent"
    assert hints[0].payload["hint"]["text"] == "prefer the original lab study over summaries"
    # The hint lands before COMPLETE, so a replay folds it into the final board.
    event_types = [event.type for event in store.read_events()]
    assert event_types.index("HINT") < event_types.index("COMPLETE")
    assert [hint.id for hint in board.hints] == ["h1"]
    assert board.hints[0].author == "agent"


async def test_reason_hint_on_dead_end_keeps_run_running(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    dead_end = json.dumps(
        {"facts": [], "intents": [], "complete": None, "hint": "no source claims this"}
    )
    board = await _engine(
        store,
        _bootstrap("Core claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split f1."}),
        _validate(0),
        _explore_reply(_sub_claim("Sub claim")),
        dead_end,  # round 2 offers no direction but leaves a note
    ).run(origin=_origin(), goal=_goal())

    # The dead-end hint is kept on the board; the run stays running (no terminal).
    assert board.status == "running"
    hints = [event for event in store.read_events() if event.type == "HINT"]
    assert [event.payload["hint"]["id"] for event in hints] == ["h1"]
    assert hints[0].payload["hint"]["author"] == "agent"
    assert [hint.text for hint in board.hints] == ["no source claims this"]


async def test_reason_hint_alongside_intents_is_ignored(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    reason = json.dumps(
        {
            "facts": [],
            "intents": [{"type": "decompose", "from": "f1", "question": "Split f1."}],
            "complete": None,
            "hint": "work in progress, not a convergence note",
        }
    )
    await _engine(
        store,
        _bootstrap("A claim"),
        reason,
        _validate(0),
        _explore_reply(_sub_claim("Sub claim")),
        NO_REASON,
    ).run(origin=_origin(), goal=_goal())

    # A hint next to Intents is not a convergence note (M3): it is dropped.
    assert not [event for event in store.read_events() if event.type == "HINT"]


async def test_reason_hint_without_satisfied_goal_is_ignored(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(
        store,
        _bootstrap("A claim"),
        _complete_with_hint("部分偏差", "too early to conclude"),
    ).run(origin=_origin(), goal=_goal())

    # The structural stop condition does not hold yet (no decompose/compare), so the
    # intermediate convergence call leaves no hint and no COMPLETE (M2 rule preserved).
    assert board.status == "running"
    assert not [event for event in store.read_events() if event.type == "HINT"]
    assert all(event.type != "COMPLETE" for event in store.read_events())


async def test_explore_reply_rejects_hint(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    explore = json.dumps(
        {"facts": [], "intents": [], "complete": None, "hint": "explore may not hint"}
    )
    board = await _engine(
        store,
        _bootstrap("A claim"),
        _reason({"type": "explore", "from": "f1", "question": "Source f1."}),
        _validate(0),
        explore,
    ).run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    events = store.read_events()
    assert events[-1].type == "FAILED"
    assert "hint" in events[-1].payload["reason"]


async def test_human_and_agent_hints_get_distinct_ids(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    store.append_event(
        "HINT",
        {"hint": Hint(id="h1", text="check the benchmark env", author="human").to_dict()},
        message="Hint added",
    )
    board = await _engine(
        store,
        _bootstrap("Core claim"),
        _reason({"type": "decompose", "from": "f1", "question": "Split f1."}),
        _validate(0),
        _explore_reply(_sub_claim("Sub claim")),
        _reason({"type": "explore", "from": "f2", "question": "Source f2."}),
        _validate(0),
        _explore_reply(_source_fact("Primary source")),
        _reason({"type": "verify", "from": "f2", "question": "Compare f2."}),
        _validate(0),
        _compare_reply(),
        _complete_with_hint("部分偏差", "convergence note"),
    ).run(origin=_origin(), goal=_goal())

    assert board.status == "completed"
    hint_events = [event for event in store.read_events() if event.type == "HINT"]
    # The agent hint continues the event-log numbering instead of colliding with h1.
    assert [event.payload["hint"]["id"] for event in hint_events] == ["h1", "h2"]
    assert [event.payload["hint"]["author"] for event in hint_events] == ["human", "agent"]


def test_parse_result_hint_requires_reason_task() -> None:
    reply = json.dumps({"facts": [], "intents": [], "complete": None, "hint": "note"})
    with pytest.raises(EngineError):
        parse_result(reply)  # Bootstrap/Explore calls do not allow hints
    result = parse_result(reply, allow_hint=True)
    assert result.hint == "note"


def test_parse_result_rejects_empty_hint() -> None:
    reply = json.dumps({"facts": [], "intents": [], "complete": None, "hint": "   "})
    with pytest.raises(EngineError):
        parse_result(reply, allow_hint=True)


async def test_bootstrap_bad_reply_fails_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    board = await _engine(store, "not json").run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    events = store.read_events()
    assert events[-1].type == "FAILED"
    # The unusable reply stays auditable via its session snapshot; the Bootstrap
    # intent was never written, so the session carries no intentId.
    assert events[-2].type == "SESSION"
    assert events[-2].payload["task"] == "Bootstrap"
    assert "intentId" not in events[-2].payload


@pytest.mark.parametrize("missing", ["bootstrap", "reason", "explore"])
async def test_missing_prompt_fails_run(tmp_path: Path, missing: str) -> None:
    store = RunStore(tmp_path / "run_001")

    class _MissingPrompt:
        name = "fake"

        async def get(self, name: str) -> PromptTemplate:
            if name == missing:
                raise FileNotFoundError(f"no {name} template")
            return PromptTemplate(name=name, text=name.upper())

    if missing == "explore":
        # The explore template is only fetched once an Intent is dispatched.
        replies: tuple[str, ...] = (
            _bootstrap("A claim"),
            _reason({"type": "explore", "from": "f1", "question": "Source f1."}),
            _validate(0),
        )
    else:
        replies = (_bootstrap("A claim"), NO_REASON)
    engine = Engine(
        worker=LocalWorker(model=_FakeModel(*replies)),
        search=_FakeSearch(),
        prompt=_MissingPrompt(),
        store=store,
        auto=True,
    )
    board = await engine.run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    assert store.read_events()[-1].type == "FAILED"


async def test_reason_complete_without_supporting_structure_is_ignored(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "run_001")
    reason = json.dumps({"facts": [], "intents": [], "complete": {"verdict": "部分偏差"}})
    board = await _engine(store, _bootstrap("A claim"), reason).run(origin=_origin(), goal=_goal())

    # M2: a bare "complete" no longer ends the run. The structural stop condition
    # (every claim decomposed and sourced, deviations scored) must hold first, so the
    # run stays "running" and no COMPLETE is written.
    assert board.status == "running"
    events = store.read_events()
    assert all(event.type != "COMPLETE" for event in events)
    ends = [event for event in events if event.type == "REASON" and event.payload["phase"] == "end"]
    assert len(ends) == 1
    assert ends[0].payload["triggerFacts"] == ["f1"]


async def test_reason_rejects_intents_and_complete_together(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    reason = json.dumps(
        {
            "facts": [],
            "intents": [{"type": "decompose", "from": "f1", "question": "?"}],
            "complete": {"verdict": "done"},
        }
    )
    board = await _engine(store, _bootstrap("A claim"), reason).run(origin=_origin(), goal=_goal())

    assert board.status == "failed"
    assert store.read_events()[-1].type == "FAILED"


async def test_board_is_deterministic(tmp_path: Path) -> None:
    bootstrap = _bootstrap("A claim")
    store = RunStore(tmp_path / "a")
    first = await _engine(store, bootstrap, NO_REASON).run(origin=_origin(), goal=_goal())
    # The reducer is a pure fold: the same events always yield the same board.
    assert render_canonical(first) == render_canonical(reduce(store.read_events()))

    second = await _engine(RunStore(tmp_path / "b"), bootstrap, NO_REASON).run(
        origin=_origin(), goal=_goal()
    )
    # Across two runs only volatile timestamps differ; the structure is identical.
    assert [(f.id, f.kind, f.role) for f in first.facts] == [
        (f.id, f.kind, f.role) for f in second.facts
    ]
    assert [(i.id, i.type, i.status) for i in first.intents] == [
        (i.id, i.type, i.status) for i in second.intents
    ]
    assert [(e.source, e.target, e.relation) for e in first.edges] == [
        (e.source, e.target, e.relation) for e in second.edges
    ]


def test_parse_result_reads_fields_and_ids_evidence() -> None:
    result = parse_result(
        json.dumps(
            {
                "facts": [
                    {
                        "label": "x",
                        "kind": "fact",
                        "role": "main-claim",
                        "confidence": 0.5,
                        "evidence": [
                            {"quote": "q", "sourceTitle": "t", "url": "u", "locator": "l"}
                        ],
                    }
                ],
                "intents": [{"type": "decompose", "from": "f1", "question": "split it"}],
                "complete": {"verdict": "partial"},
            }
        )
    )
    assert result.complete == "partial"
    assert result.facts[0].evidence[0].id == "ev1"
    assert result.facts[0].evidence[0].quote == "q"
    assert result.intents[0].type == "decompose"


def test_parse_result_rejects_non_json() -> None:
    with pytest.raises(EngineError):
        parse_result("not json")


def test_parse_result_rejects_unknown_fact_kind() -> None:
    with pytest.raises(EngineError):
        parse_result(json.dumps({"facts": [{"label": "x", "kind": "nope", "role": "main-claim"}]}))


def test_parse_result_rejects_unknown_intent_type() -> None:
    with pytest.raises(EngineError):
        parse_result(json.dumps({"intents": [{"type": "guess", "question": "q"}]}))


def test_parse_validation_accepts_keep_and_drop() -> None:
    result = parse_validation(
        json.dumps({"keep": [1], "drop": [{"index": 0, "duplicateOf": "i1", "reason": "dup"}]}),
        2,
        {"i1"},
    )
    assert [(d.index, d.drop, d.duplicate_of) for d in result.decisions] == [
        (0, True, "i1"),
        (1, False, None),
    ]
    assert result.kept == 1
    assert result.dropped == 1


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        "[]",
        json.dumps({"keep": "nope"}),
        json.dumps({"keep": [True]}),  # bool index
        json.dumps({"keep": [0], "drop": [{"index": 0}]}),  # classified twice
        json.dumps({"keep": []}),  # missing candidates
        json.dumps({"keep": [5]}),  # out of range
        json.dumps({"keep": [0], "drop": [{"index": 1, "duplicateOf": "x"}]}),  # unknown dup
        json.dumps({"keep": [0], "drop": [1]}),  # drop entry not an object
    ],
)
def test_parse_validation_rejects_malformed(reply: str) -> None:
    with pytest.raises(EngineError):
        parse_validation(reply, 2, {"i1"})


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
async def test_live_bootstrap_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from originweave import config
    from originweave.capabilities import build_model, build_prompt, build_search

    monkeypatch.chdir(REPO_ROOT)
    cfg = config.Config()
    document = (REPO_ROOT / "examples/copilot_productivity/input/document.md").read_text(
        encoding="utf-8"
    )
    origin = Fact.from_dict(
        {"id": "origin", "kind": "origin", "label": "Document A", "note": document}
    )
    engine = Engine(
        worker=LocalWorker(model=build_model(cfg)),
        search=build_search(cfg),
        prompt=build_prompt(cfg),
        store=RunStore(tmp_path / "live"),
        auto=False,
    )
    board = await engine.run(origin=origin, goal=_goal())
    assert any(fact.role == "main-claim" for fact in board.facts)
