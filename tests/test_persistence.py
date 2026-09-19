from __future__ import annotations

import json
from pathlib import Path

import pytest

from originweave.blackboard import BlackboardError
from originweave.config import BudgetConfig
from originweave.persistence import (
    IntentCounts,
    Project,
    ProjectRegistry,
    Run,
    Steps,
    allocate_run_id,
    summarize_run,
)
from originweave.store import RunStore

SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "copilot_productivity"

_ORIGIN = {"id": "origin", "kind": "origin", "label": "Document A"}
_GOAL = {"id": "goal", "kind": "goal", "label": "Every sub-claim is sourced"}


def _store_with_events(root: Path) -> RunStore:
    store = RunStore(root)
    store.init_layout()
    store.append_event(
        "PROJECT", {"origin": _ORIGIN, "goal": _GOAL}, at="2026-01-01T00:00:00+00:00"
    )
    store.append_event(
        "INTENT",
        {"intent": {"id": "i1", "type": "explore", "from": "origin", "question": "q"}},
        at="2026-01-01T00:00:01+00:00",
    )
    store.append_event(
        "EXECUTE",
        {"intentId": "i1", "worker": "worker-1", "model": "x"},
        at="2026-01-01T00:00:02+00:00",
    )
    store.append_event(
        "CONCLUDE",
        {"intentId": "i1", "facts": [{"id": "f1", "kind": "fact", "role": "main-claim"}]},
        at="2026-01-01T00:00:03+00:00",
    )
    store.append_event("COMPLETE", {"verdict": "ok"}, at="2026-01-01T00:00:04+00:00")
    return store


