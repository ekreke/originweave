"""ASGI tests for the Connect server (M1c-1).

Skipped when the generated ``originweave.v1`` code is absent (i.e. `make proto` has
not been run); CI generates it first, so the tests run there.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

pytest.importorskip("originweave.v1.originweave_connect")

from originweave.config import Config  # noqa: E402
from originweave.persistence import Project, ProjectRegistry  # noqa: E402
from originweave.server import ServerContext, create_app  # noqa: E402
from originweave.server.service import Service  # noqa: E402
from originweave.store import RunStore  # noqa: E402

SERVICE = "/originweave.v1.OriginweaveService"
JSON_HEADERS = {"Content-Type": "application/json"}

_ORIGIN = {"id": "origin", "kind": "origin", "label": "Document A"}
_GOAL = {"id": "goal", "kind": "goal", "label": "Every sub-claim is sourced"}


def _client(root: Path) -> httpx.AsyncClient:
    # An explicit config keeps the test independent of any originweave.toml in CWD.
    app = create_app(config=Config(), root=root)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


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


async def test_unimplemented_rpc_reports_unimplemented(tmp_path: Path) -> None:
    # CreateRun is wired in C3b; until then it inherits the UNIMPLEMENTED default.
    async with _client(tmp_path) as client:
        response = await _post(client, "CreateRun", {})

    assert response.status_code == 501
    assert response.json()["code"] == "unimplemented"


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
