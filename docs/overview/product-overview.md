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
   `replay` 可在不触网的情况下字节级复现结论。可重放针对的是**事件日志**；
   能力（检索 / 模型）调用本身**不保证可复现**。
3. **偏差而非真伪（deviation, not verdict-on-truth）**：产品衡量的是"描述相对源头
   发生了什么变化"，而非替用户做出最终事实裁量。
4. **抽象论点优先（claim-first）**：核心对象是**抽象论点**而非原子事实。抽象论点
   必须被拆解为可独立验证的子断言，再逐条回链与判定。

## 3. 输入与产物

| | 内容 |
|---|---|
| 输入 | 资料 A：网页 URL（`sourceType: url`）或纯文本（`sourceType: text`）；以及 `goal`（停止条件/判定标准；`CreateRun` 必填） |
| 产物 | ① 溯源 DAG（Fact/Intent 节点 + 边 + 证据）② 偏差记分卡（deviation 列表）③ report（verdict + summary + findings + sources）④ append-only 事件时间线 ⑤ 实体-关系图（可选，`CreateRun.analysis=relation\|both`） |

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
  analysis,                # provenance | relation | both（默认 provenance）
  status,                  # queued | running | awaiting_human | paused | stopped | completed | failed
  goal,                    # 停止条件 / 判定标准
  facts, deviations,       # 计数
  entities, relations,     # 实体-关系图计数（analysis != provenance 时）
  intents: { open, done }, # Intent 计数
  confidence,              # 0..1 整体置信度
  steps:  { current, total },
  budget: { tokens, cost, elapsed },
  createdAt, updatedAt
}
```
`status` 语义：`awaiting_human` = HITL Gate 挂起（见 `blackboard-protocol.md` 第 7 节）；
`paused` = 人工暂停（可恢复）；`stopped` = 预算（`max_steps`/`max_wall`/`max_cost`，`CreateRun` 字段）
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
  id, type, status,        # type: decompose | explore | verify | extract | relate
  from, question,          # status: open | claimed | done | dropped | awaiting_human
  producedFacts[],
  claimedBy, heartbeatAt, createdAt,
  duplicateOf              # status=dropped 时：被重复的既有 Intent id（Validate 填入，可空）
}
```
`extract` / `relate` 只在 `analysis` 含 relation 时使用，产出 `Entity` / `Relation`
（见下方实体-关系图小节），不改动 `facts`。

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

### 实体-关系图（`analysis` 含 relation 时）

与溯源 DAG **并列的第二张图**，共享同一 run 与事件溯源；节点是实体、边是实体间关系。
字段名同样是冻结契约。

```text
Entity {
  id, name,
  type,                    # person | organization | product | location | event | other
  aliases: string[],       # 同名/别名归并结果
  status,                  # verified | open | flagged
  confidence,              # 0..1
  note,
  position: { x, y },      # 渲染侧可重算
  evidence: Evidence[]     # 可空（允许无来源推断）
}

Relation {
  id,
  source, target,          # Entity id（有向）
  type,                    # 关系本体，见下表
  label,                   # A 中的原文表述（展示用，可为空）
  status,                  # verified | inferred | open | flagged
  confidence,              # 0..1
  inferred,                # true = 无来源推断（渲染为虚线）
  note,
  evidence: Evidence[]     # inferred 时可空
}

EntityGraph { entities: Entity[], relations: Relation[] }
```

`Entity.type` 语义：`person` / `organization` / `product` / `location` / `event` / `other`。

`Relation.status` 语义：`verified` = 有 `quote+url` 证据；`inferred` = 无来源推断
（`inferred=true`，渲染为虚线，须带置信度）；`open` = 待核实；`flagged` = 存疑。

**关系本体（预定义类型）**——只建正向，反向标签由渲染层派生（如 `subsidiary-of`
反读为「母公司」）：

| `type` | 方向 | 含义 |
|---|---|---|
| `subsidiary-of` | org → org | 隶属 / 子公司 |
| `invests-in` | person/org → org | 投资 |
| `acquires` | org → org | 收购 / 合并 |
| `partners-with` | org ↔ org | 合作（对称） |
| `competes-with` | org ↔ org | 竞争（对称） |
| `supplies` | org → org | 供应 |
| `employs` | org → person | 雇佣 / 任职 |
| `founded` | person/org → org | 创始 |
| `owns` | person/org → org | 拥有 / 控制 |
| `located-in` | org → location | 位于 |
| `other` | any | 未归入上述类型的兜底 |

