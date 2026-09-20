"""ASGI tests for the Connect server (M1c-1).

Skipped when the generated ``originweave.v1`` code is absent (i.e. `make proto` has
not been run); CI generates it first, so the tests run there.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

pytest.importorskip("originweave.v1.originweave_connect")

from originweave.capabilities import PromptTemplate  # noqa: E402
from originweave.capabilities.worker import LocalWorker  # noqa: E402
from originweave.config import Config  # noqa: E402
from originweave.persistence import Project, ProjectRegistry  # noqa: E402
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
    return ServerContext.build(config=Config(), providers=providers, root=root)


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


def _write_run(runs_dir: Path, run_id: str, *, project_id: str, complete: bool = True) -> None:
    store = RunStore(runs_dir / run_id)
    store.init_layout()
    store.write_run_meta({"id": run_id, "project_id": project_id, "title": "T", "goal": "g"})
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


async def test_list_runs_filters_by_project(tmp_path: Path) -> None:
    _write_run(tmp_path / "runs", "run_001", project_id="p")
    _write_run(tmp_path / "runs", "run_002", project_id="q")

    async with _client(tmp_path) as client:
        all_runs = await _post(client, "ListRuns", {})
        filtered = await _post(client, "ListRuns", {"projectId": "p"})
        project_runs = await _post(client, "ListProjectRuns", {"projectId": "q"})

    assert [run["id"] for run in all_runs.json()["runs"]] == ["run_001", "run_002"]
    assert [run["id"] for run in filtered.json()["runs"]] == ["run_001"]
    assert [run["id"] for run in project_runs.json()["runs"]] == ["run_002"]


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
    store.append_event(
        "EXECUTE", {"intentId": "i1", "worker": "w", "model": "x"}, at=at.format(2)
    )
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
