from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from originweave import config
from originweave.capabilities import (
    CapabilityError,
    ChatMessage,
    ExaSearch,
    MissingCredentialError,
    OpenAIModel,
    ParallelSearch,
    ProviderError,
    build_model,
    build_prompt,
    build_search,
    get_model,
    get_prompt,
    get_search,
)
from originweave.capabilities.search import EXA_URL, PARALLEL_URL, parse_response


def _mcp_payload(text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}}


def _mcp_handler(
    text: str, *, capture: dict[str, Any], status: int = 200
) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        capture["url"] = str(request.url)
        capture["headers"] = dict(request.headers)
        capture["body"] = json.loads(request.content)
        return httpx.Response(status, json=_mcp_payload(text))

    return handler


def _chat_handler(content: str, *, capture: dict[str, Any], status: int = 200) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        capture["url"] = str(request.url)
        capture["headers"] = dict(request.headers)
        capture["body"] = json.loads(request.content)
        return httpx.Response(
            status, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
        )

    return handler


# --------------------------------------------------------------------- registry


def test_get_search_returns_provider() -> None:
    assert get_search("exa").name == "exa"
    assert get_search("parallel").name == "parallel"


def test_get_search_rejects_unknown() -> None:
    with pytest.raises(CapabilityError):
        get_search("google")


def test_get_model_returns_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    provider = get_model("openai", model="m", base_url="https://api.example/v1")
    assert isinstance(provider, OpenAIModel)
    assert provider.model == "m"
    assert provider.base_url == "https://api.example/v1"


def test_get_model_rejects_unknown() -> None:
    with pytest.raises(CapabilityError):
        get_model("anthropic", model="m", base_url="https://api.example/v1")


def test_get_prompt_rejects_unknown() -> None:
    with pytest.raises(CapabilityError):
        get_prompt("openai")


async def test_local_prompt_reads_directory(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "claim.txt").write_text("extract claims\n", encoding="utf-8")
    provider = get_prompt("local", directory=prompts)
    template = await provider.get("claim")
    assert template.text == "extract claims"


async def test_local_prompt_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        await get_prompt("local", directory=tmp_path).get("absent")


def _cfg() -> config.Config:
    return config.Config()


def test_build_helpers_select_configured_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = _cfg()
    assert isinstance(build_search(cfg), ExaSearch)
    assert build_prompt(cfg).name == "local"
    assert isinstance(build_model(cfg), OpenAIModel)


# ------------------------------------------------------------------- exa search


async def test_exa_search_calls_free_mcp_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    captured: dict[str, Any] = {}
    client = httpx.AsyncClient(transport=httpx.MockTransport(_mcp_handler("ctx", capture=captured)))
    try:
        provider = ExaSearch(client=client)
        text = await provider.search("who is x", num_results=3)
    finally:
        await client.aclose()

    assert text == "ctx"
    assert captured["url"] == EXA_URL
    assert captured["headers"]["accept"] == "application/json, text/event-stream"
    assert captured["headers"]["user-agent"].startswith("originweave/")
    body = captured["body"]
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    assert body["method"] == "tools/call"
    assert body["params"]["name"] == "web_search_exa"
    args = body["params"]["arguments"]
    assert args["query"] == "who is x"
    assert args["numResults"] == 3
    assert args["type"] == "auto"
    assert args["livecrawl"] == "fallback"


async def test_exa_search_appends_api_key_when_present() -> None:
    captured: dict[str, Any] = {}
    client = httpx.AsyncClient(transport=httpx.MockTransport(_mcp_handler("ctx", capture=captured)))
    try:
        provider = ExaSearch(api_key="secret", client=client)
        await provider.search("q")
    finally:
        await client.aclose()
    assert captured["url"] == f"{EXA_URL}?exaApiKey=secret"


# -------------------------------------------------------------- parallel search