同类实体**按规范化名称归并**（保留 `aliases`），保证 `replay` 产出确定性。

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
  payload                 #       REQUEST_HUMAN | HUMAN_INPUT | FAILED | STOPPED |
}                          #       VALIDATE | SESSION | WORKER_STEP | ENTITY | RELATION
                           # tone: info | success | warning | danger
```
事件类型（黑板协议）：`PROJECT` / `INTENT` / `EXECUTE` / `CONCLUDE` / `REASON` /
`COMPLETE` / `HEARTBEAT` / `RELEASE` / `HINT` / `REQUEST_HUMAN` / `HUMAN_INPUT` /
`FAILED` / `STOPPED` / `VALIDATE` / `SESSION` / `WORKER_STEP` / `ENTITY` / `RELATION`。
`type` 决定事件种类，`payload` 携带该种类的结构化字段（逐事件字段表见
[`blackboard-protocol.md`](blackboard-protocol.md) 第 5 节）；`message` / `tone` 仅用于展示。

### Session（Worker 会话，M6）
```text
Session {
  id, runId, worker, task,  # task: Bootstrap | Reason | Explore | Validate
  intentId?,                # 派发给 Intent 的任务有；Reason/Validate 为空
  model,
  input, output,            # 原始输入（渲染后的 prompt/board）与原始输出（回复文本）
  steps: SessionStep[],     # { seq, kind: turn-start|tool-call|tool-result|message|turn-end, name?, text?, ok? }
  startedAt, endedAt
}
```
一次 Worker 调用 = 一个**隔离会话**（上下文不跨调用共享），是一个"节点"任务的完整历史。
原始输入/输出全文落 run dir `sessions/<id>.json`；`SESSION` / `WORKER_STEP` 事件只作索引，
不参与 DAG 状态派生。Worker 执行体可插拔（`[worker].provider = local | pi`；默认 `pi`，
`PiWorker` 已于 **M6 P2** 实现，运行时缺失会明确报错），项目级可设 `maxConcurrency`（并发上限）、
`tools`（工具白名单）与 `budget`（`maxSteps` / `maxWall` / `maxCost`）。Worker 的 LLM 仅复用
`[capability.model]`，凭据仍只从环境变量读取。

## 5. CLI 面（冻结）

**起一次 run 的入口是 server / proto API**（见 `dashboard.md` §4 与 `proto/`），CLI 只提供
本地工具：事件重放、只读视图、能力检查、MCP 暴露与配置初始化。

```text
originweave --version
originweave init
originweave replay <run-dir> [--json]
originweave ui   [--run <dir>] [--port 8765]
originweave capabilities list|install-obscura
originweave mcp [--run <dir>]
```

说明：
- **无 `trace`**：核验由 `OriginweaveService.CreateRun`（proto）发起，编排与调度归 server
  （架构红线 2），不在 CLI 内跑重任务。
- `analysis`（`provenance|relation|both`）、预算（`max_steps`/`max_wall`/`max_cost`）与
  `auto`（跳过 HITL Gate）是 `CreateRunRequest` 的字段（或配置 `[hitl].auto`），不是 CLI flag。

实现状态：`init`（生成 `originweave.toml`，已存在需 `--force`）、`capabilities list`
（M0b）与 `replay`（M0c，只读重放）已实现；`ui` / `mcp` / `capabilities install-obscura`
仍为占位，逐个 milestone 落地（`src/originweave/cli.py`）。

## 6. 非目标（Non-goals）

- 不做"真/假"的终审判定；只给出偏差与证据（verdict 表述为偏差性质）。
- 关系图中的 `inferred` 边是**显式标注的推断**（虚线 + 置信度），不等同于有证据的结论。
- 不做通用搜索引擎；检索能力由可替换的 capability provider 提供。
- 不做 capability 级缓存 / 离线回放：`replay` 只重放事件日志，能力（检索 / 模型）始终真实调用。
- 不做多租户 / 权限体系（1.0 范围内）。
- 不在前端做执行编排或容器生命周期管理（见 `agent-design.md` 第 7 节）。
