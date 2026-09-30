# organization_relations sample

样例：以 **relation 分析** 的视角核验同一份资料 A，抽取**组织实体**及其关系，产出独立的
**实体-关系图**（`analysis=relation`）。这是 `originweave replay` / `originweave ui` 的
关系图端到端 fixture（M5e）。

资料 A 与来源**复用** `examples/copilot_productivity/` 的冻结快照（本目录 `input/` 与
`sources/` 是同名副本），因此两种分析视角共享同一份一手材料；差异只在事件日志里处理的
Intent 类型（`extract`/`relate` 而非 `explore`/`verify`）。

## 资料与来源

| | 内容 |
|---|---|
| **资料 A** | `input/document.md` — Sityos AI *“55% Faster Code, 84% Better Builds: GitHub Copilot's Real Enterprise Impact”*（`sourceType: url`） |
| **S1（一手）** | `sources/github_copilot_lab_2022.md` — GitHub 2022 实验室研究 |
| **S2（一手）** | `sources/github_copilot_accenture_2024.md` — GitHub + Accenture 2024 企业研究 |

`input/source.json` 记录资料 A 的 `url`/`sourceType`/`fetchedAt`；`sources/manifest.json`
登记两个来源及其快照文件。所有关系证据的 `quote` 均可回链到这些快照。

## 实体

| id | name | type | status | conf. |
|---|---|---|---|---|
| n1 | GitHub | organization | verified | 0.95 |
| n2 | Microsoft | organization | verified | 0.90 |
| n3 | Accenture | organization | open | 0.85 |
| n4 | OpenAI | organization | open | 0.80 |

`n1` 另带别名 `GitHub, Inc.`（演示同名归并的 `aliases` 字段）。

## 关系（`EntityGraph.relations`）

| id | source → target | type | status | 依据 |
|---|---|---|---|---|
| r1 | n1 GitHub → n2 Microsoft | partners-with | verified | S1「GitHub Next conducted the experiment in partnership with the Microsoft Office of the Chief Economist」 |
| r2 | n1 GitHub → n2 Microsoft | subsidiary-of | **inferred** | 无直接来源 → `inferred=true`、`confidence=0.55`，前端渲染为**虚线** |
| r3 | n1 GitHub → n3 Accenture | partners-with | verified | S2「we partnered with Accenture to study how developers integrated GitHub Copilot into their daily workflows」 |
| r4 | n4 OpenAI → n1 GitHub | supplies | verified | 资料 A「GitHub Copilot is an AI pair programmer built on OpenAI's Codex…」 |

规则（`product-overview.md` §4）：一条关系**要么**带 `quote+url` 证据（`status=verified`），
**要么**标记为无来源推断（`inferred=true`、`status=inferred`、必须带 `confidence`）。

## 产物结构

```text
examples/organization_relations/
├── README.md              # 本文件
├── run.json               # 静态元数据（analysis=relation），非事件
├── input/                 # 资料 A 冻结快照 + source.json
├── sources/               # 一手来源快照 + manifest.json
├── events.jsonl           # append-only 事件日志（该次 run）
└── entity-graph.json      # 派生图（可由 events 重建，非事实来源）
```

## 运行

```bash
# 只读重放（确定性、不触网），摘要会列出 entities / relations 计数
uv run originweave replay examples/organization_relations
uv run originweave replay examples/organization_relations --json   # 全量 Board（含实体图）

# 审阅台：构建前端后按 analysis 显示 RELATIONS / ENTITIES 页签
make frontend-build
uv run originweave ui --run examples/organization_relations --port 8765

# 重新生成 events.jsonl + entity-graph.json（应逐字节一致）
make fixtures
```

## 事件日志

`events.jsonl` 由 `scripts/build_sample_fixtures.py` 用 `RunStore.append_event()` 生成
（固定时间戳），产物入库；测试会重生成并逐字节比对。事件覆盖 `PROJECT/HINT → Bootstrap
（核心论点 f1）→ REQUEST_HUMAN/HUMAN_INPUT（Gate A confirm-claim）→ extract（ENTITY×4）→
relate（每个实体一个 Intent，RELATION×4）→ COMPLETE`。图 pass 的事件形态与引擎一致：
`INTENT(extract|relate)/EXECUTE → ENTITY|RELATION* → CONCLUDE`。

`entity-graph.json` 由日志 fold 得到（`reduce(events)` → `EntityGraph`），与 `engine._flush_entity_graph`
同格式；`replay` 会从事件重算同一张图（测试断言二者一致）。
