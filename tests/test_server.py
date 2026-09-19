"""ASGI smoke tests for the Connect server (M1c-1 C1).

Skipped when the generated ``originweave.v1`` code is absent (i.e. `make proto` has
not been run); CI generates it first, so the tests run there.
"""

from __future__ import annotations

import json

import httpx
import pytest

pytest.importorskip("originweave.v1.originweave_connect")

from originweave.server.app import create_app  # noqa: E402

SERVICE = "/originweave.v1.OriginweaveService"
JSON_HEADERS = {"Content-Type": "application/json"}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    )


async def test_list_projects_is_empty() -> None:
    async with _client() as client:
        response = await client.post(
            f"{SERVICE}/ListProjects", content=json.dumps({}), headers=JSON_HEADERS
        )

    assert response.status_code == 200
    # proto3 JSON omits empty repeated fields, so an empty registry serializes as {}.
    assert response.json() == {}


async def test_unimplemented_rpc_reports_unimplemented() -> None:
    async with _client() as client:
        response = await client.post(
            f"{SERVICE}/GetRun",
            content=json.dumps({"runId": "run_001"}),
            headers=JSON_HEADERS,
        )

    assert response.status_code == 501
    assert response.json()["code"] == "unimplemented"


async def test_create_app_accepts_an_injected_service() -> None:
    from originweave.server.service import Service

    app = create_app(service=Service())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"{SERVICE}/ListProjects", content=json.dumps({}), headers=JSON_HEADERS
        )

    assert response.status_code == 200
