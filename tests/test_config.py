from __future__ import annotations

from pathlib import Path

import pytest

from originweave import config


def test_default_values() -> None:
    cfg = config.Config()
    assert cfg.hitl.auto is False
    assert cfg.capability.search.provider == "exa"
    assert cfg.capability.prompt.provider == "local"
    assert cfg.capability.prompt.directory == "prompts"
    assert cfg.capability.model.provider == "openai"
    assert cfg.capability.model.model == "deepseek-v4.1-flash"
    assert cfg.capability.model.base_url == ""
    assert cfg.worker.provider == "pi"
    assert cfg.worker.max_concurrency == 1
    assert cfg.worker.tools == ()
    assert cfg.worker.budget.max_steps == 60
    assert cfg.worker.budget.max_wall == "10m"
    assert cfg.worker.budget.max_cost == 2.0
    assert cfg.run.dir == "runs"


def test_write_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    written = config.write_default(path)
    assert written == path
    assert config.load(path) == config.Config()


def test_write_refuses_overwrite_without_force(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    config.write_default(path)
    with pytest.raises(FileExistsError):
        config.write_default(path)
    assert config.write_default(path, force=True) == path


def test_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    assert config.load(tmp_path / "absent.toml") == config.Config()


def test_load_reads_overrides(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    path.write_text(
        """
[hitl]
auto = true
[capability.search]
provider = "parallel"
[capability.prompt]
provider = "langfuse"
directory = "p"
[capability.model]
provider = "openai"
model = "some-model"
base_url = "https://example.test/v1"
[worker.budget]
max_steps = 5
max_wall = "1m"
max_cost = 0.5
[run]
dir = "out"
""".lstrip(),
        encoding="utf-8",
    )
    cfg = config.load(path)
    assert cfg.hitl.auto is True
    assert cfg.capability.search.provider == "parallel"
    assert cfg.capability.prompt.provider == "langfuse"
    assert cfg.capability.prompt.directory == "p"
    assert cfg.capability.model.model == "some-model"
    assert cfg.capability.model.base_url == "https://example.test/v1"
    assert cfg.worker.budget.max_steps == 5
    assert cfg.worker.budget.max_cost == 0.5
    assert cfg.run.dir == "out"


def test_validate_rejects_unknown_search_provider() -> None:
    cfg = config.Config(
        capability=config.CapabilityConfig(search=config.SearchConfig(provider="nope"))
    )
    with pytest.raises(config.ConfigError):
        cfg.validate()


def test_validate_rejects_unknown_model_provider() -> None:
    cfg = config.Config(
        capability=config.CapabilityConfig(model=config.ModelConfig(provider="nope"))
    )
    with pytest.raises(config.ConfigError):
        cfg.validate()


def test_validate_rejects_unknown_worker_provider() -> None:
    cfg = config.Config(worker=config.WorkerConfig(provider="nope"))
    with pytest.raises(config.ConfigError):
        cfg.validate()


def test_validate_rejects_bad_worker_concurrency() -> None:
    cfg = config.Config(worker=config.WorkerConfig(max_concurrency=0))
    with pytest.raises(config.ConfigError):
        cfg.validate()


def test_validate_rejects_worker_concurrency_above_ceiling() -> None:
    over = config.MAX_WORKER_CONCURRENCY + 1
    cfg = config.Config(worker=config.WorkerConfig(max_concurrency=over))
    with pytest.raises(config.ConfigError) as excinfo:
        cfg.validate()
    assert "max_concurrency" in str(excinfo.value)


def test_validate_rejects_heartbeat_interval_not_below_timeout() -> None:
    cfg = config.Config(
        worker=config.WorkerConfig(heartbeat_interval="5m", heartbeat_timeout="30s")
    )
    with pytest.raises(config.ConfigError):
        cfg.validate()


def test_validate_rejects_unknown_heartbeat_on_timeout() -> None:
    cfg = config.Config(worker=config.WorkerConfig(heartbeat_on_timeout="explode"))
    with pytest.raises(config.ConfigError) as excinfo:
        cfg.validate()
    assert "heartbeat_on_timeout" in str(excinfo.value)


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("500ms", 0.5), ("5s", 5.0), ("10m", 600.0), ("2h", 7200.0), ("1d", 86400.0)],
)
def test_parse_duration(text: str, seconds: float) -> None:
    assert config.parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["10", "0s", "1w", "m", "1 m", "-5s"])