async def test_parallel_search_uses_bearer_and_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PARALLEL_API_KEY", "ptoken")
    captured: dict[str, Any] = {}
    client = httpx.AsyncClient(transport=httpx.MockTransport(_mcp_handler("ctx", capture=captured)))
    try:
        provider = ParallelSearch(client=client)
        await provider.search("q")
    finally:
        await client.aclose()

    assert captured["url"] == PARALLEL_URL
    assert captured["headers"]["authorization"] == "Bearer ptoken"
    assert captured["headers"]["user-agent"].startswith("originweave/")
    body = captured["body"]
    assert body["method"] == "tools/call"
    assert body["params"]["name"] == "web_search"
    assert body["params"]["arguments"]["objective"] == "q"
    assert body["params"]["arguments"]["search_queries"] == ["q"]


async def test_parallel_search_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    captured: dict[str, Any] = {}
    client = httpx.AsyncClient(transport=httpx.MockTransport(_mcp_handler("ctx", capture=captured)))
    try:
        await ParallelSearch(client=client).search("q")
    finally:
        await client.aclose()
    assert "authorization" not in captured["headers"]


# ---------------------------------------------------------------- search errors


def test_parse_response_plain_json() -> None:
    body = json.dumps(_mcp_payload("results"))
    assert parse_response(body) == "results"


def test_parse_response_sse_frames() -> None:
    body = f"event: message\ndata: {json.dumps(_mcp_payload('results'))}\n\n"
    assert parse_response(body) == "results"


def test_parse_response_ignores_garbage() -> None:
    assert parse_response("data: [DONE]\n\n") is None
    assert parse_response("not json") is None


async def test_search_http_error_raises_provider_error() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text="boom"))
    )
    try:
        with pytest.raises(ProviderError):
            await ExaSearch(client=client).search("q")
    finally:
        await client.aclose()


async def test_search_without_text_raises_provider_error() -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": ""}]}}
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    try:
        with pytest.raises(ProviderError):
            await ExaSearch(client=client).search("q")
    finally:
        await client.aclose()


async def test_search_connect_error_raises_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError):
            await ExaSearch(client=client).search("q")
    finally:
        await client.aclose()


# ---------------------------------------------------------------------- model


async def test_openai_model_completes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    captured: dict[str, Any] = {}
    client = httpx.AsyncClient(transport=httpx.MockTransport(_chat_handler("hi", capture=captured)))
    try:
        provider = OpenAIModel(model="m", base_url="https://api.example/v1", client=client)
        text = await provider.complete([ChatMessage(role="user", content="ping")])
    finally:
        await client.aclose()

    assert text == "hi"
    assert captured["url"] == "https://api.example/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer k"
    assert captured["body"]["model"] == "m"
    assert captured["body"]["messages"] == [{"role": "user", "content": "ping"}]


async def test_openai_model_base_url_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://override.example/v1/")
    captured: dict[str, Any] = {}
    client = httpx.AsyncClient(transport=httpx.MockTransport(_chat_handler("hi", capture=captured)))
    try:
        provider = OpenAIModel(model="m", base_url="https://api.example/v1", client=client)
        await provider.complete([ChatMessage(role="user", content="ping")])
    finally:
        await client.aclose()
    assert provider.base_url == "https://override.example/v1"
    assert captured["url"] == "https://override.example/v1/chat/completions"


async def test_openai_model_requires_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIModel(model="m", base_url="https://api.example/v1")
    with pytest.raises(MissingCredentialError):
        await provider.complete([ChatMessage(role="user", content="ping")])


async def test_openai_model_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(429, text="slow down"))
    )
    try:
        provider = OpenAIModel(model="m", base_url="https://api.example/v1", client=client)
        with pytest.raises(ProviderError):
            await provider.complete([ChatMessage(role="user", content="ping")])
    finally:
        await client.aclose()


async def test_openai_model_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        provider = OpenAIModel(model="m", base_url="https://api.example/v1", client=client)
        with pytest.raises(ProviderError):
            await provider.complete([ChatMessage(role="user", content="ping")])
    finally:
        await client.aclose()


async def test_openai_model_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    provider = OpenAIModel(model="m", base_url="")
    with pytest.raises(MissingCredentialError):
        await provider.complete([ChatMessage(role="user", content="ping")])
