"""Regenerate the deterministic offline fixtures for the ``copilot_productivity`` sample.

The sample under ``examples/copilot_productivity/`` is a *recorded* run: an
append-only event log plus the capability responses that run depended on. This
script rebuilds both artefacts from a single in-code definition so they stay in
sync and byte-reproducible:

* ``events.jsonl``            via :meth:`originweave.store.RunStore.append_event`
* ``capabilities/**/*.json``  via :meth:`originweave.capabilities.cache.ResponseCache.write`

Hand-written snapshots (``input/`` and ``sources/``) are *not* regenerated.

Usage::

    uv run python scripts/build_sample_fixtures.py            # rewrite in place
    uv run python scripts/build_sample_fixtures.py --check    # verify up to date
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from originweave.capabilities.cache import ResponseCache
from originweave.store import RunStore

DEFAULT_ROOT = Path("examples/copilot_productivity")
RECORDED_AT = "2026-09-16T00:00:00+00:00"
_BASE_TIME = datetime(2026, 9, 16, 0, 0, 0, tzinfo=UTC)

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

#: ``(query, limit)`` pairs the sample agent is expected to issue; kept here so
#: M1 orchestration can align its queries with the recorded responses.
SEARCH_QUERIES: tuple[tuple[str, int], ...] = (
    ("GitHub Copilot 55% faster developer productivity study", 5),
    ("GitHub Copilot Accenture enterprise study 84% successful builds", 5),
)

#: Prompt template names the sample agent is expected to resolve.
PROMPT_NAMES: tuple[str, ...] = ("bootstrap", "decompose", "verify")

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
    """Monotonic, deterministic ISO-8601 timestamps for the fixture."""

    def __init__(self) -> None:
        self._offset = 0

    def peek(self) -> str:
        return (_BASE_TIME + timedelta(seconds=self._offset)).isoformat()

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
            {"gate": "A", "question": "确认核心抽象论点及其拆解树。"},
            "Gate A：等待人工确认论点",
        )
    )
    events.append(
        event(
            "HUMAN_INPUT",
            {
                "gate": "A",
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
            {"gate": "B", "question": "55% 的归因以哪一份一手来源为准？"},
            "Gate B：等待人工裁决来源冲突",
        )
    )
    events.append(
        event(
            "HUMAN_INPUT",
            {
                "gate": "B",
                "decision": "以一手来源为准",
                "text": "55% 归属 2022 实验室研究；Accenture 研究不含耗时指标。",
                "targets": ["s1", "s2"],
                "author": "human",
            },
            "Gate B 已裁决",
        )
    )
    events.append(event("COMPLETE", {"verdict": "部分偏差"}, "到达 goal：产出偏差记分卡"))

    return events


def _capability_records() -> list[tuple[str, str, dict[str, Any], Any]]:
    search_q1, limit1 = SEARCH_QUERIES[0]
    search_q2, limit2 = SEARCH_QUERIES[1]
    return [
        (
            "exa",
            "search",
            {"query": search_q1, "limit": limit1},
            [
                {
                    "title": S1_TITLE,
                    "url": S1_URL,
                    "snippet": (
                        "developers who used GitHub Copilot completed the task significantly "
                        "faster-55% faster ... 95% confidence interval ... [21%, 89%]"
                    ),
                    "published": "2022-09-07",
                },
                {
                    "title": DOC_TITLE,
                    "url": DOC_URL,
                    "snippet": (
                        "in a controlled enterprise study with Accenture, developers using it "
                        "completed tasks 55% faster"
                    ),
                    "published": None,
                },
            ],
        ),
        (
            "exa",
            "search",
            {"query": search_q2, "limit": limit2},
            [
                {
                    "title": S2_TITLE,
                    "url": S2_URL,
                    "snippet": (
                        "84% increase in successful builds; 15% increase to the pull request "
                        "merge rate"
                    ),
                    "published": "2024-05-13",
                },
            ],
        ),
        (
            "local",
            "prompt",
            {"name": "bootstrap"},
            {
                "name": "bootstrap",
                "text": (
                    "Read document A. Identify its single core abstract claim, then list the "
                    "sub-claims a reader must accept for it to hold."
                ),
                "version": None,
            },
        ),
        (
            "local",
            "prompt",
            {"name": "decompose"},
            {
                "name": "decompose",
                "text": (
                    "Split the core claim into independently verifiable sub-claims. For each, "
                    "state what evidence would confirm or refute it."
                ),
                "version": None,
            },
        ),
        (
            "local",
            "prompt",
            {"name": "verify"},
            {
                "name": "verify",
                "text": (
                    "Compare each sub-claim against its cited primary source. Report deviations "
                    "with a verbatim quote, URL, and locator."
                ),
                "version": None,
            },
        ),
    ]


def _build_events(store: RunStore) -> None:
    for event_type, payload, message, at in _events():
        store.append_event(event_type, payload, message=message, at=at)


def build(root: Path) -> None:
    """(Re)write ``events.jsonl`` and ``capabilities/**`` under ``root``."""
    events_path = root / "events.jsonl"
    if events_path.exists():
        events_path.unlink()
    capabilities = root / "capabilities"
    if capabilities.exists():
        shutil.rmtree(capabilities)

    store = RunStore(root)
    store.init_layout()
    _build_events(store)

    cache = ResponseCache(capabilities)
    for provider, op, params, response in _capability_records():
        cache.write(provider, op, params, response, recorded_at=RECORDED_AT)


def _snapshot(root: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    events_path = root / "events.jsonl"
    if events_path.is_file():
        snapshot["events.jsonl"] = events_path.read_bytes()
    capabilities = root / "capabilities"
    if capabilities.is_dir():
        for path in sorted(capabilities.rglob("*.json")):
            snapshot[str(path.relative_to(root))] = path.read_bytes()
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="sample directory")
    parser.add_argument("--check", action="store_true", help="verify fixtures are up to date")
    args = parser.parse_args(argv)
    root = Path(args.root)

    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "root"
            build(candidate)
            if _snapshot(root) != _snapshot(candidate):
                print(f"fixtures under {root} are stale; run scripts/build_sample_fixtures.py")
                return 1
        print(f"fixtures under {root} are up to date")
        return 0

    build(root)
    print(f"wrote fixtures under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
