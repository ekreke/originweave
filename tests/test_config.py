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
    assert cfg.budget.max_steps == 60
    assert cfg.budget.max_wall == "10m"
    assert cfg.budget.max_cost == 2.0
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
[budget]
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
    assert cfg.budget.max_steps == 5
    assert cfg.budget.max_cost == 0.5
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


def test_validate_rejects_bad_budget() -> None:
    cfg = config.Config(budget=config.BudgetConfig(max_steps=0))
    with pytest.raises(config.ConfigError):
        cfg.validate()


def test_load_rejects_wrong_type(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    path.write_text('[budget]\nmax_steps = "many"\n', encoding="utf-8")
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


def test_load_rejects_unknown_key(tmp_path: Path) -> None:
    path = tmp_path / "originweave.toml"
    path.write_text("[budget]\nmax_step = 3\n", encoding="utf-8")
    with pytest.raises(config.ConfigError) as excinfo:
        config.load(path)
    assert "max_step" in str(excinfo.value)


def test_load_rejects_removed_live_table(tmp_path: Path) -> None:
    # Phase R removed the offline switch; [live] is no longer a valid table.
    path = tmp_path / "originweave.toml"
    path.write_text("[live]\nenabled = false\n", encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load(path)
