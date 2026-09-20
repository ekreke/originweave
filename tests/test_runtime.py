"""M3a tests: container-per-worker runtime (no real Docker; fakes + MockTransport)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx
import pytest

from originweave.blackboard import Board, Fact
from originweave.capabilities.base import CapabilityError, PromptTemplate
from originweave.capabilities.worker import LocalWorker
from originweave.config import Config, ConfigError, WorkerConfig
from originweave.runtime import ContainerHandle, ContainerManager, ContainerWorker
from originweave.runtime import container as container_module
from originweave.runtime import runner as runner_module
from originweave.server.context import Providers, ServerContext


class _FakeModel:
    name = "fake"

    async def complete(self, messages: Sequence[object]) -> str:
        return '{"facts": [], "intents": [], "complete": null}'


class _NoSearch:
    name = "fake"

    async def search(self, query: str, *, num_results: int = 8) -> str:
        return ""


class _FakePrompt:
    name = "fake"

    async def get(self, name: str) -> PromptTemplate:
        return PromptTemplate(name=name, text=name.upper())


def _providers() -> Providers:
    return Providers(
        worker=LocalWorker(model=_FakeModel()), search=_NoSearch(), prompt=_FakePrompt()
    )


def _board() -> Board:
    return Board(
        origin=Fact.from_dict({"id": "origin", "kind": "origin", "label": "A"}),
        goal=Fact.from_dict({"id": "goal", "kind": "goal", "label": "G"}),
    )


def _container_config() -> Config:
    return Config(worker=WorkerConfig(execution="container"))


# --------------------------------------------------------------------- config


def test_worker_execution_defaults_to_in_process() -> None:
    cfg = Config()
    assert cfg.worker.execution == "in-process"
    assert cfg.worker.image == "originweave-runtime:latest"
    assert cfg.to_dict()["worker"]["execution"] == "in-process"


def test_worker_execution_rejects_unknown_value() -> None:
    with pytest.raises(ConfigError, match="worker.execution"):
        Config(worker=WorkerConfig(execution="vm")).validate()


# --------------------------------------------------------------- container manager


async def test_container_manager_spawns_mounts_and_reaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    async def fake_run(argv: list[str], *, check: bool = True) -> str:
        calls.append(argv)
        if argv[1] == "run":
            return "cid-abc\n"
        if argv[1] == "port":
            return "127.0.0.1:32768\n"
        return ""

    monkeypatch.setattr(container_module, "_run_command", fake_run)
    manager = ContainerManager(image="img:latest")

    handle = await manager.spawn(run_dir=tmp_path, env={"ORIGINWEAVE_MODEL": "m"})
    assert handle.container_id == "cid-abc"
    assert handle.base_url == "http://127.0.0.1:32768"

    run_argv = calls[0]
    assert run_argv[0] == "docker"
    assert run_argv[-1] == "img:latest"
    assert f"{tmp_path}:{tmp_path}" in run_argv
    assert "-e" in run_argv and "ORIGINWEAVE_MODEL=m" in run_argv

    await manager.remove(handle)
    assert calls[-1][:3] == ["docker", "rm", "-f"]


async def test_container_manager_reports_a_missing_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_run(argv: list[str], *, check: bool = True) -> str:
        raise container_module.ContainerError(f"{argv[0]!r} not found on PATH")

    monkeypatch.setattr(container_module, "_run_command", fake_run)
    with pytest.raises(container_module.ContainerError, match="not found"):
        await ContainerManager(image="img:latest").spawn(run_dir=tmp_path, env={})


async def test_container_manager_reaps_when_port_lookup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    async def fake_run(argv: list[str], *, check: bool = True) -> str:
        calls.append(argv)
        if argv[1] == "run":
            return "cid-x\n"
        if argv[1] == "port":
            raise container_module.ContainerError("no port")
        return ""

    monkeypatch.setattr(container_module, "_run_command", fake_run)
    with pytest.raises(container_module.ContainerError):
        await ContainerManager(image="img:latest").spawn(run_dir=tmp_path, env={})
    assert ["docker", "rm", "-f", "cid-x"] in calls  # leaked container is removed


# --------------------------------------------------------------- container worker


class _FakeManager:
    def __init__(self) -> None:
        self.spawned: list[Path] = []
        self.removed: list[str] = []

    async def spawn(self, *, run_dir: Path, env: Mapping[str, str]) -> ContainerHandle:
        self.spawned.append(run_dir)
        return ContainerHandle(container_id="cid-1", base_url="http://worker.test")

    async def remove(self, handle: ContainerHandle) -> None:
        self.removed.append(handle.container_id)


def _transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/run":
            return httpx.Response(
                200,
                json={
                    "text": '{"facts": [], "intents": [], "complete": null}',
                    "input": {"system": "S", "user": "U"},
                    "steps": [{"seq": 1, "kind": "turn-start"}],
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _docker_ready() -> bool:
    """True when Docker is up and the runtime image has been built (`make image`)."""
    if shutil.which("docker") is None:
        return False
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        return False
    return (
        subprocess.run(
            ["docker", "image", "inspect", "originweave-runtime:latest"],
            capture_output=True,
        ).returncode
        == 0
    )


@pytest.mark.skipif(not _docker_ready(), reason="needs Docker + `make image`")
async def test_real_container_serves_health(tmp_path: Path) -> None:
    """Real end-to-end: `docker run` the runtime image, poll /health, then reap it."""
    manager = ContainerManager(image="originweave-runtime:latest")
    handle = await manager.spawn(
        run_dir=tmp_path,
        env={"ORIGINWEAVE_WORKER_PROVIDER": "local", "ORIGINWEAVE_MODEL": "m"},
    )
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            for _ in range(60):
                try:
                    if (await http.get(f"{handle.base_url}/health")).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
            else:
                pytest.fail("container never became healthy")
    finally:
        await manager.remove(handle)


async def test_container_worker_executes_and_reaps(tmp_path: Path) -> None:
    manager = _FakeManager()
    worker = ContainerWorker(
        manager=manager,  # type: ignore[arg-type]
        run_dir=tmp_path,
        env={"ORIGINWEAVE_MODEL": "a-model"},
        transport=_transport(),
    )

    reply = await worker.run("Reason", PromptTemplate(name="reason", text="REASON"), _board())

    assert reply.text.startswith('{"facts"')
    assert reply.input == {"system": "S", "user": "U"}
    assert reply.steps[0].kind == "turn-start"
    assert manager.spawned == [tmp_path]  # the run dir was mounted
    assert manager.removed == ["cid-1"]  # reclaimed even on success
    assert worker.model == "a-model"


async def test_container_worker_reaps_when_the_task_fails(tmp_path: Path) -> None:
    manager = _FakeManager()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(500, text="boom")

    worker = ContainerWorker(
        manager=manager,  # type: ignore[arg-type]
        run_dir=tmp_path,
        env={},
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(container_module.ContainerError):
        await worker.run("Reason", PromptTemplate(name="reason", text="R"), _board())
    assert manager.removed == ["cid-1"]  # the container is reclaimed on failure too


# ----------------------------------------------------------------- server wiring


def test_worker_for_in_process_returns_the_shared_provider(tmp_path: Path) -> None:
    providers = _providers()
    ctx = ServerContext.build(config=Config(), providers=providers, root=tmp_path)
    assert ctx.container_manager is None
    assert ctx.worker_for(tmp_path / "run_001") is providers.worker


def test_worker_for_container_returns_a_container_worker(tmp_path: Path) -> None:
    ctx = ServerContext.build(config=_container_config(), root=tmp_path)
    assert ctx.container_manager is not None
    worker = ctx.worker_for(tmp_path / "run_001")
    assert isinstance(worker, ContainerWorker)


def test_worker_for_container_without_a_manager_raises(tmp_path: Path) -> None:
    ctx = ServerContext.build(config=_container_config(), root=tmp_path)
    ctx.container_manager = None
    with pytest.raises(CapabilityError, match="container manager"):
        ctx.worker_for(tmp_path / "run_001")


def test_worker_env_filters_search_and_reads_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://env-base")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    cfg = Config(
        worker=WorkerConfig(execution="container", provider="pi", tools=("search", "read"))
    )
    ctx = ServerContext.build(config=cfg, root=tmp_path)

    env = ctx._worker_env()
    assert env["ORIGINWEAVE_WORKER_TOOLS"] == "read"  # search is not mounted in-container
    assert env["ORIGINWEAVE_MODEL_BASE_URL"] == "http://env-base"
    assert env["OPENAI_API_KEY"] == "secret"  # credentials come from the environment


def test_config_from_settings_preserves_execution_and_image() -> None:
    pb = pytest.importorskip("originweave.v1.originweave_pb2")
    from originweave.server.service import _config_from_settings

    base = Config(worker=WorkerConfig(execution="container", image="img:1"))
    settings = pb.Settings(
        worker=pb.WorkerSettings(
            provider="local",
            max_concurrency=2,
            tools=[],
            heartbeat_interval="15s",
            heartbeat_timeout="5m",
            heartbeat_on_timeout="release",
            llm=pb.LlmSettings(provider="openai", model="m", base_url=""),
            budget=pb.WorkerBudget(max_steps=5, max_wall="1m", max_cost=1.0),
        )
    )

    result = _config_from_settings(base, settings)
    assert result.worker.execution == "container"  # not reset by a settings update
    assert result.worker.image == "img:1"
    assert result.worker.provider == "local"


# --------------------------------------------------------------------- runner


def test_runner_builds_the_configured_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORIGINWEAVE_WORKER_PROVIDER", "local")
    monkeypatch.setenv("ORIGINWEAVE_MODEL", "m")
    assert isinstance(runner_module.build_container_worker(), LocalWorker)


async def test_runner_health_and_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner_module, "build_container_worker", lambda: LocalWorker(model=_FakeModel())
    )
    app = runner_module.create_runner_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://runner"
    ) as client:
        assert (await client.get("/health")).status_code == 200
        response = await client.post(
            "/run",
            json={
                "task": "Reason",
                "template": "R",
                "board": _board().to_dict(),
                "extra": {},
            },
        )
    assert response.status_code == 200
    assert response.json()["text"].startswith('{"facts"')