def test_parse_duration_rejects_bad_values(text: str) -> None:
    with pytest.raises(config.ConfigError):
        config.parse_duration(text)


def test_validate_rejects_unknown_worker_tool() -> None:
    cfg = config.Config(worker=config.WorkerConfig(tools=("teleport",)))
    with pytest.raises(config.ConfigError) as excinfo:
        cfg.validate()
    assert "teleport" in str(excinfo.value)


def test_load_reads_worker_overrides(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    path.write_text(
        """
[worker]
provider = "pi"
max_concurrency = 4
tools = ["search", "read"]
heartbeat_interval = "5s"
heartbeat_timeout = "30s"
heartbeat_on_timeout = "fail"
[worker.budget]
max_steps = 12
max_wall = "2h"
max_cost = 1.5
""".lstrip(),
        encoding="utf-8",
    )
    cfg = config.load(path)
    assert cfg.worker.provider == "pi"
    assert cfg.worker.max_concurrency == 4
    assert cfg.worker.tools == ("search", "read")
    assert cfg.worker.heartbeat_interval == "5s"
    assert cfg.worker.heartbeat_timeout == "30s"
    assert cfg.worker.heartbeat_on_timeout == "fail"
    assert cfg.worker.budget == config.BudgetConfig(max_steps=12, max_wall="2h", max_cost=1.5)


def test_load_rejects_bad_worker_tools_type(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    path.write_text('[worker]\ntools = "search"\n', encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load(path)


def test_load_rejects_unknown_worker_key(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    path.write_text("[worker]\nmax_workers = 3\n", encoding="utf-8")
    with pytest.raises(config.ConfigError) as excinfo:
        config.load(path)
    assert "max_workers" in str(excinfo.value)


def test_load_rejects_bool_worker_concurrency(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    path.write_text("[worker]\nmax_concurrency = true\n", encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load(path)


def test_validate_rejects_bad_budget() -> None:
    cfg = config.Config(worker=config.WorkerConfig(budget=config.BudgetConfig(max_steps=0)))
    with pytest.raises(config.ConfigError):
        cfg.validate()


@pytest.mark.parametrize("max_wall", ["0m", "-1m", "1", "1w", "1 m", "1M", "1.5m"])
def test_validate_rejects_invalid_max_wall(max_wall: str) -> None:
    cfg = config.Config(worker=config.WorkerConfig(budget=config.BudgetConfig(max_wall=max_wall)))
    with pytest.raises(config.ConfigError, match="worker.budget.max_wall"):
        cfg.validate()


@pytest.mark.parametrize("max_wall", ["500ms", "30s", "10m", "2h", "1d"])
def test_validate_accepts_valid_max_wall(max_wall: str) -> None:
    config.Config(
        worker=config.WorkerConfig(budget=config.BudgetConfig(max_wall=max_wall))
    ).validate()


def test_load_rejects_wrong_worker_budget_type(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    path.write_text('[worker.budget]\nmax_steps = "many"\n', encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load(path)


def test_load_rejects_non_table(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    path.write_text("hitl = 3\n", encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load(path)


def test_load_rejects_bad_toml(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    path.write_text("this is = = not toml\n", encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load(path)


def test_load_rejects_unknown_worker_budget_key(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    path.write_text("[worker.budget]\nmax_step = 3\n", encoding="utf-8")
    with pytest.raises(config.ConfigError) as excinfo:
        config.load(path)
    assert "max_step" in str(excinfo.value)


def test_load_rejects_retired_top_level_budget(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    path.write_text("[budget]\nmax_steps = 3\n", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="unknown key"):
        config.load(path)


def test_load_rejects_removed_live_table(tmp_path: Path) -> None:
    # Phase R removed the offline switch; [live] is no longer a valid table.
    path = tmp_path / "originweave.toml"
    path.write_text("[live]\nenabled = false\n", encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load(path)


def test_project_dir_default_and_override(tmp_path: Path) -> None:
    assert config.Config().project.dir == "projects"
    assert config.Config().to_dict()["project"] == {"dir": "projects"}

    path = tmp_path / "originweave.toml"
    path.write_text('[project]\ndir = "proj"\n', encoding="utf-8")
    assert config.load(path).project.dir == "proj"


def test_load_rejects_unknown_project_key(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    path.write_text("[project]\nroot = 'x'\n", encoding="utf-8")
    with pytest.raises(config.ConfigError) as excinfo:
        config.load(path)
    assert "root" in str(excinfo.value)
