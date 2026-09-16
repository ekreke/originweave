# 产品概览 · originweave

## 1. 一句话定义

给定资料 A，抽取其**核心抽象论点**，定位论点的**真实源头**，判定 A 相对源头的
**偏差**，输出**可审计的溯源 DAG + 偏差记分卡**（每项结论带来源 URL + 逐字引用，
可回链、可重放）。

## 2. 问题与设计原则

现代文档（技术博客、报道、营销材料、二手转述）中的说法，往往在传播链上被
强化、改写、省略或错误归因。人工核查既慢又难以复用证据。

originweave 的四条硬性原则：

1. **可审计（auditable）**：任何结论都必须能回链到具体来源与**逐字引用**
   （`quote` + `url` + `locator`）。禁止无来源断言。
2. **可重放（replayable）**：一次 run 的全部输入与事件被持久化（含人工输入），
   `replay` 可在不触网的情况下字节级复现结论。
3. **偏差而非真伪（deviation, not verdict-on-truth）**：产品衡量的是"描述相对源头
   发生了什么变化"，而非替用户做出最终事实裁量。
4. **抽象论点优先（claim-first）**：核心对象是**抽象论点**而非原子事实。抽象论点
   必须被拆解为可独立验证的子断言，再逐条回链与判定。

## 3. 输入与产物

| | 内容 |
|---|---|
| 输入 | 资料 A：网页 URL（`sourceType: url`）或纯文本（`sourceType: text`）；以及可选的 `goal`（停止条件/判定标准） |
| 产物 | ① 溯源 DAG（Fact/Intent 节点 + 边 + 证据）② 偏差记分卡（deviation 列表）③ report（verdict + summary + findings + sources）④ append-only 事件时间线 |

## 4. 领域模型（冻结契约）

字段名即对外契约。黑板元素（Fact/Intent/Hint）的完整语义与事件协议见
[`blackboard-protocol.md`](blackboard-protocol.md)。

### Project
```text
Project { id, name, description, runCount, updatedAt, accent }
```

### Run
```text
Run {
  id,                      # "run_009" 形态
  projectId, title,
  sourceType,              # url | text
  status,                  # queued | running | awaiting_human | paused | stopped | completed | failed
  goal,                    # 停止条件 / 判定标准
  facts, deviations,       # 计数
  intents: { open, done }, # Intent 计数
  confidence,              # 0..1 整体置信度
  steps:  { current, total },
  budget: { tokens, cost, elapsed },
  createdAt, updatedAt
}
```
`status` 语义：`awaiting_human` = HITL Gate 挂起（见 `blackboard-protocol.md` 第 7 节）；
`paused` = 人工暂停（可恢复）；`stopped` = 预算（`--max-steps`/`--max-wall`/`--max-cost`）
触顶或人工终止，已落盘中间态（不可续跑，需新建 run）；`failed` = 执行异常终止。
`paused`/`stopped`/`failed` 的 run 在 `replay` 时仍可完整复现到终止点。

### 黑板事实图
```text
Fact {
  id, label, subtitle,
  kind,                    # origin | goal | fact | citation | source | boundary | compare | deviation
  role,                    # main-claim | sub-claim | none
  status,                  # verified | open | flagged | review
  confidence,              # 0..1
  note,
  position: { x, y },
  evidence: Evidence[]
}

Intent {
  id, type, status,        # type: decompose | explore | verify
  from, question,          # status: open | claimed | done | dropped | awaiting_human
  producedFacts[],
  claimedBy, heartbeatAt, createdAt
}

Hint { id, text, author, createdAt }   # author: human | agent

Edge {
  id, source, target,
  relation,                # main-chain | dependency | goal-derived | decomposes | spawns | resolves
  note
}

Evidence { id, quote, sourceTitle, url, locator }
```

`kind` 语义：
- `origin` — 起点，资料 A 的锚点。
- `goal` — 终点，溯源停止条件 / 判定标准。
- `fact` — 从 A 抽出的事实性主张（`role=main-claim` 核心抽象论点，`role=sub-claim` 子断言）。
- `citation` — A 中的引用/转述环节。
- `source` — 回链到的一手来源或原始数据。
- `boundary` — 由 goal 推导出的边缘事实/停止条件。
- `compare` — 比对引擎节点，汇总 facts × sources × goal。
- `deviation` — 由比对产生的偏差节点。

`relation` 语义：
- `main-chain` — 主链推导（论点 → 引用 → 源头）。
- `dependency` — 支撑关系。
- `goal-derived` — 由 goal 推导。
- `decomposes` — 抽象论点 → 子断言。
- `spawns` — Fact → Intent（探索声明）。
- `resolves` — Intent → Fact（产出结论）。

### Deviation 与 Report
```text
Deviation { id, title, summary, severity, confidence, nodeId }   # severity: high | medium | low

Report {
  runId, verdict,          # 如 "部分偏差"
  summary,
  findings: Deviation[],
  sources:  Evidence[]
}
```

### Event（事件溯源时间线）
```text
Event {
  id, at, type,           # type: PROJECT | INTENT | EXECUTE | CONCLUDE | REASON |
  message, tone,          #       COMPLETE | HEARTBEAT | RELEASE | HINT |
  payload                 #       REQUEST_HUMAN | HUMAN_INPUT
}                          # tone: info | success | warning | danger
```
事件类型（黑板协议）：`PROJECT` / `INTENT` / `EXECUTE` / `CONCLUDE` / `REASON` /
`COMPLETE` / `HEARTBEAT` / `RELEASE` / `HINT` / `REQUEST_HUMAN` / `HUMAN_INPUT`。
`type` 决定事件种类，`payload` 携带该种类的结构化字段（逐事件字段表见
[`blackboard-protocol.md`](blackboard-protocol.md) 第 5 节）；`message` / `tone` 仅用于展示。

## 5. CLI 面（冻结）

```text
originweave --version

originweave trace <target> [--out report.md] [--run <dir>]
                 [--provider exa|parallel] [--prompt-provider local|langfuse]
                 [--max-steps N] [--max-wall <dur>] [--max-cost <usd>]
                 [--auto] [--json]
originweave ui   [--run <dir>] [--port 8765]
originweave replay <run-dir>
originweave capabilities list|install-obscura
originweave mcp [--run <dir>]
originweave init
```

`--auto`：全自动，跳过 HITL Gate（默认人工介入）。

实现状态：`init`（生成 `originweave.toml`，已存在需 `--force`）与
`capabilities list` 已实现（M0b）；`trace` / `ui` / `replay` / `mcp` /
`capabilities install-obscura` 仍为占位，逐个 milestone 落地（`src/originweave/cli.py`）。

## 6. 非目标（Non-goals）

- 不做"真/假"的终审判定；只给出偏差与证据（verdict 表述为偏差性质）。
- 不做通用搜索引擎；检索能力由可替换的 capability provider 提供。
- 不做多租户 / 权限体系（1.0 范围内）。
- 不在前端做执行编排或容器生命周期管理（见 `agent-design.md` 第 7 节）。
