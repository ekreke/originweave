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
    app = create_app(config=Config(), providers=providers, root=tmp_path)

    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        await _create_run(client, auto=True)  # still running at exit

    # The lifespan shutdown awaited the background task to completion.
    store = RunStore(tmp_path / "runs" / "run_001")
    types = [event.type for event in store.read_events()]
    assert "CONCLUDE" in types  # Bootstrap finished, not just PROJECT


def test_ui_command_runs_uvicorn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from originweave.cli import main

    run_dir = _write_ui_run(tmp_path, "demo")
    monkeypatch.chdir(tmp_path)
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

