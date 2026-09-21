"""ASGI tests for the Connect server (M1c-1).

Skipped when the generated ``originweave.v1`` code is absent (i.e. `make proto` has
not been run); CI generates it first, so the tests run there.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

pytest.importorskip("originweave.v1.originweave_connect")

from originweave import config as config_module  # noqa: E402
from originweave.capabilities import PromptTemplate, ProviderError  # noqa: E402
from originweave.capabilities.worker import LocalWorker  # noqa: E402
from originweave.config import Config, WorkerConfig  # noqa: E402
from originweave.persistence import Project, ProjectRegistry  # noqa: E402
from originweave.reduce import reduce  # noqa: E402
from originweave.server import Providers, ServerContext, create_app  # noqa: E402
from originweave.server.service import Service  # noqa: E402
from originweave.store import RunStore  # noqa: E402

SERVICE = "/originweave.v1.OriginweaveService"
JSON_HEADERS = {"Content-Type": "application/json"}

_ORIGIN = {"id": "origin", "kind": "origin", "label": "Document A"}
_GOAL = {"id": "goal", "kind": "goal", "label": "Every sub-claim is sourced"}

NO_REASON = '{"facts": [], "intents": [], "complete": null}'


class _FakeModel:
    """Replays scripted replies; falls back to a no-op Reason when exhausted."""

    name = "fake"

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies)

    async def complete(self, messages: Sequence[object]) -> str:
        if self._replies:
            return self._replies.pop(0)
        return NO_REASON


class _FakeSearch:
    name = "fake"

    async def search(self, query: str, *, num_results: int = 8) -> str:
        return ""


class _SlowModel:
    """Blocks before replying, so CreateRun can be observed returning mid-run."""

    name = "slow"

    def __init__(self, delay: float, *replies: str) -> None:
        self._delay = delay
        self._replies = list(replies)

    async def complete(self, messages: Sequence[object]) -> str:
        await asyncio.sleep(self._delay)
        if self._replies:
            return self._replies.pop(0)
        return NO_REASON


class _FakePrompt:
    name = "fake"

    async def get(self, name: str) -> PromptTemplate:
        return PromptTemplate(name=name, text=name.upper())


def _bootstrap(*labels: str) -> str:
    facts = [
        {
            "label": label,
            "kind": "fact",
            "role": "main-claim",
            "status": "open",
            "confidence": 0.5,
        }
        for label in labels
    ]
    return json.dumps({"facts": facts, "intents": [], "complete": None})


def _providers(*replies: str) -> Providers:
    return Providers(
        worker=LocalWorker(model=_FakeModel(*replies)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
    )


def _client(root: Path) -> httpx.AsyncClient:
    # An explicit config keeps the test independent of any originweave.toml in CWD.
    app = create_app(config=Config(), root=root)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _ctx_with(root: Path, providers: Providers) -> ServerContext:
    """A server context rooted at ``root`` with a project ``p`` and given providers."""
    ProjectRegistry(root / "projects", root / "runs").write(Project(id="p", name="P"))
    # Scripted providers run in-process; container behaviour is covered separately in
    # test_runtime without requiring Docker for every server contract test.
    config = Config(worker=WorkerConfig(execution="in-process", container_scope="per-call"))
    return ServerContext.build(config=config, providers=providers, root=root)


def _ctx(root: Path, *replies: str) -> ServerContext:
    """A server context rooted at ``root`` with a project ``p`` and fake providers."""
    return _ctx_with(root, _providers(*replies))


def _client_for(ctx: ServerContext) -> httpx.AsyncClient:
    app = create_app(service=Service(ctx))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _create_run(client: httpx.AsyncClient, *, auto: bool | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "projectId": "p",
        "sourceType": "text",
        "sourceText": "Copilot cut task time by 55%.",
        "goal": "Every claim is sourced.",
    }
    if auto is not None:
        body["auto"] = auto
    response = await _post(client, "CreateRun", body)
    assert response.status_code == 200, response.text
    return response.json()["run"]


def _write_run(
    runs_dir: Path,
    run_id: str,
    *,
    project_id: str,
    complete: bool = True,
    at: str = "2026-01-01T00:00:0{}",
) -> None:
    store = RunStore(runs_dir / run_id)
    store.init_layout()
    store.write_run_meta({"id": run_id, "project_id": project_id, "title": "T", "goal": "g"})
    store.append_event("PROJECT", {"origin": _ORIGIN, "goal": _GOAL}, at=at.format(0))
    store.append_event(
        "INTENT",
        {"intent": {"id": "i1", "type": "explore", "from": "origin", "question": "q"}},
        at=at.format(1),
    )
    store.append_event(
        "EXECUTE", {"intentId": "i1", "worker": "worker-1", "model": "x"}, at=at.format(2)
    )
    store.append_event(
        "CONCLUDE",
        {"intentId": "i1", "facts": [{"id": "f1", "kind": "fact", "role": "main-claim"}]},
        at=at.format(3),
    )
    if complete:
        store.append_event("COMPLETE", {"verdict": "ok"}, at=at.format(4))


async def _post(client: httpx.AsyncClient, method: str, body: dict[str, object]) -> httpx.Response:
    return await client.post(f"{SERVICE}/{method}", content=json.dumps(body), headers=JSON_HEADERS)


async def test_list_projects_is_empty(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        response = await _post(client, "ListProjects", {})

    assert response.status_code == 200
    assert response.json() == {}


async def test_create_app_accepts_an_injected_service(tmp_path: Path) -> None:
    app = create_app(service=Service(ServerContext.build(root=tmp_path)))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await _post(client, "ListProjects", {})

    assert response.status_code == 200


async def test_get_run_returns_detail(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")

    async with _client(tmp_path) as client:
        response = await _post(client, "GetRun", {"runId": "run_001"})

    assert response.status_code == 200
    detail = response.json()["runDetail"]
    assert detail["run"]["id"] == "run_001"
    assert detail["run"]["status"] == "completed"
    assert detail["run"]["projectId"] == "p"
    assert [fact["id"] for fact in detail["facts"]] == ["f1"]
    assert [intent["id"] for intent in detail["intents"]] == ["i1"]
    assert detail["origin"]["kind"] == "origin"
    assert len(detail["events"]) == 5
    assert detail["events"][0]["type"] == "PROJECT"


async def test_get_run_missing_reports_not_found(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        response = await _post(client, "GetRun", {"runId": "run_404"})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_get_run_exposes_waiting_for(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs" / "run_001")
    store.init_layout()
    store.write_run_meta({"id": "run_001", "project_id": "p"})
    store.append_event(
        "PROJECT", {"origin": _ORIGIN, "goal": _GOAL}, at="2026-01-01T00:00:00+00:00"
    )
    store.append_event(
        "REQUEST_HUMAN",
        {"gate": "confirm-claim", "question": "ok?"},
        at="2026-01-01T00:00:01+00:00",
    )

    async with _client(tmp_path) as client:
        response = await _post(client, "GetRun", {"runId": "run_001"})

    detail = response.json()["runDetail"]
    assert detail["run"]["status"] == "awaiting_human"
    assert detail["waitingFor"]["gate"] == "confirm-claim"


async def test_get_project_rejects_invalid_id(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        response = await _post(client, "GetProject", {"projectId": "a/b"})

    assert response.json()["code"] == "invalid_argument"


async def test_list_runs_skips_corrupt_and_stray_dirs(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")
    corrupt = tmp_path / "runs" / "run_002"
    corrupt.mkdir(parents=True)
    (corrupt / "events.jsonl").write_text("not json", encoding="utf-8")
    (tmp_path / "runs" / "junk").mkdir()

    async with _client(tmp_path) as client:
        response = await _post(client, "ListRuns", {})

    assert [run["id"] for run in response.json()["runs"]] == ["run_001"]


async def test_get_run_corrupt_log_reports_internal(tmp_path: Path) -> None:
    corrupt = tmp_path / "runs" / "run_002"
    corrupt.mkdir(parents=True)
    (corrupt / "events.jsonl").write_text("not json", encoding="utf-8")

    async with _client(tmp_path) as client:
        response = await _post(client, "GetRun", {"runId": "run_002"})

    assert response.status_code == 500
    assert response.json()["code"] == "internal"


async def test_get_run_at_event_folds_the_board(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")
    events = RunStore(tmp_path / "runs" / "run_001").read_events()

    async with _client(tmp_path) as client:
        responses = [
            await _post(client, "GetRun", {"runId": "run_001", "atEvent": k}) for k in range(1, 6)
        ]

    for k, response in enumerate(responses, start=1):
        assert response.status_code == 200, response.text
        detail = response.json()["runDetail"]
        board = reduce(events[:k])
        assert [fact["id"] for fact in detail.get("facts", [])] == [f.id for f in board.facts]
        assert [intent["id"] for intent in detail.get("intents", [])] == [
            i.id for i in board.intents
        ]
        assert [edge["id"] for edge in detail.get("edges", [])] == [e.id for e in board.edges]
        assert detail["run"]["status"] == board.status
        # The timeline always carries the full log so stepping keeps a stable length.
        assert len(detail["events"]) == len(events)

    # Concrete checkpoints: after PROJECT only, then after CONCLUDE, then COMPLETE.
    assert responses[0].json()["runDetail"]["run"]["status"] == "running"
    assert responses[0].json()["runDetail"].get("facts", []) == []
    assert [f["id"] for f in responses[3].json()["runDetail"]["facts"]] == ["f1"]
    assert responses[4].json()["runDetail"]["run"]["status"] == "completed"


async def test_get_run_at_event_folds_hints_and_gates(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs" / "run_001")
    store.init_layout()
    store.write_run_meta({"id": "run_001", "project_id": "p"})
    at = "2026-01-01T00:00:0{}"
    store.append_event("PROJECT", {"origin": _ORIGIN, "goal": _GOAL}, at=at.format(0))
    store.append_event(
        "HINT",
        {"hint": {"id": "h1", "text": "t", "author": "human", "createdAt": ""}},
        at=at.format(1),
    )
    store.append_event(
        "REQUEST_HUMAN", {"gate": "confirm-claim", "question": "ok?"}, at=at.format(2)
    )

    async with _client(tmp_path) as client:
        first = await _post(client, "GetRun", {"runId": "run_001", "atEvent": 1})
        second = await _post(client, "GetRun", {"runId": "run_001", "atEvent": 2})
        third = await _post(client, "GetRun", {"runId": "run_001", "atEvent": 3})

    only_project = first.json()["runDetail"]
    assert only_project.get("hints", []) == []
    assert "waitingFor" not in only_project

    with_hint = second.json()["runDetail"]
    assert [hint["id"] for hint in with_hint["hints"]] == ["h1"]
    assert "waitingFor" not in with_hint  # the gate is not requested yet

    awaiting = third.json()["runDetail"]
    assert awaiting["waitingFor"]["gate"] == "confirm-claim"
    assert awaiting["run"]["status"] == "awaiting_human"


async def test_get_run_rejects_out_of_range_at_event(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")

    async with _client(tmp_path) as client:
        too_small = await _post(client, "GetRun", {"runId": "run_001", "atEvent": 0})
        too_big = await _post(client, "GetRun", {"runId": "run_001", "atEvent": 99})

    for response in (too_small, too_big):
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_argument"


async def test_pinned_run_supports_at_event(tmp_path: Path) -> None:
    run_dir = _write_ui_run(tmp_path, "demo")  # PROJECT + COMPLETE

    async with _ui_client(tmp_path, static_dir=None, run_dir=run_dir) as client:
        first = await _post(client, "GetRun", {"runId": "demo", "atEvent": 1})
        full = await _post(client, "GetRun", {"runId": "demo", "atEvent": 2})

    assert first.json()["runDetail"]["run"]["status"] == "running"
    assert full.json()["runDetail"]["run"]["status"] == "completed"


async def test_get_run_includes_source_text_for_retry(tmp_path: Path) -> None:
    # A bad Bootstrap reply fails the run; failed/stopped runs expose source_text so
    # the UI can retry them.
    ctx = _ctx(tmp_path, "not json")
    async with _client_for(ctx) as client:
        run = await _create_run(client, auto=True)
        await ctx.scheduler.wait(str(run["id"]))
        detail = (await _post(client, "GetRun", {"runId": str(run["id"])})).json()["runDetail"]
        await ctx.scheduler.drain()

    assert detail["run"]["status"] == "failed"
    # CreateRun writes input/document.md; GetRun exposes it verbatim for the retry flow.
    assert detail["sourceText"] == "Copilot cut task time by 55%."


async def test_get_run_source_text_is_empty_without_input(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")

    async with _client(tmp_path) as client:
        detail = (await _post(client, "GetRun", {"runId": "run_001"})).json()["runDetail"]

    assert detail.get("sourceText", "") == ""


async def test_get_run_graph_returns_light_projection(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")

    async with _client(tmp_path) as client:
        response = await _post(client, "GetRunGraph", {"runId": "run_001"})

    assert response.status_code == 200
    graph = response.json()["graph"]
    assert graph["run"]["id"] == "run_001"
    assert graph["run"]["status"] == "completed"
    assert [fact["id"] for fact in graph["facts"]] == ["f1"]
    assert [intent["id"] for intent in graph["intents"]] == ["i1"]
    assert graph["origin"]["kind"] == "origin"
    assert graph["goal"]["kind"] == "goal"
    assert graph["eventCount"] == 5
    # The light projection carries counts, not evidence/note payloads...
    assert graph["facts"][0].get("evidenceCount", 0) == 0
    assert "evidence" not in graph["facts"][0]
    assert "note" not in graph["facts"][0]
    # ...and none of the heavy RunDetail-only sections.
    assert "events" not in graph
    assert "sessions" not in graph
    assert "sourceText" not in graph


async def test_get_run_graph_at_event_folds_and_keeps_full_count(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")
    events = RunStore(tmp_path / "runs" / "run_001").read_events()

    async with _client(tmp_path) as client:
        responses = [
            await _post(client, "GetRunGraph", {"runId": "run_001", "atEvent": k})
            for k in range(1, 6)
        ]

    for k, response in enumerate(responses, start=1):
        assert response.status_code == 200, response.text
        graph = response.json()["graph"]
        board = reduce(events[:k])
        assert [fact["id"] for fact in graph.get("facts", [])] == [f.id for f in board.facts]
        assert graph["run"]["status"] == board.status
        # The cursor bound is the full-log length, stable while stepping.
        assert graph["eventCount"] == len(events)
    assert responses[0].json()["graph"].get("facts", []) == []
    assert responses[4].json()["graph"]["run"]["status"] == "completed"


async def test_get_run_graph_missing_reports_not_found(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        response = await _post(client, "GetRunGraph", {"runId": "run_404"})

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_get_run_graph_rejects_out_of_range_at_event(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")

    async with _client(tmp_path) as client:
        too_small = await _post(client, "GetRunGraph", {"runId": "run_001", "atEvent": 0})
        too_big = await _post(client, "GetRunGraph", {"runId": "run_001", "atEvent": 99})

    for response in (too_small, too_big):
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_argument"


def _write_run_with_evidence(runs_dir: Path, run_id: str) -> None:
    """A run whose produced fact carries a note + verbatim evidence (M2 style)."""
    store = RunStore(runs_dir / run_id)
    store.init_layout()
    store.write_run_meta({"id": run_id, "project_id": "p"})
    at = "2026-01-01T00:00:0{}"
    store.append_event("PROJECT", {"origin": _ORIGIN, "goal": _GOAL}, at=at.format(0))
    store.append_event(
        "INTENT",
        {"intent": {"id": "i1", "type": "explore", "from": "origin", "question": "q"}},
        at=at.format(1),
    )
    store.append_event(
        "EXECUTE", {"intentId": "i1", "worker": "worker-1", "model": "x"}, at=at.format(2)
    )
    store.append_event(
        "CONCLUDE",
        {
            "intentId": "i1",
            "facts": [
                {
                    "id": "f1",
                    "kind": "fact",
                    "role": "sub-claim",
                    "note": "analyst remark",
                    "evidence": [
                        {
                            "id": "ev1",
                            "quote": "verbatim",
                            "sourceTitle": "Source",
                            "url": "https://example.com",
                            "locator": "p.1",
                        }
                    ],
                }
            ],
        },
        at=at.format(3),
    )


async def test_get_fact_detail_returns_evidence_and_note(tmp_path: Path) -> None:
    _write_run_with_evidence(tmp_path / "runs", "run_001")

    async with _client(tmp_path) as client:
        response = await _post(client, "GetFactDetail", {"runId": "run_001", "factId": "f1"})

    assert response.status_code == 200
    fact = response.json()["fact"]
    assert fact["note"] == "analyst remark"
    assert [evidence["id"] for evidence in fact["evidence"]] == ["ev1"]
    assert fact["evidence"][0]["quote"] == "verbatim"


async def test_get_fact_detail_serves_origin_goal_and_missing(tmp_path: Path) -> None:
    _write_run_with_evidence(tmp_path / "runs", "run_001")

    async with _client(tmp_path) as client:
        origin = await _post(client, "GetFactDetail", {"runId": "run_001", "factId": "origin"})
        goal = await _post(client, "GetFactDetail", {"runId": "run_001", "factId": "goal"})
        missing = await _post(client, "GetFactDetail", {"runId": "run_001", "factId": "nope"})
        empty = await _post(client, "GetFactDetail", {"runId": "run_001", "factId": ""})

    assert origin.json()["fact"]["kind"] == "origin"
    assert goal.json()["fact"]["kind"] == "goal"
    assert missing.status_code == 404
    assert empty.status_code == 400


async def test_get_fact_detail_folds_at_event(tmp_path: Path) -> None:
    # f1 only exists from the CONCLUDE event (4) onward; earlier folds lack it.
    _write_run_with_evidence(tmp_path / "runs", "run_001")

    async with _client(tmp_path) as client:
        early = await _post(
            client, "GetFactDetail", {"runId": "run_001", "factId": "f1", "atEvent": 2}
        )
        late = await _post(
            client, "GetFactDetail", {"runId": "run_001", "factId": "f1", "atEvent": 4}
        )

    assert early.status_code == 404
    assert late.status_code == 200
    assert late.json()["fact"]["id"] == "f1"


async def test_list_events_returns_full_and_sliced(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")

    async with _client(tmp_path) as client:
        full = await _post(client, "ListEvents", {"runId": "run_001"})
        sliced = await _post(client, "ListEvents", {"runId": "run_001", "atEvent": 2})
        out_of_range = await _post(client, "ListEvents", {"runId": "run_001", "atEvent": 99})

    assert full.status_code == 200
    assert len(full.json()["events"]) == 5
    assert sliced.status_code == 200
    assert [event["id"] for event in sliced.json()["events"]] == ["e0001", "e0002"]
    assert out_of_range.status_code == 400


async def test_list_sessions_filters_by_intent(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs" / "run_001")
    store.init_layout()
    store.write_run_meta({"id": "run_001", "project_id": "p"})
    store.append_event(
        "PROJECT", {"origin": _ORIGIN, "goal": _GOAL}, at="2026-01-01T00:00:00+00:00"
    )
    sessions_dir = store.root / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "sess_001.json").write_text(
        json.dumps({"id": "sess_001", "runId": "run_001", "task": "Explore", "intentId": "i1"}),
        encoding="utf-8",
    )
    (sessions_dir / "sess_002.json").write_text(
        json.dumps({"id": "sess_002", "runId": "run_001", "task": "Bootstrap"}),
        encoding="utf-8",
    )

    async with _client(tmp_path) as client:
        every = await _post(client, "ListSessions", {"runId": "run_001"})
        only_i1 = await _post(client, "ListSessions", {"runId": "run_001", "intentId": "i1"})
        none = await _post(client, "ListSessions", {"runId": "run_404"})

    assert [session["id"] for session in every.json().get("sessions", [])] == [
        "sess_001",
        "sess_002",
    ]
    assert [session["id"] for session in only_i1.json().get("sessions", [])] == ["sess_001"]
    assert none.status_code == 404


async def test_pinned_run_serves_graph_fact_events_sessions(tmp_path: Path) -> None:
    run_dir = _write_ui_run(tmp_path, "demo")

    async with _ui_client(tmp_path, static_dir=None, run_dir=run_dir) as client:
        graph = await _post(client, "GetRunGraph", {"runId": "demo"})
        wrong = await _post(client, "GetRunGraph", {"runId": "other"})
        fact = await _post(client, "GetFactDetail", {"runId": "demo", "factId": "goal"})
        events = await _post(client, "ListEvents", {"runId": "demo"})
        sessions = await _post(client, "ListSessions", {"runId": "demo"})

    assert graph.json()["graph"]["run"]["status"] == "completed"
    assert graph.json()["graph"]["eventCount"] == 2
    assert wrong.status_code == 404
    assert fact.json()["fact"]["kind"] == "goal"
    assert len(events.json()["events"]) == 2
    assert sessions.json().get("sessions", []) == []


async def test_projects_list_and_get(tmp_path: Path) -> None:
    ProjectRegistry(tmp_path / "projects", tmp_path / "runs").write(Project(id="p", name="P"))

    async with _client(tmp_path) as client:
        listed = await _post(client, "ListProjects", {})
        found = await _post(client, "GetProject", {"projectId": "p"})
        missing = await _post(client, "GetProject", {"projectId": "nope"})

    assert [project["id"] for project in listed.json()["projects"]] == ["p"]
    assert found.json()["project"]["name"] == "P"
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"


async def test_create_project_persists_and_lists(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        created = await _post(
            client,
            "CreateProject",
            {"id": "p", "name": "P", "description": "demo", "accent": "#abc"},
        )
        listed = await _post(client, "ListProjects", {})

    assert created.status_code == 200, created.text
    project = created.json()["project"]
    # proto3 JSON omits default scalars, so runCount/updatedAt only appear once non-zero.
    assert {k: project[k] for k in ("id", "name", "description", "accent")} == {
        "id": "p",
        "name": "P",
        "description": "demo",
        "accent": "#abc",
    }
    assert project.get("runCount", 0) == 0
    assert [p["id"] for p in listed.json()["projects"]] == ["p"]
    assert (tmp_path / "projects" / "p" / "project.json").is_file()


async def test_create_project_rejects_duplicate_and_invalid(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        first = await _post(client, "CreateProject", {"id": "p", "name": "P"})
        duplicate = await _post(client, "CreateProject", {"id": "p", "name": "P2"})
        bad_id = await _post(client, "CreateProject", {"id": "a/b", "name": "P"})
        empty_id = await _post(client, "CreateProject", {"id": "", "name": "P"})
        reserved = await _post(client, "CreateProject", {"id": "new", "name": "New"})
        blank_name = await _post(client, "CreateProject", {"id": "q", "name": "   "})

    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "already_exists"
    for response in (bad_id, empty_id, reserved, blank_name):
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_argument"
    # A rejected id leaves no project directory behind.
    assert not (tmp_path / "projects" / "a" / "b").exists()
    assert not (tmp_path / "projects" / "new").exists()
    assert not (tmp_path / "projects" / "q").exists()


async def test_create_project_enables_create_run(tmp_path: Path) -> None:
    ctx = _ctx_with(tmp_path, _providers(_bootstrap("A claim"), NO_REASON))
    async with _client_for(ctx) as client:
        created = await _post(client, "CreateProject", {"id": "fresh", "name": "Fresh"})
        assert created.status_code == 200
        response = await _post(
            client,
            "CreateRun",
            {
                "projectId": "fresh",
                "sourceType": "text",
                "sourceText": "doc A",
                "goal": "g",
                "auto": True,
            },
        )
        await ctx.scheduler.drain()

    assert response.status_code == 200, response.text
    assert response.json()["run"]["projectId"] == "fresh"


async def test_list_runs_filters_by_project(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")
    _write_run(tmp_path / "runs", "run_002", project_id="q")

    async with _client(tmp_path) as client:
        all_runs = await _post(client, "ListRuns", {})
        filtered = await _post(client, "ListRuns", {"projectId": "p"})
        project_runs = await _post(client, "ListProjectRuns", {"projectId": "q"})

    # Equal created_at: the run_id-descending tie-break decides.
    assert [run["id"] for run in all_runs.json()["runs"]] == ["run_002", "run_001"]
    assert [run["id"] for run in filtered.json()["runs"]] == ["run_001"]
    assert [run["id"] for run in project_runs.json()["runs"]] == ["run_002"]


async def test_list_runs_orders_by_created_at_desc(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p", at="2026-03-01T00:00:0{}")
    _write_run(tmp_path / "runs", "run_002", project_id="p", at="2026-01-01T00:00:0{}")
    _write_run(tmp_path / "runs", "run_003", project_id="p", at="2026-02-01T00:00:0{}")

    async with _client(tmp_path) as client:
        response = await _post(client, "ListProjectRuns", {"projectId": "p"})

    # Newest first regardless of run_id order (dashboard.md §4.1).
    assert [run["id"] for run in response.json()["runs"]] == ["run_001", "run_003", "run_002"]


# --------------------------------------------------------------- C3b: CreateRun


async def test_create_run_persists_input_and_is_readable(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _bootstrap("Copilot cut task time by 55%"), NO_REASON)

    async with _client_for(ctx) as client:
        run = await _create_run(client, auto=True)
        # CreateRun waits only for PROJECT: the run is already readable at "running".
        assert run["id"] == "run_001"
        assert run["projectId"] == "p"
        assert run["status"] == "running"
        assert run["title"] == "Copilot cut task time by 55%."

        await ctx.scheduler.wait("run_001")
        detail = (await _post(client, "GetRun", {"runId": "run_001"})).json()["runDetail"]
        await ctx.scheduler.drain()

    assert detail["events"][0]["type"] == "PROJECT"
    assert detail["origin"]["kind"] == "origin"
    assert [fact["role"] for fact in detail["facts"]] == ["main-claim"]
    assert detail["intents"]

    store = RunStore(tmp_path / "runs" / "run_001")
    assert (store.input_dir / "document.md").read_text(encoding="utf-8").startswith("Copilot")
    assert store.run_json_path.is_file()
    meta = store.read_run_meta()
    assert meta is not None and meta["id"] == "run_001" and meta["project_id"] == "p"


async def test_create_run_freezes_non_secret_runtime_config(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _bootstrap("A claim"), NO_REASON)
    async with _client_for(ctx) as client:
        await _create_run(client, auto=True)
        await ctx.scheduler.wait("run_001")

    meta = RunStore(tmp_path / "runs" / "run_001").read_run_meta()
    assert meta is not None
    runtime = meta["runtime"]
    assert runtime["worker"]["execution"] == "in-process"
    assert runtime["worker"]["container_scope"] == "per-call"
    assert "OPENAI_API_KEY" not in str(runtime)


async def test_create_run_requires_an_existing_project(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _bootstrap("A claim"))
    async with _client_for(ctx) as client:
        response = await _post(
            client,
            "CreateRun",
            {"projectId": "nope", "sourceType": "text", "sourceText": "x", "goal": "g"},
        )
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_create_run_rejects_unsupported_input(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _bootstrap("A claim"))
    base = {"projectId": "p", "sourceType": "text", "sourceText": "x", "goal": "g"}
    async with _client_for(ctx) as client:
        url = await _post(client, "CreateRun", {**base, "sourceType": "url"})
        empty = await _post(client, "CreateRun", {**base, "sourceText": "   "})
        no_goal = await _post(client, "CreateRun", {**base, "goal": ""})
        relation = await _post(client, "CreateRun", {**base, "analysis": "relation"})
        bad_wall = await _post(client, "CreateRun", {**base, "maxWall": "soon"})

    for response in (url, empty, no_goal, relation, bad_wall):
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_argument"


async def test_add_hint_appends_event(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _bootstrap("A claim"), NO_REASON)
    async with _client_for(ctx) as client:
        await _create_run(client, auto=True)
        await ctx.scheduler.wait("run_001")
        response = await _post(
            client, "AddHint", {"runId": "run_001", "text": "check the confidence interval"}
        )
        await ctx.scheduler.drain()

    assert response.status_code == 200
    hint = response.json()["hint"]
    assert hint["id"] == "h1"
    assert hint["author"] == "human"
    assert hint["text"] == "check the confidence interval"

    events = RunStore(tmp_path / "runs" / "run_001").read_events()
    hints = [event for event in events if event.type == "HINT"]
    assert len(hints) == 1
    assert hints[0].payload["hint"]["text"] == "check the confidence interval"


async def test_add_hint_missing_run_reports_not_found(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    async with _client_for(ctx) as client:
        response = await _post(client, "AddHint", {"runId": "run_404", "text": "x"})
    assert response.status_code == 404


async def test_submit_human_input_approves_gate_a(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _bootstrap("A claim"), NO_REASON)
    async with _client_for(ctx) as client:
        await _create_run(client)  # auto defaults to [hitl].auto = False
        await ctx.scheduler.wait("run_001")

        paused = (await _post(client, "GetRun", {"runId": "run_001"})).json()["runDetail"]
        assert paused["run"]["status"] == "awaiting_human"
        assert paused["waitingFor"]["gate"] == "confirm-claim"

        response = await _post(
            client,
            "SubmitHumanInput",
            {"runId": "run_001", "gate": "confirm-claim", "decision": "approve"},
        )
        await ctx.scheduler.drain()

    assert response.status_code == 200
    assert response.json()["run"]["status"] == "running"
    events = RunStore(tmp_path / "runs" / "run_001").read_events()
    decisions = [event for event in events if event.type == "HUMAN_INPUT"]
    assert len(decisions) == 1
    assert decisions[0].payload["decision"] == "approve"


async def test_submit_human_input_reject_stops_run(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _bootstrap("A claim"), NO_REASON)
    async with _client_for(ctx) as client:
        await _create_run(client)
        await ctx.scheduler.wait("run_001")
        response = await _post(
            client,
            "SubmitHumanInput",
            {"runId": "run_001", "gate": "confirm-claim", "decision": "reject"},
        )
        await ctx.scheduler.drain()

    assert response.status_code == 200
    assert response.json()["run"]["status"] == "stopped"
    events = RunStore(tmp_path / "runs" / "run_001").read_events()
    assert "STOPPED" in [event.type for event in events]


async def test_submit_human_input_when_not_awaiting(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _bootstrap("A claim"), NO_REASON)
    async with _client_for(ctx) as client:
        await _create_run(client, auto=True)
        await ctx.scheduler.wait("run_001")
        response = await _post(
            client,
            "SubmitHumanInput",
            {"runId": "run_001", "gate": "confirm-claim", "decision": "approve"},
        )
        await ctx.scheduler.drain()

    assert response.status_code == 400
    assert response.json()["code"] == "failed_precondition"


async def test_submit_human_input_rejects_wrong_gate(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _bootstrap("A claim"))
    async with _client_for(ctx) as client:
        await _create_run(client)
        await ctx.scheduler.wait("run_001")
        response = await _post(
            client,
            "SubmitHumanInput",
            {"runId": "run_001", "gate": "arbitrate", "decision": "approve"},
        )
        await ctx.scheduler.drain()

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_argument"


async def test_submit_human_input_rejects_unknown_decision(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _bootstrap("A claim"))
    async with _client_for(ctx) as client:
        await _create_run(client)
        await ctx.scheduler.wait("run_001")
        response = await _post(
            client,
            "SubmitHumanInput",
            {"runId": "run_001", "gate": "confirm-claim", "decision": "maybe"},
        )
        await ctx.scheduler.drain()

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_argument"


async def test_create_run_returns_before_the_engine_finishes(tmp_path: Path) -> None:
    providers = Providers(
        worker=LocalWorker(model=_SlowModel(0.2, _bootstrap("A claim"))),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
    )
    ctx = _ctx_with(tmp_path, providers)

    async with _client_for(ctx) as client:
        run = await _create_run(client, auto=True)
        assert run["status"] == "running"
        # The engine is still inside Bootstrap: only PROJECT has been written.
        detail = (await _post(client, "GetRun", {"runId": "run_001"})).json()["runDetail"]
        assert [event["type"] for event in detail["events"]] == ["PROJECT"]
        await ctx.scheduler.drain()


async def test_concurrent_create_run_allocates_unique_ids(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _bootstrap("A claim"), NO_REASON)
    async with _client_for(ctx) as client:
        runs = await asyncio.gather(*(_create_run(client, auto=True) for _ in range(3)))
        await ctx.scheduler.drain()

    assert sorted(str(run["id"]) for run in runs) == ["run_001", "run_002", "run_003"]


async def test_create_run_records_budget_override_and_analysis(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _bootstrap("A claim"), NO_REASON)
    async with _client_for(ctx) as client:
        response = await _post(
            client,
            "CreateRun",
            {
                "projectId": "p",
                "sourceType": "text",
                "sourceText": "doc",
                "goal": "g",
                "auto": True,
                "maxSteps": 7,
                "maxWall": "3m",
                "maxCost": 1.5,
            },
        )
        assert response.status_code == 200
        await ctx.scheduler.wait("run_001")
        await ctx.scheduler.drain()

    meta = RunStore(tmp_path / "runs" / "run_001").read_run_meta()
    assert meta is not None
    assert meta["analysis"] == "provenance"
    assert meta["budget"] == {"max_steps": 7, "max_wall": "3m", "max_cost": 1.5}


# ------------------------------------------------------------------- M2: report


def _write_run_with_deviation(runs_dir: Path, run_id: str) -> None:
    store = RunStore(runs_dir / run_id)
    store.init_layout()
    store.write_run_meta({"id": run_id, "project_id": "p", "title": "T", "goal": "g"})
    at = "2026-01-01T00:00:0{}"
    store.append_event("PROJECT", {"origin": _ORIGIN, "goal": _GOAL}, at=at.format(0))
    store.append_event(
        "INTENT",
        {"intent": {"id": "i1", "type": "decompose", "from": "f1", "question": "q"}},
        at=at.format(1),
    )
    store.append_event("EXECUTE", {"intentId": "i1", "worker": "w", "model": "x"}, at=at.format(2))
    deviation = {
        "id": "d1",
        "kind": "deviation",
        "label": "wrong attribution",
        "subtitle": "severity=high \u00b7 confidence=0.90",
        "role": "none",
        "status": "flagged",
        "confidence": 0.9,
        "note": "note",
        "evidence": [
            {
                "id": "ev1",
                "quote": "55%",
                "sourceTitle": "Lab",
                "url": "https://example.com/lab",
                "locator": "p.1",
            }
        ],
    }
    store.append_event("CONCLUDE", {"intentId": "i1", "facts": [deviation]}, at=at.format(3))
    store.append_event("COMPLETE", {"verdict": "\u90e8\u5206\u504f\u5dee"}, at=at.format(4))


async def test_get_run_exposes_report_and_deviations(tmp_path: Path) -> None:
    _write_run_with_deviation(tmp_path / "runs", "run_001")

    async with _client(tmp_path) as client:
        response = await _post(client, "GetRun", {"runId": "run_001"})

    detail = response.json()["runDetail"]
    assert detail["deviations"][0]["id"] == "d1"
    assert detail["deviations"][0]["severity"] == "high"
    assert detail["report"]["verdict"] == "\u90e8\u5206\u504f\u5dee"
    assert detail["report"]["findings"][0]["nodeId"] == "d1"


async def test_submit_human_input_approves_gate_b(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs" / "run_001")
    store.init_layout()
    store.write_run_meta({"id": "run_001", "project_id": "p", "goal": "g"})
    at = "2026-01-01T00:00:0{}"
    store.append_event("PROJECT", {"origin": _ORIGIN, "goal": _GOAL}, at=at.format(0))
    store.append_event(
        "REQUEST_HUMAN", {"gate": "arbitrate", "question": "which source?"}, at=at.format(1)
    )

    ctx = _ctx(tmp_path, NO_REASON)  # the resumed Reason proposes nothing
    async with _client_for(ctx) as client:
        response = await _post(
            client,
            "SubmitHumanInput",
            {"runId": "run_001", "gate": "arbitrate", "decision": "approve"},
        )
        await ctx.scheduler.drain()

    assert response.status_code == 200
    events = RunStore(tmp_path / "runs" / "run_001").read_events()
    decisions = [event for event in events if event.type == "HUMAN_INPUT"]
    assert len(decisions) == 1
    assert decisions[0].payload["gate"] == "arbitrate"


async def test_get_run_malformed_deviation_reports_internal(tmp_path: Path) -> None:
    _write_run_with_deviation(tmp_path / "runs", "run_001")
    events_path = tmp_path / "runs" / "run_001" / "events.jsonl"
    events_path.write_text(
        events_path.read_text(encoding="utf-8").replace("severity=high", "no-severity"),
        encoding="utf-8",
    )

    async with _client(tmp_path) as client:
        response = await _post(client, "GetRun", {"runId": "run_001"})

    assert response.status_code == 500
    assert response.json()["code"] == "internal"


# --------------------------------------------------------------- C4: ui / static


def _write_ui_run(root: Path, name: str = "demo") -> Path:
    """A run directory with an event log but no run.json (like the sample)."""
    store = RunStore(root / name)
    store.init_layout()
    store.append_event(
        "PROJECT", {"origin": _ORIGIN, "goal": _GOAL}, at="2026-01-01T00:00:00+00:00"
    )
    store.append_event("COMPLETE", {"verdict": "ok"}, at="2026-01-01T00:00:01+00:00")
    return store.root


def _ui_client(tmp_path: Path, *, static_dir: Path | None, run_dir: Path | None = None):
    app = create_app(config=Config(), root=tmp_path, static_dir=static_dir, run_dir=run_dir)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_static_frontend_is_served_with_spa_fallback(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")

    async with _ui_client(tmp_path, static_dir=dist) as client:
        index = await client.get("/")
        deep_link = await client.get("/projects/p/runs/run_001")
        missing_asset = await client.get("/assets/missing.js")
        api = await _post(client, "ListProjects", {})

    assert index.status_code == 200
    assert "id=root" in index.text
    assert deep_link.status_code == 200
    assert "id=root" in deep_link.text
    assert missing_asset.status_code == 404  # a missing asset stays a 404, not the shell
    assert api.status_code == 200  # the API still routes under the static mount


async def test_static_does_not_leak_files(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("top-secret", encoding="utf-8")

    async with _ui_client(tmp_path, static_dir=dist) as client:
        escaped = await client.get("/../secret.txt")
        encoded = await client.get("/%2e%2e/secret.txt")

    assert "top-secret" not in escaped.text
    assert "top-secret" not in encoded.text


async def test_without_static_dir_root_is_not_index(tmp_path: Path) -> None:
    async with _ui_client(tmp_path, static_dir=None) as client:
        response = await client.get("/")
    assert response.status_code == 404


async def test_pinned_run_is_read_only(tmp_path: Path) -> None:
    run_dir = _write_ui_run(tmp_path, "demo")

    async with _ui_client(tmp_path, static_dir=None, run_dir=run_dir) as client:
        runs = await _post(client, "ListRuns", {})
        detail = await _post(client, "GetRun", {"runId": "demo"})
        missing = await _post(client, "GetRun", {"runId": "run_001"})
        projects = await _post(client, "ListProjects", {})
        project = await _post(client, "GetProject", {"projectId": "sample"})
        project_runs = await _post(client, "ListProjectRuns", {"projectId": "sample"})
        other_runs = await _post(client, "ListProjectRuns", {"projectId": "other"})
        create = await _post(
            client,
            "CreateRun",
            {"projectId": "sample", "sourceType": "text", "sourceText": "x", "goal": "g"},
        )
        hint = await _post(client, "AddHint", {"runId": "demo", "text": "hi"})
        human = await _post(
            client,
            "SubmitHumanInput",
            {"runId": "demo", "gate": "confirm-claim", "decision": "approve"},
        )
        new_project = await _post(client, "CreateProject", {"id": "x", "name": "X"})

    assert [run["id"] for run in runs.json()["runs"]] == ["demo"]
    assert detail.status_code == 200
    assert detail.json()["runDetail"]["run"]["status"] == "completed"
    assert missing.status_code == 404
    assert [project["id"] for project in projects.json()["projects"]] == ["sample"]
    assert project.json()["project"]["id"] == "sample"
    assert [run["id"] for run in project_runs.json()["runs"]] == ["demo"]
    assert other_runs.json().get("runs", []) == []
    assert create.status_code == 400
    assert create.json()["code"] == "failed_precondition"
    assert hint.status_code == 400
    assert human.status_code == 400
    assert new_project.status_code == 400
    assert new_project.json()["code"] == "failed_precondition"


async def test_pinned_run_uses_run_json_id(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "dir1")
    store.init_layout()
    store.write_run_meta({"id": "run_007", "project_id": "p"})
    store.append_event(
        "PROJECT", {"origin": _ORIGIN, "goal": _GOAL}, at="2026-01-01T00:00:00+00:00"
    )

    async with _ui_client(tmp_path, static_dir=None, run_dir=store.root) as client:
        by_id = await _post(client, "GetRun", {"runId": "run_007"})
        by_dir = await _post(client, "GetRun", {"runId": "dir1"})

    assert by_id.status_code == 200
    assert by_id.json()["runDetail"]["run"]["id"] == "run_007"
    assert by_dir.status_code == 404


async def test_lifespan_drains_background_runs(tmp_path: Path) -> None:
    providers = Providers(
        worker=LocalWorker(model=_SlowModel(0.05, _bootstrap("A claim"))),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
    )
    ProjectRegistry(tmp_path / "projects", tmp_path / "runs").write(Project(id="p", name="P"))
    app = create_app(
        config=Config(worker=WorkerConfig(execution="in-process", container_scope="per-call")),
        providers=providers,
        root=tmp_path,
    )

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        await _create_run(client, auto=True)  # still running at exit

    # The lifespan shutdown awaited the background task to completion.
    store = RunStore(tmp_path / "runs" / "run_001")
    types = [event.type for event in store.read_events()]
    assert "CONCLUDE" in types  # Bootstrap finished, not just PROJECT


def test_ui_command_runs_uvicorn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from originweave.cli import main

    run_dir = _write_ui_run(tmp_path, "demo")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ORIGINWEAVE_SERVER_URL", raising=False)
    captured: dict[str, object] = {}

    def fake_run(app: object, *, host: str, port: int, log_level: str) -> None:
        captured.update(app=app, host=host, port=port, log_level=log_level)

    monkeypatch.setattr("uvicorn.run", fake_run)

    assert main(["ui", "--run", str(run_dir), "--port", "0"]) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 0
    assert captured["app"] is not None


def test_ui_command_rejects_missing_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from originweave.cli import main

    monkeypatch.chdir(tmp_path)
    assert main(["ui", "--run", str(tmp_path / "nope")]) == 1


def test_ui_command_exports_the_server_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from originweave.cli import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ORIGINWEAVE_SERVER_URL", raising=False)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    assert main(["ui", "--port", "9999"]) == 0
    # The Pi search extension (M6 P4) reaches this server on the actual port.
    assert os.environ["ORIGINWEAVE_SERVER_URL"] == "http://127.0.0.1:9999"


# --------------------------------------------------------------- M6 P3: settings


def _settings_body(**worker_overrides: object) -> dict[str, object]:
    """A complete WorkerSettings body (UpdateSettings treats scalars as authoritative)."""
    worker: dict[str, object] = {
        "provider": "local",
        "maxConcurrency": 2,
        "tools": ["search"],
        "heartbeatInterval": "10s",
        "heartbeatTimeout": "1m",
        "heartbeatOnTimeout": "release",
        "budget": {"maxSteps": 20, "maxWall": "5m", "maxCost": 1.0},
        "llm": {"provider": "openai", "model": "some-model", "baseUrl": ""},
    }
    worker.update(worker_overrides)
    return {"worker": worker}


async def test_get_settings_returns_the_live_config(tmp_path: Path) -> None:
    ctx = _ctx_with(tmp_path, _providers())
    async with _client_for(ctx) as client:
        response = await _post(client, "GetSettings", {})

    assert response.status_code == 200
    settings = response.json()["settings"]["worker"]
    assert settings["provider"] == "pi"  # the default
    assert settings["maxConcurrency"] == 1
    assert settings["llm"]["provider"] == "openai"
    assert settings["budget"]["maxSteps"] == 60


async def test_update_settings_writes_config_and_applies(tmp_path: Path) -> None:
    ctx = _ctx_with(tmp_path, _providers())
    async with _client_for(ctx) as client:
        response = await _post(
            client, "UpdateSettings", {"settings": _settings_body(maxConcurrency=4)}
        )

    assert response.status_code == 200, response.text
    worker = response.json()["settings"]["worker"]
    assert worker["provider"] == "local"
    assert worker["maxConcurrency"] == 4
    assert worker["tools"] == ["search"]

    # Persisted to originweave.toml and reloadable as a valid config.
    path = tmp_path / "originweave.toml"
    assert path.is_file()
    reloaded = config_module.load(path)
    assert reloaded.worker.provider == "local"
    assert reloaded.worker.max_concurrency == 4
    assert reloaded.worker.tools == ("search",)
    # The live context was updated too, so subsequent runs use the new settings.
    assert ctx.config.worker.max_concurrency == 4


async def test_update_settings_rebuilds_providers(tmp_path: Path) -> None:
    seen: list[str] = []

    def factory(cfg: Config) -> Providers:
        seen.append(cfg.worker.provider)
        return _providers(NO_REASON)

    ProjectRegistry(tmp_path / "projects", tmp_path / "runs").write(Project(id="p", name="P"))
    ctx = ServerContext.build(
        config=Config(), providers=_providers(), root=tmp_path, providers_factory=factory
    )
    async with _client_for(ctx) as client:
        response = await _post(client, "UpdateSettings", {"settings": _settings_body()})

    assert response.status_code == 200
    assert seen == ["local"]
    assert ctx.providers.worker.name == "local"


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": "nope"},
        {"tools": ["not-a-tool"]},
        {"heartbeatInterval": "1m", "heartbeatTimeout": "30s"},  # interval >= timeout
        {"maxConcurrency": 0},
        {"budget": {"maxSteps": 0, "maxWall": "5m", "maxCost": 1.0}},
        {"llm": {"provider": "nope", "model": "m", "baseUrl": ""}},
        {"llm": {"provider": "openai", "model": "", "baseUrl": ""}},  # empty model
    ],
)
async def test_update_settings_rejects_invalid(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    ctx = _ctx_with(tmp_path, _providers())
    async with _client_for(ctx) as client:
        response = await _post(client, "UpdateSettings", {"settings": _settings_body(**overrides)})

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "invalid_argument"
    assert not (tmp_path / "originweave.toml").exists()


async def test_update_settings_requires_a_worker_block(tmp_path: Path) -> None:
    ctx = _ctx_with(tmp_path, _providers())
    async with _client_for(ctx) as client:
        response = await _post(client, "UpdateSettings", {"settings": {}})

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_argument"


async def test_pinned_settings_are_read_only(tmp_path: Path) -> None:
    run_dir = _write_ui_run(tmp_path, "demo")

    async with _ui_client(tmp_path, static_dir=None, run_dir=run_dir) as client:
        read = await _post(client, "GetSettings", {})
        write = await _post(client, "UpdateSettings", {"settings": _settings_body()})

    assert read.status_code == 200
    assert write.status_code == 400
    assert write.json()["code"] == "failed_precondition"


async def test_update_settings_falls_back_for_omitted_submessages(tmp_path: Path) -> None:
    ctx = _ctx_with(tmp_path, _providers())
    partial = {
        "worker": {
            "provider": "local",
            "maxConcurrency": 2,
            "tools": [],
            "heartbeatInterval": "10s",
            "heartbeatTimeout": "1m",
            "heartbeatOnTimeout": "fail",
        }
    }
    async with _client_for(ctx) as client:
        response = await _post(client, "UpdateSettings", {"settings": partial})

    assert response.status_code == 200, response.text
    reloaded = config_module.load(tmp_path / "originweave.toml")
    assert reloaded.worker.provider == "local"
    assert reloaded.worker.tools == ()
    assert reloaded.worker.heartbeat_on_timeout == "fail"
    # Omitted llm / budget sub-messages keep their previous values.
    assert reloaded.capability.model == Config().capability.model
    assert reloaded.worker.budget == Config().worker.budget
    # Unrelated sections survive the rewrite.
    assert reloaded.hitl == Config().hitl
    assert reloaded.capability.search == Config().capability.search
    assert reloaded.capability.prompt == Config().capability.prompt
    assert reloaded.run == Config().run
    assert reloaded.project == Config().project


# --------------------------------------------------------------- M6 P3b: Search


class _RecordingSearch:
    """A fake search provider that records its calls and can be made to fail."""

    name = "fake"

    def __init__(self, *, text: str = "", error: Exception | None = None) -> None:
        self._text = text
        self._error = error
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, num_results: int = 8) -> str:
        self.calls.append((query, num_results))
        if self._error is not None:
            raise self._error
        return self._text


def _ctx_with_search(tmp_path: Path, search: _RecordingSearch) -> ServerContext:
    providers = Providers(
        worker=LocalWorker(model=_FakeModel()), search=search, prompt=_FakePrompt()
    )
    return _ctx_with(tmp_path, providers)


async def test_search_returns_provider_text(tmp_path: Path) -> None:
    search = _RecordingSearch(text="[1] Copilot study ...")
    ctx = _ctx_with_search(tmp_path, search)
    async with _client_for(ctx) as client:
        response = await _post(client, "Search", {"query": "copilot productivity", "numResults": 3})

    assert response.status_code == 200, response.text
    assert response.json()["text"] == "[1] Copilot study ..."
    assert search.calls == [("copilot productivity", 3)]


async def test_search_defaults_to_eight_results(tmp_path: Path) -> None:
    search = _RecordingSearch(text="x")
    ctx = _ctx_with_search(tmp_path, search)
    async with _client_for(ctx) as client:
        response = await _post(client, "Search", {"query": "q"})

    assert response.status_code == 200
    assert search.calls == [("q", 8)]


@pytest.mark.parametrize(
    "body",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "q", "numResults": 0},
        {"query": "q", "numResults": 999},
    ],
)
async def test_search_rejects_bad_arguments(tmp_path: Path, body: dict[str, object]) -> None:
    search = _RecordingSearch(text="x")
    ctx = _ctx_with_search(tmp_path, search)
    async with _client_for(ctx) as client:
        response = await _post(client, "Search", body)

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_argument"
    assert search.calls == []  # the provider is never reached


async def test_search_provider_error_is_unavailable(tmp_path: Path) -> None:
    search = _RecordingSearch(error=ProviderError("rate limited"))
    ctx = _ctx_with_search(tmp_path, search)
    async with _client_for(ctx) as client:
        response = await _post(client, "Search", {"query": "q"})

    assert response.status_code == 503
    assert response.json()["code"] == "unavailable"


# --------------------------------------------------------------- M6 P3c: sessions


def _write_session(store: RunStore, session_id: str, **overrides: object) -> None:
    session: dict[str, object] = {
        "id": session_id,
        "runId": store.root.name,
        "worker": "worker-1",
        "task": "Explore",
        "intentId": "i1",
        "model": "fake",
        "input": {"system": "S", "user": "U"},
        "output": '{"facts": []}',
        "steps": [
            {"seq": 1, "kind": "turn-start", "text": "go", "ok": True},
            {"seq": 2, "kind": "tool-call", "name": "search", "text": "q"},
        ],
        "startedAt": "2026-01-01T00:00:00+00:00",
        "endedAt": "2026-01-01T00:00:01+00:00",
    }
    session.update(overrides)
    store.write_session(session_id, session)


async def test_get_run_exposes_sessions(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")
    store = RunStore(tmp_path / "runs" / "run_001")
    _write_session(store, "sess_001")

    async with _client(tmp_path) as client:
        response = await _post(client, "GetRun", {"runId": "run_001"})

    sessions = response.json()["runDetail"]["sessions"]
    assert len(sessions) == 1
    session = sessions[0]
    assert session["id"] == "sess_001"
    assert session["runId"] == "run_001"
    assert session["worker"] == "worker-1"
    assert session["task"] == "Explore"
    assert session["intentId"] == "i1"
    assert session["input"]["user"] == "U"
    assert session["output"] == '{"facts": []}'
    assert session["startedAt"] == "2026-01-01T00:00:00+00:00"
    assert [step["seq"] for step in session["steps"]] == [1, 2]
    assert session["steps"][1]["name"] == "search"
    assert session["steps"][0]["ok"] is True
    assert "ok" not in session["steps"][1]  # unset optional is omitted


async def test_get_run_sessions_are_sorted_by_id(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")
    store = RunStore(tmp_path / "runs" / "run_001")
    _write_session(store, "sess_002", task="Reason", intentId=None)
    _write_session(store, "sess_001")

    async with _client(tmp_path) as client:
        response = await _post(client, "GetRun", {"runId": "run_001"})

    sessions = response.json()["runDetail"]["sessions"]
    assert [session["id"] for session in sessions] == ["sess_001", "sess_002"]
    assert "intentId" not in sessions[1]  # omitted when null


async def test_get_run_without_sessions_returns_empty(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")
    # The run dir has a sessions/ directory (init_layout) but no snapshots.
    async with _client(tmp_path) as client:
        response = await _post(client, "GetRun", {"runId": "run_001"})

    assert response.json()["runDetail"].get("sessions", []) == []


async def test_get_run_malformed_session_reports_internal(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")
    sessions_dir = tmp_path / "runs" / "run_001" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "sess_001.json").write_text("not json", encoding="utf-8")

    async with _client(tmp_path) as client:
        response = await _post(client, "GetRun", {"runId": "run_001"})

    assert response.status_code == 500
    assert response.json()["code"] == "internal"


@pytest.mark.parametrize(
    "session",
    [
        {"id": "sess_001", "input": ["not", "an", "object"]},
        {"id": "sess_001", "steps": "not-a-list"},
        {"id": "sess_001", "steps": [{"seq": "abc"}]},
        {"id": "sess_001", "steps": [42]},
    ],
)
async def test_get_run_structurally_bad_session_reports_internal(
    tmp_path: Path, session: dict[str, object]
) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")
    store = RunStore(tmp_path / "runs" / "run_001")
    store.write_session("sess_001", session)

    async with _client(tmp_path) as client:
        response = await _post(client, "GetRun", {"runId": "run_001"})

    assert response.status_code == 500, response.text
    assert response.json()["code"] == "internal"


# ----------------------------------------------------- M1c-2b 2b-5 end-to-end


async def test_end_to_end_create_run_to_scorecard(tmp_path: Path) -> None:
    """Full path with a fake provider: CreateRun → Gate A → verify → COMPLETE + report.md."""
    bootstrap = json.dumps(
        {
            "facts": [
                {
                    "label": "Copilot cut task time by 55%",
                    "kind": "fact",
                    "role": "main-claim",
                    "status": "open",
                    "confidence": 0.6,
                }
            ],
            "intents": [],
            "complete": None,
        }
    )
    reason_decompose = json.dumps(
        {
            "facts": [],
            "intents": [{"type": "decompose", "from": "f1", "question": "Split f1."}],
            "complete": None,
        }
    )
    keep = json.dumps({"keep": [0], "drop": []})
    sub_claim = json.dumps(
        {
            "facts": [
                {
                    "label": "the 55% figure is well scoped",
                    "kind": "fact",
                    "role": "sub-claim",
                    "status": "open",
                    "confidence": 0.5,
                }
            ],
            "intents": [],
            "complete": None,
        }
    )
    reason_verify = json.dumps(
        {
            "facts": [],
            "intents": [{"type": "verify", "from": "f2", "question": "Compare f2."}],
            "complete": None,
        }
    )
    compare = json.dumps(
        {
            "facts": [
                {
                    "key": "cmp",
                    "label": "compare (facts x sources x goal)",
                    "kind": "compare",
                    "role": "none",
                    "status": "verified",
                    "confidence": 0.8,
                },
                {
                    "key": "dev1",
                    "label": "wrong attribution",
                    "kind": "deviation",
                    "role": "none",
                    "status": "flagged",
                    "confidence": 0.9,
                    "subtitle": "severity=high \u00b7 confidence=0.90",
                    "evidence": [
                        {
                            "quote": "55%",
                            "sourceTitle": "Lab study",
                            "url": "https://example.com/lab",
                            "locator": "p.1",
                        }
                    ],
                },
            ],
            "edges": [
                {"source": "f2", "target": "cmp", "relation": "dependency", "note": "verify"},
                {"source": "goal", "target": "dev1", "relation": "goal-derived", "note": "dev"},
            ],
            "intents": [],
            "complete": None,
        }
    )
    complete = json.dumps(
        {"facts": [], "intents": [], "complete": {"verdict": "\u90e8\u5206\u504f\u5dee"}}
    )

    ctx = _ctx(
        tmp_path,
        bootstrap,
        reason_decompose,
        keep,
        sub_claim,
        reason_verify,
        keep,
        compare,
        complete,
    )

    async with _client_for(ctx) as client:
        run = await _create_run(client)  # auto defaults to [hitl].auto = False
        run_id = str(run["id"])
        await ctx.scheduler.wait(run_id)

        paused = (await _post(client, "GetRun", {"runId": run_id})).json()["runDetail"]
        assert paused["run"]["status"] == "awaiting_human"
        assert paused["waitingFor"]["gate"] == "confirm-claim"

        approved = await _post(
            client,
            "SubmitHumanInput",
            {"runId": run_id, "gate": "confirm-claim", "decision": "approve"},
        )
        assert approved.status_code == 200, approved.text
        await ctx.scheduler.drain()

        detail = (await _post(client, "GetRun", {"runId": run_id})).json()["runDetail"]

    assert detail["run"]["status"] == "completed"
    kinds = [fact["kind"] for fact in detail["facts"]]
    assert "compare" in kinds
    assert "deviation" in kinds
    assert detail["report"]["verdict"] == "\u90e8\u5206\u504f\u5dee"
    assert detail["deviations"][0]["severity"] == "high"
    assert (tmp_path / "runs" / run_id / "report.md").is_file()


async def test_pause_and_resume_run(tmp_path: Path) -> None:
    """M3b: PauseRun stops a running run at a boundary; ResumeRun continues it."""
    providers = Providers(
        worker=LocalWorker(model=_SlowModel(0.2, _bootstrap("A claim"), NO_REASON, NO_REASON)),
        search=_FakeSearch(),
        prompt=_FakePrompt(),
    )
    ctx = _ctx_with(tmp_path, providers)
    async with _client_for(ctx) as client:
        run = await _create_run(client, auto=True)
        run_id = str(run["id"])

        paused = await _post(client, "PauseRun", {"runId": run_id})
        assert paused.status_code == 200, paused.text
        assert paused.json()["run"]["status"] == "paused"

        resumed = await _post(client, "ResumeRun", {"runId": run_id})
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["run"]["status"] == "running"
        await ctx.scheduler.drain()

    types = [event.type for event in RunStore(tmp_path / "runs" / run_id).read_events()]
    assert "PAUSED" in types and "RESUMED" in types
