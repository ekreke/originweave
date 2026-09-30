"""Regenerate the deterministic fixtures under ``examples/``.

Each sample is an append-only event log. This script rebuilds every sample from a
single in-code definition so it stays in sync and byte-reproducible, via
:meth:`originweave.store.RunStore.append_event`. The ``organization_relations``
sample additionally gets a derived ``entity-graph.json`` (replayed from the events).

Hand-written snapshots (``input/`` and ``sources/``) are *not* regenerated.

Usage::

    uv run python scripts/build_sample_fixtures.py            # rewrite in place
    uv run python scripts/build_sample_fixtures.py --check    # verify up to date
    uv run python scripts/build_sample_fixtures.py --root <dir>  # single sample (copilot events)
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from originweave.blackboard import EntityGraph
from originweave.reduce import reduce
from originweave.store import RunStore

DEFAULT_ROOT = Path("examples/copilot_productivity")
RELATION_ROOT = Path("examples/organization_relations")
_BASE_TIME = datetime(2026, 9, 16, 0, 0, 0, tzinfo=UTC)
_RELATION_BASE_TIME = datetime(2026, 9, 17, 0, 0, 0, tzinfo=UTC)

DOC_URL = (
    "https://www.sityos.com/en/use-cases/"
    "55-faster-code-84-better-builds-github-copilots-real-enterprise-impact"
)
S1_URL = (
    "https://github.blog/news-insights/research/"
    "research-quantifying-github-copilots-impact-on-developer-productivity-and-happiness/"
)
S2_URL = (
    "https://github.blog/news-insights/research/"
    "research-quantifying-github-copilots-impact-in-the-enterprise-with-accenture/"
)

DOC_TITLE = "55% Faster Code, 84% Better Builds: GitHub Copilot's Real Enterprise Impact"
S1_TITLE = "Research: quantifying GitHub Copilot's impact on developer productivity and happiness"
S2_TITLE = "Research: Quantifying GitHub Copilot's impact in the enterprise with Accenture"

_EVIDENCE: dict[str, dict[str, str]] = {
    "e1": {
        "id": "e1",
        "quote": (
            "the developers using GitHub Copilot took on average 1 hour and 11 minutes to "
            "complete the task, while the developers who didn't use GitHub Copilot took on "
            "average 2 hours and 41 minutes"
        ),
        "sourceTitle": S1_TITLE,
        "url": S1_URL,
        "locator": "Finding 2 · experiment paragraph",
    },
    "e2": {
        "id": "e2",
        "quote": (
            "These results are statistically significant (P=.0017) and the 95% confidence "
            "interval for the percentage speed gain is [21%, 89%]."
        ),
        "sourceTitle": S1_TITLE,
        "url": S1_URL,
        "locator": "Finding 2 · paragraph after the experiment",
    },
    "e3": {
        "id": "e3",
        "quote": (
            "We recruited 95 professional developers, split them randomly into two groups, and "
            "timed how long it took them to write an HTTP server in JavaScript."
        ),
        "sourceTitle": S1_TITLE,
        "url": S1_URL,
        "locator": "Finding 2 · experiment setup",
    },
    "e4": {
        "id": "e4",
        "quote": "At Accenture, we saw an 84% increase in successful builds",
        "sourceTitle": S2_TITLE,
        "url": S2_URL,
        "locator": "Our findings · Developers improved code quality",
    },
    "e5": {
        "id": "e5",
        "quote": (
            "An impressive 90% of developers expressed feeling more fulfilled with their jobs "
            "when utilizing GitHub Copilot"
        ),
        "sourceTitle": S2_TITLE,
        "url": S2_URL,
        "locator": "Our findings · GitHub Copilot improved the overall developer experience",
    },
    "e6": {
        "id": "e6",
        "quote": "We found that our AI pair programmer helps developers code up to 55% faster",
        "sourceTitle": S2_TITLE,
        "url": S2_URL,
        "locator": "intro (links back to the 2022 lab study)",
    },
    "e7": {
        "id": "e7",
        "quote": (
            "in a controlled enterprise study with Accenture, developers using it completed "
            "tasks 55% faster"
        ),
        "sourceTitle": DOC_TITLE,
        "url": DOC_URL,
        "locator": "How 50,000+ companies ... · lead paragraph",
    },
    "e8": {
        "id": "e8",
        "quote": "1,000+ developers were tracked over 6 weeks",
        "sourceTitle": DOC_TITLE,
        "url": DOC_URL,
        "locator": "paragraph starting 'In a randomised controlled trial ...'",
    },
    "e9": {
        "id": "e9",
        "quote": "pull request cycle time dropped from 9.6 days to 2.4 days (a 75% reduction)",
        "sourceTitle": DOC_TITLE,
        "url": DOC_URL,
        "locator": "paragraph starting 'In a randomised controlled trial ...'",
    },
    "e10": {
        "id": "e10",
        "quote": "it is peer-reviewed enterprise data from a real organisation at scale",
        "sourceTitle": DOC_TITLE,
        "url": DOC_URL,
        "locator": "paragraph starting 'In a randomised controlled trial ...'",
    },
}


def _evidence(*ids: str) -> list[dict[str, str]]:
    return [dict(_EVIDENCE[evidence_id]) for evidence_id in ids]


def _fact(
    fact_id: str,
    kind: str,
    *,
    role: str = "none",
    label: str = "",
    subtitle: str = "",
    status: str = "open",
    confidence: float = 0.0,
    note: str = "",
    evidence: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "id": fact_id,
        "kind": kind,
        "role": role,
        "label": label,
        "subtitle": subtitle,
        "status": status,
        "confidence": confidence,
        "note": note,
        "position": {"x": 0.0, "y": 0.0},
        "evidence": evidence or [],
    }


ORIGIN = _fact(
    "origin",
    "origin",
    label="资料 A · Sityos AI「55% Faster Code」",
    subtitle="营销/聚合页 · url",
    status="verified",
    confidence=1.0,
    note="溯源起点：待核验的资料 A。",
)

GOAL = _fact(
    "goal",
    "goal",
    label="判定「55% faster」是否忠实于一手研究",
    subtitle="停止条件 · 归因 / 口径 / 边界 / 样本",
    status="verified",
    confidence=1.0,
    note="核心论点全部拆解、回链、偏差判定完成才 COMPLETE。",
)


class _Clock:
    """Monotonic, deterministic ISO-8601 timestamps for a fixture."""

    def __init__(self, base: datetime = _BASE_TIME) -> None:
        self._base = base
        self._offset = 0

    def peek(self) -> str:
        return (self._base + timedelta(seconds=self._offset)).isoformat()

    def tick(self) -> str:
        at = self.peek()
        self._offset += 1
        return at


def _intent(
    intent_id: str,
    intent_type: str,
    from_id: str,
    question: str,
    at: str,
) -> dict[str, Any]:
    return {
        "id": intent_id,
        "type": intent_type,
        "status": "open",
        "from": from_id,
        "question": question,
        "producedFacts": [],
        "claimedBy": None,
        "heartbeatAt": None,
        "createdAt": at,
        "duplicateOf": None,
    }


def _edge(edge_id: str, source: str, target: str, relation: str, note: str = "") -> dict[str, str]:
    return {"id": edge_id, "source": source, "target": target, "relation": relation, "note": note}


def _events() -> list[tuple[str, dict[str, Any], str, str]]:
    clock = _Clock()

    def event(
        event_type: str, payload: dict[str, Any], message: str
    ) -> tuple[str, dict[str, Any], str, str]:
        return event_type, payload, message, clock.tick()

    f1 = _fact(
        "f1",
        "fact",
        role="main-claim",
        label="GitHub Copilot 让开发者完成任务快 55%",
        subtitle="核心抽象论点 · main-claim",
        status="flagged",
        confidence=0.70,
        note="核心说法已拆为 3 条子断言；55% 的口径与归因待核实。",
    )
    f2 = _fact(
        "f2",
        "fact",
        role="sub-claim",
        label="该 55% 出自与 Accenture 的企业 RCT",
        subtitle="sub-claim · 归因",
        status="flagged",
        confidence=0.55,
        note="资料 A 称其为 Accenture 企业研究。",
        evidence=_evidence("e7", "e8"),
    )
    f3 = _fact(
        "f3",
        "fact",
        role="sub-claim",
        label="同一研究得出 84% 构建成功率与 90% 满意度",
        subtitle="sub-claim · 结论并列",
        status="review",
        confidence=0.60,
        note="多个数字被并列为同一研究的结论。",
        evidence=_evidence("e4", "e5"),
    )
    f4 = _fact(
        "f4",
        "fact",
        role="sub-claim",
        label="该研究为 peer-reviewed 企业级数据",
        subtitle="sub-claim · 性质表述",
        status="review",
        confidence=0.50,
        note="资料 A 称其为 peer-reviewed。",
        evidence=_evidence("e10"),
    )
    c1 = _fact(
        "c1",
        "citation",
        label="资料 A 引述 GitHub 研究",
        subtitle="citation",
        status="verified",
        confidence=0.85,
        note="A 中的转述环节。",
    )
    s1 = _fact(
        "s1",
        "source",
        label="GitHub 2022 实验室研究（n=95 · 单任务 · CI [21%, 89%]）",
        subtitle="一手来源",
        status="verified",
        confidence=0.95,
        note="55% 的真实出处：单个 JS HTTP server 任务、95 名专业开发者。",
        evidence=_evidence("e1", "e2", "e3"),
    )
    s2 = _fact(
        "s2",
        "source",
        label="GitHub + Accenture 2024 企业研究",
        subtitle="一手来源",
        status="verified",
        confidence=0.90,
        note="只含 PR 量/合并率/构建成功率/满意度，未测量任务耗时。",
        evidence=_evidence("e4", "e5", "e6"),
    )
    p1 = _fact(
        "p1",
        "compare",
        label="compare（facts × sources × goal）",
        subtitle="比对引擎",
        status="verified",
        confidence=0.80,
        note="汇总 facts × sources × goal，产出 deviation。",
    )
    b1 = _fact(
        "b1",
        "boundary",
        label="适用边界：单个 JS HTTP server 任务、95 名专业开发者",
        subtitle="goal 派生的边界事实",
        status="verified",
        confidence=0.85,
        note="越过该边界即停止判定。",
        evidence=_evidence("e3", "e2"),
    )
    deviations = [
        _fact(
            "d1",
            "deviation",
            label="归因错误：55% 归给 Accenture 企业研究",
            subtitle="severity=high · confidence=0.90",
            status="flagged",
            confidence=0.90,
            note="55% 出自 2022 年 GitHub 实验室研究；Accenture 2024 研究未测量任务耗时。",
            evidence=_evidence("e7", "e6", "e1"),
        ),
        _fact(
            "d2",
            "deviation",
            label="无来源数字：1,000+ 开发者 / 6 周 / PR 周期 9.6→2.4 天",
            subtitle="severity=high · confidence=0.88",
            status="flagged",
            confidence=0.88,
            note="两处一手来源均无这些数据。",
            evidence=_evidence("e8", "e9", "e4"),
        ),
        _fact(
            "d3",
            "deviation",
            label="省略边界：55% 未带置信区间与小样本/单任务限定",
            subtitle="severity=high · confidence=0.86",
            status="flagged",
            confidence=0.86,
            note="原文 95% 置信区间为 [21%, 89%]，区间极宽。",
            evidence=_evidence("e7", "e2"),
        ),
        _fact(
            "d4",
            "deviation",
            label="指标混用：把遥测指标与自报比例并列为同质结论",
            subtitle="severity=medium · confidence=0.72",
            status="review",
            confidence=0.72,
            note="84% 为遥测指标，90% 为开发者自报比例；两者性质不同却并列陈述。",
            evidence=_evidence("e4", "e5", "e7"),
        ),
        _fact(
            "d5",
            "deviation",
            label="表述夸大：称未经同行评审的博客为 peer-reviewed",
            subtitle="severity=medium · confidence=0.70",
            status="review",
            confidence=0.70,
            note="两篇 GitHub 博客均为厂商研究发布，未经同行评审。",
            evidence=_evidence("e10"),
        ),
        _fact(
            "d6",
            "deviation",
            label="数值口径：'90% higher job satisfaction' 转述失准",
            subtitle="severity=low · confidence=0.62",
            status="review",
            confidence=0.62,
            note="原文为 90% 表示更有成就感，而非满意度提升 90%。",
            evidence=_evidence("e5"),
        ),
    ]

    events: list[tuple[str, dict[str, Any], str, str]] = []
    events.append(
        event("PROJECT", {"origin": ORIGIN, "goal": GOAL}, "run 创建：初始化 origin 与 goal")
    )
    events.append(
        event(
            "HINT",
            {
                "hint": {
                    "id": "h1",
                    "text": "优先核对 55% 的原始出处与置信区间。",
                    "author": "human",
                    "createdAt": "2026-09-16T00:00:01+00:00",
                }
            },
            "人类注入提示",
        )
    )
    events.append(event("REASON", {"phase": "start", "triggerFacts": ["origin"]}, "Reason 开始"))

    bootstrap_at = clock.peek()
    events.append(
        event(
            "INTENT",
            {
                "intent": _intent(
                    "i1",
                    "explore",
                    "origin",
                    "识别资料 A 的核心抽象论点（Bootstrap）。",
                    bootstrap_at,
                )
            },
            "声明 Intent i1：抽取核心论点",
        )
    )
    events.append(
        event(
            "EXECUTE",
            {"intentId": "i1", "worker": "worker-1", "model": "fixture"},
            "worker-1 认领 i1",
        )
    )
    events.append(
        event(
            "CONCLUDE",
            {
                "intentId": "i1",
                "facts": [f1],
                "edges": [_edge("e-main-origin-f1", "origin", "f1", "main-chain", "bootstrap")],
            },
            "i1 产出 f1 核心抽象论点",
        )
    )
    events.append(
        event("REASON", {"phase": "end", "triggerFacts": ["f1"]}, "Reason 结束：图已变化")
    )
    events.append(
        event(
            "REQUEST_HUMAN",
            {"gate": "confirm-claim", "question": "确认核心抽象论点及其拆解树。"},
            "Gate A：等待人工确认论点",
        )
    )
    events.append(
        event(
            "HUMAN_INPUT",
            {
                "gate": "confirm-claim",
                "decision": "approve",
                "text": "论点成立，按子断言继续。",
                "targets": ["f1"],
                "author": "human",
            },
            "Gate A 已确认",
        )
    )

    decompose_at = clock.peek()
    events.append(
        event(
            "INTENT",
            {
                "intent": _intent(
                    "i2", "decompose", "f1", "把「快 55%」拆成可独立验证的子断言。", decompose_at
                )
            },
            "声明 Intent i2：拆解核心论点",
        )
    )
    events.append(
        event(
            "EXECUTE",
            {"intentId": "i2", "worker": "worker-1", "model": "fixture"},
            "worker-1 认领 i2",
        )
    )
    events.append(
        event(
            "CONCLUDE",
            {"intentId": "i2", "facts": [f2, f3, f4], "edges": []},
            "i2 产出 f2/f3/f4 子断言",
        )
    )

    explore_at = clock.peek()
    events.append(
        event(
            "INTENT",
            {
                "intent": _intent(
                    "i3",
                    "explore",
                    "f2",
                    "f2 声称 55% 出自 Accenture 企业研究——核实其真实出处与边界。",
                    explore_at,
                )
            },
            "声明 Intent i3：探索一手来源",
        )
    )
    events.append(
        event(
            "EXECUTE",
            {"intentId": "i3", "worker": "worker-1", "model": "fixture"},
            "worker-1 认领 i3",
        )
    )
    events.append(event("HEARTBEAT", {"intentId": "i3"}, "i3 心跳"))
    events.append(
        event(
            "CONCLUDE",
            {
                "intentId": "i3",
                "facts": [c1, s1, s2],
                "edges": [
                    _edge("e-main-f2-c1", "f2", "c1", "main-chain", "cite"),
                    _edge("e-main-c1-s1", "c1", "s1", "main-chain", "link"),
                    _edge("e-dep-f2-s2", "f2", "s2", "dependency", "evidence"),
                ],
            },
            "i3 产出 c1 引用与 s1/s2 一手来源",
        )
    )

    verify_at = clock.peek()
    events.append(
        event(
            "INTENT",
            {
                "intent": _intent(
                    "i4",
                    "verify",
                    "f3",
                    "比对 f2/f3/f4 与一手来源，判定偏差。",
                    verify_at,
                )
            },
            "声明 Intent i4：比对判偏差",
        )
    )
    events.append(
        event(
            "EXECUTE",
            {"intentId": "i4", "worker": "worker-2", "model": "fixture"},
            "worker-2 认领 i4",
        )
    )
    events.append(
        event(
            "CONCLUDE",
            {
                "intentId": "i4",
                "facts": [p1, b1, *deviations],
                "edges": [
                    _edge("e-dep-f1-p1", "f1", "p1", "dependency", "verify"),
                    _edge("e-dep-f2-p1", "f2", "p1", "dependency", "verify"),
                    _edge("e-dep-f3-p1", "f3", "p1", "dependency", "verify"),
                    _edge("e-dep-f4-p1", "f4", "p1", "dependency", "verify"),
                    _edge("e-goal-b1", "goal", "b1", "goal-derived", "boundary"),
                    *[
                        _edge(f"e-goal-{d['id']}", "goal", d["id"], "goal-derived", "deviation")
                        for d in deviations
                    ],
                ],
            },
            "i4 产出 compare 与 6 项偏差",
        )
    )
    events.append(
        event(
            "REQUEST_HUMAN",
            {"gate": "arbitrate", "question": "55% 的归因以哪一份一手来源为准？"},
            "Gate B：等待人工裁决来源冲突",
        )
    )
    events.append(
        event(
            "HUMAN_INPUT",
            {
                "gate": "arbitrate",
                "decision": "edit",
                "text": "55% 归属 2022 实验室研究；Accenture 研究不含耗时指标。",
                "targets": ["s1", "s2"],
                "author": "human",
            },
            "Gate B 已裁决",
        )
    )
    events.append(event("COMPLETE", {"verdict": "部分偏差"}, "到达 goal：产出偏差记分卡"))

    return events


# ------------------------------------------------------------------ organization_relations

# Reuses the copilot_productivity snapshots (same 资料 A + sources); this sample runs
# the relation analysis over the same corpus, so its evidence quotes link back to the
# same frozen files. Relations split into verified (quote+url) and inferred (no source).

_REL_EVIDENCE: dict[str, dict[str, str]] = {
    "r1-ev0": {
        "id": "r1-ev0",
        "quote": (
            "GitHub Next conducted the experiment in partnership with the Microsoft Office "
            "of the Chief Economist"
        ),
        "sourceTitle": S1_TITLE,
        "url": S1_URL,
        "locator": "Acknowledgements",
    },
    "r3-ev0": {
        "id": "r3-ev0",
        "quote": (
            "we partnered with Accenture to study how developers integrated GitHub Copilot "
            "into their daily workflows"
        ),
        "sourceTitle": S2_TITLE,
        "url": S2_URL,
        "locator": "intro",
    },
    "r4-ev0": {
        "id": "r4-ev0",
        "quote": (
            "GitHub Copilot is an AI pair programmer built on OpenAI's Codex and GitHub's "
            "own large language models"
        ),
        "sourceTitle": DOC_TITLE,
        "url": DOC_URL,
        "locator": "What GitHub Copilot Does",
    },
}


def _entity(
    entity_id: str,
    name: str,
    *,
    type: str = "organization",
    aliases: list[str] | None = None,
    status: str = "open",
    confidence: float = 0.0,
    note: str = "",
    evidence: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "id": entity_id,
        "name": name,
        "type": type,
        "aliases": aliases or [],
        "status": status,
        "confidence": confidence,
        "note": note,
        "position": {"x": 0.0, "y": 0.0},
        "evidence": evidence or [],
    }


def _relation(
    relation_id: str,
    source: str,
    target: str,
    type: str,
    *,
    label: str = "",
    status: str = "open",
    confidence: float = 0.0,
    inferred: bool = False,
    note: str = "",
    evidence: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "id": relation_id,
        "source": source,
        "target": target,
        "type": type,
        "label": label,
        "status": status,
        "confidence": confidence,
        "inferred": inferred,
        "note": note,
        "evidence": evidence or [],
    }


def _relation_events() -> list[tuple[str, dict[str, Any], str, str]]:
    """The ``organization_relations`` run: entities + relations over the copilot corpus.

    Mirrors the engine's graph passes: Bootstrap + Gate A, then an ``extract`` pass
    (ENTITY events) and per-entity ``relate`` passes (RELATION events), then COMPLETE.
    """
    clock = _Clock(_RELATION_BASE_TIME)

    def event(
        event_type: str, payload: dict[str, Any], message: str
    ) -> tuple[str, dict[str, Any], str, str]:
        return event_type, payload, message, clock.tick()

    origin = _fact(
        "origin",
        "origin",
        label="资料 A · Sityos AI「55% Faster Code」",
        subtitle="营销/聚合页 · url",
        status="verified",
        confidence=1.0,
        note="抽取起点：待分析组织关系的资料 A。",
    )
    goal = _fact(
        "goal",
        "goal",
        label="抽取资料 A 中的组织实体及其关系，无来源的推断须显式标注",
        subtitle="停止条件 · 实体 / 关系",
        status="verified",
        confidence=1.0,
        note="全部实体抽取并判关系后 COMPLETE。",
    )
    f1 = _fact(
        "f1",
        "fact",
        role="main-claim",
        label="Copilot 生态涉及 GitHub / Microsoft / Accenture / OpenAI",
        subtitle="核心抽象论点 · main-claim",
        status="open",
        confidence=0.60,
        note="从资料 A 的论述中识别出的组织集合。",
    )

    n1 = _entity(
        "n1",
        "GitHub",
        aliases=["GitHub, Inc."],
        status="verified",
        confidence=0.95,
        note="Copilot 的开发方与代码托管平台。",
    )
    n2 = _entity(
        "n2",
        "Microsoft",
        status="verified",
        confidence=0.90,
        note="与 GitHub 合作开展实验的组织。",
    )
    n3 = _entity(
        "n3",
        "Accenture",
        status="open",
        confidence=0.85,
        note="企业研究的合作方。",
    )
    n4 = _entity(
        "n4",
        "OpenAI",
        status="open",
        confidence=0.80,
        note="Codex 模型提供方。",
    )

    r1 = _relation(
        "r1",
        "n1",
        "n2",
        "partners-with",
        label="partnership",
        status="verified",
        confidence=0.85,
        evidence=[dict(_REL_EVIDENCE["r1-ev0"])],
    )
    r2 = _relation(
        "r2",
        "n1",
        "n2",
        "subsidiary-of",
        status="inferred",
        confidence=0.55,
        inferred=True,
        note="GitHub 隶属 Microsoft：资料 A 与来源均未直接陈述，属推断。",
    )
    r3 = _relation(
        "r3",
        "n1",
        "n3",
        "partners-with",
        label="partnered",
        status="verified",
        confidence=0.90,
        evidence=[dict(_REL_EVIDENCE["r3-ev0"])],
    )
    r4 = _relation(
        "r4",
        "n4",
        "n1",
        "supplies",
        label="built on Codex",
        status="verified",
        confidence=0.75,
        evidence=[dict(_REL_EVIDENCE["r4-ev0"])],
    )

    events: list[tuple[str, dict[str, Any], str, str]] = []
    events.append(
        event("PROJECT", {"origin": origin, "goal": goal}, "run 创建：初始化 origin 与 goal")
    )
    events.append(
        event(
            "HINT",
            {
                "hint": {
                    "id": "h1",
                    "text": "优先核对组织之间的合作/隶属关系是否有来源。",
                    "author": "human",
                    "createdAt": "2026-09-17T00:00:01+00:00",
                }
            },
            "人类注入提示",
        )
    )
    events.append(event("REASON", {"phase": "start", "triggerFacts": ["origin"]}, "Reason 开始"))

    bootstrap_at = clock.peek()
    events.append(
        event(
            "INTENT",
            {
                "intent": _intent(
                    "i1",
                    "explore",
                    "origin",
                    "识别资料 A 的组织集合（Bootstrap）。",
                    bootstrap_at,
                )
            },
            "声明 Intent i1：抽取核心论点",
        )
    )
    events.append(
        event(
            "EXECUTE",
            {"intentId": "i1", "worker": "worker-1", "model": "fixture"},
            "worker-1 认领 i1",
        )
    )
    events.append(
        event(
            "CONCLUDE",
            {
                "intentId": "i1",
                "facts": [f1],
                "edges": [_edge("e-main-origin-f1", "origin", "f1", "main-chain", "bootstrap")],
            },
            "i1 产出 f1 核心论点",
        )
    )
    events.append(
        event("REASON", {"phase": "end", "triggerFacts": ["f1"]}, "Reason 结束：图已变化")
    )
    events.append(
        event(
            "REQUEST_HUMAN",
            {"gate": "confirm-claim", "question": "确认抽取范围与组织集合。"},
            "Gate A：等待人工确认",
        )
    )
    events.append(
        event(
            "HUMAN_INPUT",
            {
                "gate": "confirm-claim",
                "decision": "approve",
                "text": "范围成立，继续抽取实体与关系。",
                "targets": ["f1"],
                "author": "human",
            },
            "Gate A 已确认",
        )
    )

    events.append(event("REASON", {"phase": "start", "triggerFacts": ["f1"]}, "Reason 开始"))
    extract_at = clock.peek()
    events.append(
        event(
            "INTENT",
            {
                "intent": _intent(
                    "i2", "extract", "origin", "从资料 A 抽取组织实体。", extract_at
                )
            },
            "声明 Intent i2：抽取实体",
        )
    )
    events.append(
        event(
            "EXECUTE",
            {"intentId": "i2", "worker": "worker-1", "model": "fixture"},
            "worker-1 认领 i2",
        )
    )
    for entity in (n1, n2, n3, n4):
        events.append(event("ENTITY", {"entity": entity}, f"i2 抽取实体 {entity['id']}"))
    events.append(
        event("CONCLUDE", {"intentId": "i2", "facts": [], "edges": []}, "i2 提交实体")
    )

    # One relate pass per entity (engine dispatches relate Intents from entity ids).
    relate_pass = [
        ("i3", "n1", [r1, r2]),
        ("i4", "n2", []),
        ("i5", "n3", [r3]),
        ("i6", "n4", [r4]),
    ]
    for intent_id, entity_id, relations in relate_pass:
        events.append(
            event("REASON", {"phase": "start", "triggerFacts": [f1["id"]]}, "Reason 开始")
        )
        at = clock.peek()
        events.append(
            event(
                "INTENT",
                {
                    "intent": _intent(
                        intent_id, "relate", entity_id, f"判定 {entity_id} 的关系。", at
                    )
                },
                f"声明 Intent {intent_id}：判关系",
            )
        )
        events.append(
            event(
                "EXECUTE",
                {"intentId": intent_id, "worker": "worker-2", "model": "fixture"},
                f"worker-2 认领 {intent_id}",
            )
        )
        for relation in relations:
            events.append(
                event("RELATION", {"relation": relation}, f"{intent_id} 写入关系 {relation['id']}")
            )
        events.append(
            event(
                "CONCLUDE",
                {"intentId": intent_id, "facts": [], "edges": []},
                f"{intent_id} 提交",
            )
        )

    events.append(event("COMPLETE", {"verdict": "组织关系已判定"}, "到达停止条件：产出实体-关系图"))
    return events


@dataclass(frozen=True)
class Sample:
    """One committed example: its events builder and whether it derives a graph file."""

    name: str
    root: Path
    events: Callable[[], list[tuple[str, dict[str, Any], str, str]]]
    entity_graph: bool = False


SAMPLES: tuple[Sample, ...] = (
    Sample("copilot_productivity", DEFAULT_ROOT, _events),
    Sample("organization_relations", RELATION_ROOT, _relation_events, entity_graph=True),
)


def build(
    root: Path,
    events_fn: Callable[[], list[tuple[str, dict[str, Any], str, str]]] = _events,
    *,
    entity_graph: bool = False,
) -> None:
    """(Re)write ``events.jsonl`` under ``root`` (``capabilities/`` is obsolete).

    With ``entity_graph``, also (re)write the derived ``entity-graph.json`` from the
    folded events, using the engine's format (``engine._flush_entity_graph``).
    """
    events_path = root / "events.jsonl"
    if events_path.exists():
        events_path.unlink()
    obsolete = root / "capabilities"
    if obsolete.exists():
        shutil.rmtree(obsolete)

    store = RunStore(root)
    store.init_layout()
    for event_type, payload, message, at in events_fn():
        store.append_event(event_type, payload, message=message, at=at)

    if entity_graph:
        board = reduce(store.read_events())
        graph = EntityGraph(entities=board.entities, relations=board.relations)
        store.write_entity_graph(
            json.dumps(graph.to_dict(), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
        )


def _snapshot(root: Path, *, entity_graph: bool = False) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    events_path = root / "events.jsonl"
    if events_path.is_file():
        snapshot["events.jsonl"] = events_path.read_bytes()
    if entity_graph:
        graph_path = root / "entity-graph.json"
        if graph_path.is_file():
            snapshot["entity-graph.json"] = graph_path.read_bytes()
    return snapshot


def _check(sample: Sample) -> bool:
    if (sample.root / "capabilities").exists():
        print(f"{sample.root}/capabilities is obsolete; run scripts/build_sample_fixtures.py")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / "root"
        build(candidate, sample.events, entity_graph=sample.entity_graph)
        if _snapshot(sample.root, entity_graph=sample.entity_graph) != _snapshot(
            candidate, entity_graph=sample.entity_graph
        ):
            print(f"fixtures under {sample.root} are stale; run scripts/build_sample_fixtures.py")
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        help="build a single sample directory with the copilot events (default: all samples)",
    )
    parser.add_argument("--check", action="store_true", help="verify fixtures are up to date")
    args = parser.parse_args(argv)

    targets = SAMPLES if args.root is None else (Sample("custom", Path(args.root), _events),)

    if args.check:
        ok = all(_check(sample) for sample in targets)
        if ok:
            print("fixtures are up to date")
        return 0 if ok else 1

    for sample in targets:
        build(sample.root, sample.events, entity_graph=sample.entity_graph)
        print(f"wrote fixtures under {sample.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
