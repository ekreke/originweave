from __future__ import annotations

from pathlib import Path

import pytest

from originweave import config
from originweave.capabilities import (
    CachedPrompt,
    CachedSearch,
    CacheMissError,
    CapabilityError,
    MissingCredentialError,
    ProviderUnavailableError,
    RecordingPrompt,
    RecordingSearch,
    ResponseCache,
    SearchResult,
    build_prompt,
    build_search,
    get_prompt,
    get_search,
    request_key,
)


class _FakeSearch:
    name = "fake"

    def search(self, query: str, *, limit: int = 10) -> list[SearchResult]:
        return [SearchResult(title="t", url="https://example.org", snippet="s")]


class _FakeExa(_FakeSearch):
    name = "exa"


def test_get_search_returns_provider() -> None:
    assert get_search("exa").name == "exa"
    assert get_search("parallel").name == "parallel"


def test_get_search_rejects_unknown() -> None:
    with pytest.raises(CapabilityError):
        get_search("google")


def test_exa_requires_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    with pytest.raises(MissingCredentialError):
        get_search("exa").search("q")


def test_exa_with_credential_is_not_live_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXA_API_KEY", "secret")
    with pytest.raises(ProviderUnavailableError):
        get_search("exa").search("q")


def test_local_prompt_reads_directory(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "claim.txt").write_text("extract claims\n", encoding="utf-8")
    provider = get_prompt("local", directory=prompts)
    assert provider.get("claim").text == "extract claims"


def test_local_prompt_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        get_prompt("local", directory=tmp_path).get("absent")


def test_get_prompt_rejects_unknown() -> None:
    with pytest.raises(CapabilityError):
        get_prompt("openai")


def test_request_key_is_order_insensitive_but_param_sensitive() -> None:
    a = request_key("exa", "search", {"query": "q", "limit": 10})
    b = request_key("exa", "search", {"limit": 10, "query": "q"})
    c = request_key("exa", "search", {"query": "q", "limit": 5})
    assert a == b
    assert a != c


def test_recording_then_replay_roundtrip(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "capabilities")
    live = RecordingSearch(_FakeSearch(), cache).search("hello", limit=3)
    replayed = CachedSearch("fake", cache).search("hello", limit=3)
    assert replayed == live
    assert cache.path_for("fake", "search", {"query": "hello", "limit": 3}).is_file()


def test_cached_search_miss_raises(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "capabilities")
    with pytest.raises(CacheMissError):
        CachedSearch("fake", cache).search("absent")


def test_cache_write_records_metadata(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "capabilities")
    params = {"query": "q", "limit": 1}
    path = cache.write("exa", "search", params, [{"title": "t", "url": "u"}])
    record = cache.read("exa", "search", params)
    assert record is not None
    assert record["provider"] == "exa"
    assert record["op"] == "search"
    assert record["params"] == params
    assert record["response"] == [{"title": "t", "url": "u"}]
    assert "recordedAt" in record
    assert path.parent.name == "exa"


def _cfg(*, live: bool) -> config.Config:
    return config.Config(live=config.LiveConfig(enabled=live))


def test_build_search_offline_replays_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = ResponseCache(tmp_path / "capabilities")
    RecordingSearch(_FakeExa(), cache).search("hello", limit=2)

    import socket

    def _no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted during offline replay")

    monkeypatch.setattr(socket, "socket", _no_network)

    provider = build_search(_cfg(live=False), cache)
    assert isinstance(provider, CachedSearch)
    assert provider.search("hello", limit=2) == [
        SearchResult(title="t", url="https://example.org", snippet="s")
    ]


def test_build_search_live_records(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "capabilities")
    assert isinstance(build_search(_cfg(live=True), cache), RecordingSearch)


def test_build_prompt_selects_replay_or_record(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "capabilities")
    assert isinstance(build_prompt(_cfg(live=False), cache), CachedPrompt)
    assert isinstance(build_prompt(_cfg(live=True), cache), RecordingPrompt)
