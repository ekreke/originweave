"""M3b tests: token usage, models.dev pricing, budget enforcement, pause/resume."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

from originweave.blackboard import Fact
from originweave.capabilities.base import PromptTemplate
from originweave.capabilities.model import ChatMessage, ModelResult, OpenAIModel, Usage
from originweave.capabilities.worker import LocalWorker
from originweave.config import BudgetConfig
from originweave.engine import Engine
from originweave.persistence import summarize_run
from originweave.pricing import ModelPrice, PricingTable
from originweave.reduce import reduce
from originweave.store import RunStore

NO_REASON = json.dumps({"facts": [], "intents": [], "complete": None})
_DEFAULT_USAGE = Usage(10, 5, 15)


class _Model:
    """A model that returns scripted replies, each carrying a fixed token usage."""

    name = "fake"
    model = "m"  # the engine labels sessions/pricing by this

    def __init__(self, *replies: str, usage: Usage | None = _DEFAULT_USAGE) -> None:
        self._replies = list(replies)
        self._usage = usage

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        text = self._replies.pop(0) if self._replies else NO_REASON
        return ModelResult(text, usage=self._usage)


class _Prompt:
    name = "fake"

    async def get(self, name: str) -> PromptTemplate:
        return PromptTemplate(name=name, text=name.upper())


class _Search:
    name = "fake"

    async def search(self, query: str, *, num_results: int = 8) -> str:
        return ""


def _origin() -> Fact:
    return Fact.from_dict({"id": "origin", "kind": "origin", "label": "A"})


def _goal() -> Fact:
    return Fact.from_dict({"id": "goal", "kind": "goal", "label": "G"})


def _engine(
    store: RunStore,
    *replies: str,
    budget: BudgetConfig | None = None,
    pricing: PricingTable | None = None,
    usage: Usage | None = _DEFAULT_USAGE,
) -> Engine:
    return Engine(
        worker=LocalWorker(model=_Model(*replies, usage=usage)),
        search=_Search(),
        prompt=_Prompt(),
        store=store,
        auto=True,
        budget=budget,
        pricing=pricing,
    )


# ------------------------------------------------------------------ usage chain


async def test_openai_model_returns_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            },
        )

    model = OpenAIModel(model="m", base_url="http://x", api_key="k")
    model._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await model.complete([ChatMessage(role="user", content="hi")])

    assert result == "hi"  # ModelResult is a str
    assert result.usage == Usage(3, 4, 7)


async def test_openai_model_without_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    model = OpenAIModel(model="m", base_url="http://x", api_key="k")
    model._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await model.complete([ChatMessage(role="user", content="hi")])
    assert getattr(result, "usage", None) is None


# --------------------------------------------------------------------- pricing


def test_pricing_table_loads_and_looks_up() -> None:
    table = PricingTable()
    count = table.load_models(
        {
            "deepseek": {
                "models": {
                    "deepseek-chat": {"cost": {"input": 0.27, "output": 1.1}},
                    "no-cost": {"name": "x"},
                }
            },
            "openai": {"models": {"gpt-x": {"cost": {"input": 1.0, "output": 2.0}}}},
        }
    )
    assert count == 2
    assert table.lookup("deepseek-chat") == ModelPrice(0.27, 1.1)
    assert table.lookup("DEEPSEEK-CHAT") == ModelPrice(0.27, 1.1)  # case-insensitive
    assert table.lookup("no-cost") is None
    assert table.lookup(None) is None


async def test_pricing_refresh_degrades_on_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    table = PricingTable()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await table.refresh(client=client) == 0
    assert table.loaded is True
    assert table.lookup("anything") is None


# ------------------------------------------------------------ budget enforcement


async def test_budget_steps_stops_the_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    budget = BudgetConfig(max_steps=1, max_wall="10m", max_cost=2.0)
    board = await _engine(store, NO_REASON, budget=budget).run(origin=_origin(), goal=_goal())

    assert board.status == "stopped"
    stopped = [e for e in store.read_events() if e.type == "STOPPED"]
    assert stopped and stopped[-1].payload["reason"] == "budget exceeded"
    assert stopped[-1].payload["budget"]["steps"] == 1


async def test_budget_cost_stops_the_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    budget = BudgetConfig(max_steps=99, max_wall="10m", max_cost=1.0)
    pricing = PricingTable({"m": ModelPrice(input_per_1m=1_000_000, output_per_1m=1_000_000)})
    # One call = (10 + 5) tokens * $1/token = $15 >= $1.
    board = await _engine(store, NO_REASON, budget=budget, pricing=pricing).run(
        origin=_origin(), goal=_goal()
    )

    assert board.status == "stopped"
    stopped = [e for e in store.read_events() if e.type == "STOPPED"][-1]
    assert stopped.payload["budget"]["cost"] >= 1.0


def test_budget_wall_exceeded_is_detected(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    store.init_layout()
    store.append_event(
        "PROJECT",
        {"origin": _origin().to_dict(), "goal": _goal().to_dict()},
        at="2000-01-01T00:00:00+00:00",
    )
    engine = _engine(
        store, budget=BudgetConfig(max_steps=99, max_wall="1s", max_cost=2.0)
    )
    info = engine._budget_exceeded(reduce(store.read_events()))
    assert info is not None
    assert info["wall_seconds"] >= 1.0


async def test_within_budget_does_not_stop(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    budget = BudgetConfig(max_steps=99, max_wall="10m", max_cost=999.0)
    board = await _engine(store, NO_REASON, budget=budget).run(origin=_origin(), goal=_goal())
    # No runnable direction, so the loop stops as a dead-end -- not a budget stop.
    assert board.status == "stopped"
    stopped = [e for e in store.read_events() if e.type == "STOPPED"]
    assert [e.payload["reason"] for e in stopped] == ["dead-end: no runnable intent"]
    assert all("budget" not in e.payload for e in stopped)


async def test_resume_on_a_fresh_engine_keeps_the_budget(tmp_path: Path) -> None:
    """A new Engine (as the server builds on resume) must rebuild cost from SESSION events."""
    store = RunStore(tmp_path / "run_001")
    pricing = PricingTable({"m": ModelPrice(input_per_1m=1_000_000, output_per_1m=1_000_000)})
    engine1 = _engine(
        store, NO_REASON, NO_REASON, budget=BudgetConfig(max_cost=999.0), pricing=pricing
    )
    engine1.request_pause()
    assert (await engine1.run(origin=_origin(), goal=_goal())).status == "paused"

    # A fresh engine with a tight cost budget: the preserved cost (15) must trip at once.
    engine2 = _engine(
        store, NO_REASON, NO_REASON, budget=BudgetConfig(max_cost=1.0), pricing=pricing
    )
    assert (await engine2.resume_from_pause()).status == "stopped"


# -------------------------------------------------------------- summarize_run


async def test_summarize_run_reports_usage_and_elapsed(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    pricing = PricingTable({"m": ModelPrice(input_per_1m=1_000_000, output_per_1m=1_000_000)})
    await _engine(store, NO_REASON, pricing=pricing).run(origin=_origin(), goal=_goal())

    run = summarize_run(store, budget=BudgetConfig())
    # Two worker calls (Bootstrap + Reason), each reporting 15 tokens.
    assert run.budget.tokens == 30
    assert run.budget.cost >= 30.0
    assert run.steps.current == 2


# --------------------------------------------------------------- pause / resume


async def test_pause_then_resume(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(store, NO_REASON, NO_REASON)
    engine.request_pause()  # ask before the loop reaches its first boundary

    board = await engine.run(origin=_origin(), goal=_goal())
    assert board.status == "paused"
    assert any(e.type == "PAUSED" for e in store.read_events())

    resumed = await engine.resume_from_pause()
    # Resume re-enters the loop, which then dead-ends on ``NO_REASON`` (a terminal stop).
    assert resumed.status == "stopped"
    assert any(e.type == "RESUMED" for e in store.read_events())


async def test_resume_from_pause_rejects_a_running_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "run_001")
    engine = _engine(store, NO_REASON)
    await engine.run(origin=_origin(), goal=_goal())
    with pytest.raises(Exception, match="not paused"):
        await engine.resume_from_pause()