def test_init_layout_does_not_create_run_json(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    store.init_layout()

    assert not store.run_json_path.exists()


def test_run_json_round_trip(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    store.init_layout()
    assert store.read_run_meta() is None

    store.write_run_meta({"id": "run_001", "project_id": "p", "title": "T"})

    assert store.read_run_meta() == {"id": "run_001", "project_id": "p", "title": "T"}


def test_allocate_run_id_scans_existing_runs(tmp_path: Path) -> None:
    runs = tmp_path / "runs"

    assert allocate_run_id(runs) == "run_001"  # missing dir -> first id

    (runs / "run_001").mkdir(parents=True)
    (runs / "run_009").mkdir()
    (runs / "not-a-run").mkdir()
    (runs / "run_x").mkdir()

    assert allocate_run_id(runs) == "run_010"


def test_allocate_run_id_handles_thousands(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    (runs / "run_1000").mkdir(parents=True)

    assert allocate_run_id(runs) == "run_1001"


def test_summarize_run_derives_from_events(tmp_path: Path) -> None:
    store = _store_with_events(tmp_path / "run_001")

    run = summarize_run(store)

    assert run.id == "run_001"
    assert run.title == "run_001"  # falls back to the directory name
    assert run.project_id == ""
    assert run.status == "completed"
    assert run.goal == "Every sub-claim is sourced"
    assert run.facts == 1
    assert run.intents == IntentCounts(open=0, done=1)
    assert run.created_at == "2026-01-01T00:00:00+00:00"
    assert run.updated_at == "2026-01-01T00:00:04+00:00"
    assert run.steps == Steps(current=0, total=0)


def test_summarize_run_meta_overrides_static_fields(tmp_path: Path) -> None:
    store = _store_with_events(tmp_path / "run_001")
    meta = {
        "id": "run_001",
        "project_id": "copilot",
        "title": "55% verification",
        "source_type": "text",
        "analysis": "provenance",
        "goal": "meta goal",
        "created_at": "2025-12-31T00:00:00+00:00",
        "budget": {"max_steps": 7},
    }

    run = summarize_run(store, meta=meta, budget=BudgetConfig(max_steps=99))

    assert run.project_id == "copilot"
    assert run.title == "55% verification"
    assert run.goal == "meta goal"
    assert run.created_at == "2025-12-31T00:00:00+00:00"
    # status always comes from the events, never the metadata.
    assert run.status == "completed"
    assert run.steps.total == 7


def test_summarize_run_empty_dir_defaults_to_queued(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_007")
    store.init_layout()

    run = summarize_run(store)

    assert run.id == "run_007"
    assert run.status == "queued"
    assert run.facts == 0
    assert run.created_at == ""
    assert run.updated_at == ""
    assert run.intents == IntentCounts()


def test_summarize_run_ignores_result_fields_in_run_json(tmp_path: Path) -> None:
    # run.json is static-only: a status/updated_at there must be ignored.
    store = RunStore(tmp_path / "run_001")
    store.init_layout()
    store.write_run_meta(
        {"id": "run_001", "status": "failed", "updated_at": "2030-01-01T00:00:00+00:00"}
    )

    run = summarize_run(store)

    assert run.status == "queued"
    assert run.updated_at == ""


def test_summarize_run_budget_falls_back_when_meta_max_steps_non_positive(
    tmp_path: Path,
) -> None:
    store = _store_with_events(tmp_path / "run_001")

    run = summarize_run(store, meta={"budget": {"max_steps": 0}}, budget=BudgetConfig(max_steps=42))

    assert run.steps.total == 42


def test_store_read_run_meta_rejects_malformed(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    store.init_layout()
    store.run_json_path.write_text("not json", encoding="utf-8")

    with pytest.raises(BlackboardError):
        store.read_run_meta()


def test_summarize_run_sample_without_run_json() -> None:
    run = summarize_run(RunStore(SAMPLE))

    assert run.status == "completed"
    assert run.facts == 15
    assert run.deviations == 6
    assert run.intents.done == 4
    assert run.project_id == ""  # sample has no run.json
    assert run.title == "copilot_productivity"
    assert run.goal != ""


def test_run_dict_round_trip() -> None:
    run = Run(id="run_001", project_id="p", facts=3, intents=IntentCounts(open=1, done=2))

    assert Run.from_dict(run.to_dict()) == run


def test_project_registry_derives_run_count_and_updated_at(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    runs_dir = tmp_path / "runs"
    registry = ProjectRegistry(projects_dir, runs_dir)

    project = registry.ensure("copilot", name="Copilot")

    assert project.run_count == 0
    assert registry.get("copilot") is not None
    assert registry.get("missing") is None

    run = _store_with_events(runs_dir / "run_001")
    run.write_run_meta({"id": "run_001", "project_id": "copilot", "title": "T"})

    loaded = registry.get("copilot")
    assert loaded is not None
    assert loaded.run_count == 1
    assert loaded.updated_at == "2026-01-01T00:00:04+00:00"
    assert [p.id for p in registry.list()] == ["copilot"]
    # counts are derived, never persisted.
    on_disk = json.loads((projects_dir / "copilot" / "project.json").read_text(encoding="utf-8"))
    assert "run_count" not in on_disk
    assert on_disk == {"id": "copilot", "name": "Copilot", "description": "", "accent": ""}


def test_project_registry_rejects_unsafe_id(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "projects", tmp_path / "runs")

    with pytest.raises(ValueError):
        registry.path("../escape")
    with pytest.raises(ValueError):
        registry.get("")


def test_project_registry_skips_invalid_dirs_and_unregistered_runs(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    runs_dir = tmp_path / "runs"
    registry = ProjectRegistry(projects_dir, runs_dir)
    registry.write(Project(id="p", name="P"))
    # a stray directory that is not a valid project id must not break list()
    stray = projects_dir / "a b"
    stray.mkdir(parents=True)
    (stray / "project.json").write_text("{}", encoding="utf-8")
    # a run dir without run.json cannot be attributed to a project
    RunStore(runs_dir / "run_001").init_layout()

    assert [project.id for project in registry.list()] == ["p"]
    loaded = registry.get("p")
    assert loaded is not None
    assert loaded.run_count == 0


def test_project_registry_tolerates_corrupt_run(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    runs_dir = tmp_path / "runs"
    registry = ProjectRegistry(projects_dir, runs_dir)
    registry.write(Project(id="p", name="P"))
    corrupt = runs_dir / "run_001"
    corrupt.mkdir(parents=True)
    (corrupt / "run.json").write_text("not json", encoding="utf-8")

    loaded = registry.get("p")

    assert loaded is not None
    assert loaded.run_count == 0


def test_project_to_dict_shape() -> None:
    project = Project(id="p", name="P", run_count=2)

    assert project.to_dict()["run_count"] == 2
    assert Project.from_dict(project.to_dict()) == project
