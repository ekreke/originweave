# 黑板协议 · originweave

本文冻结 originweave 的**执行协议**：黑板元素、Agent 工作循环、事件、协调方式与
人机协同（HITL）。设计参考黑板架构（Blackboard，Cairn / Hearsay-II 范式）：
**不给系统预设固定路径、流程与角色，路径从黑板上涌现**。

与 `agent-design.md` 的分工：本文定义「协议与数据」；`agent-design.md` 定义
「分层、capability、预算、运行时与架构红线」。

## 1. 为什么是黑板

溯源的本质是**在近乎无限的状态空间中做有向搜索**：`origin`（资料 A）明确、
`goal`（判定标准）明确、中间路径未知。状态空间搜索需要三样东西：

- 已确认的发现 —— `Fact`
- 待探索的方向 —— `Intent`
- 保留的因果链（含死胡同）—— 事件溯源

黑板是这三者的最自然载体：一块**共享的、append-only 的全局状态**，Worker 各自
读取当前状态、各自贡献新知识，没有中心调度写死流程。

## 2. 黑板元素

```text
Board {
  status,               # queued | running | awaiting_human | paused | stopped | completed | failed
  origin:  Fact,        # 特殊 Fact，kind=origin（role=none）
  goal:    Fact,        # 特殊 Fact，kind=goal（role=none）
  facts:   Fact[],      # 已确认的发现
  intents: Intent[],    # 待探索的方向（粉笔问号）
  hints:   Hint[],      # 经验提示（便利贴）
  edges:   Edge[],      # provenance 边
  entities:  Entity[],  # 实体-关系图节点（analysis 含 relation 时）
  relations: Relation[],# 实体-关系图边
  decisions: HumanDecision[],   # HUMAN_INPUT 记录
  waitingFor?: { gate, question },   # 仅 status = awaiting_human
  verdict?: str         # COMPLETE 后的整体判定
}
```

> `Board` 是 `reduce(events) -> Board` 的产物（纯函数 fold）；事件是唯一事实来源。

### 2.1 Fact（已确认的发现）
```text
Fact {
  id, label, subtitle,
  kind,                 # origin | goal | fact | citation | source | boundary | compare | deviation
  role,                 # main-claim | sub-claim | none   （抽象论点 vs 其拆解出的子断言）
  status,               # verified | open | flagged | review
  confidence,           # 0..1
  note,
  position: { x, y },   # 渲染侧可重算
  evidence: Evidence[]
}

Evidence { id, quote, sourceTitle, url, locator }
```

`kind` 语义：
- `origin` — 起点，资料 A 的锚点（原 `root`「描述」）。
- `goal` — 终点，溯源停止条件 / 判定标准（原 `root`「goal」）。
- `fact` — 从 A 抽取出的事实性主张（`role=main-claim` 为核心抽象论点，`role=sub-claim` 为其子断言）。
- `citation` — A 中的引用/转述环节。
- `source` — 回链到的一手来源或原始数据。
- `boundary` — 由 goal 推导出的边缘事实/停止条件。
- `compare` — 比对引擎节点，汇总 facts × sources × goal。
- `deviation` — 由比对产生的偏差节点。

### 2.2 Intent（待探索的方向）
```text
Intent {
  id,                   # "i002"
  type,                 # decompose | explore | verify | extract | relate
  status,               # open | claimed | done | dropped | awaiting_human
  from,                 # 来源 Fact id，或 "origin"
  question,             # 探索声明（一句话，可审计）
  producedFacts[],      # 该 Intent 产出的 Fact id 列表
  claimedBy,            # 认领者（worker 运行时 id）
  heartbeatAt,          # 心跳时间戳（超时自动释放）
  createdAt,
  duplicateOf           # status=dropped 时：被重复的既有 Intent id（Validate 填入，可空）
}
```

`type` 语义（**这是 originweave 相对 Cairn 的关键扩展**）：
- `decompose` — 把抽象论点拆解为可独立验证的子断言（claim → sub-claim）。
- `explore` — 为某个 Fact 寻找引用/一手来源（→ citation / source）。
- `verify` — 对事实与来源做比对、判定偏差（→ compare / deviation）。
- `extract` — 从 A 抽取实体（→ `Entity`；`analysis` 含 relation 时）。
- `relate` — 判别实体间关系（→ `Relation`；可带证据或标记 `inferred`）。

### 2.3 Hint（经验提示）
```text
Hint { id, text, author, createdAt }   # author: human | agent
```
Hint 表达"经验提示"（如"优先核对原始 benchmark 的测试环境"），不参与 DAG 连通性，
不改变事实，只影响 Reason 的取向。人类可随时写入。

### 2.4 Edge（provenance 边）
```text
Edge { id, source, target, relation, note }
     # relation: main-chain | dependency | goal-derived | decomposes | spawns | resolves
```
- **结构性边**由 reducer 自动推导：`spawns`（`intent.from → intent`）、
  `resolves`（`intent → producedFacts`）、`decomposes`（`decompose` 型 intent 的
  `from → producedFacts`）。
- **语义性边**（`main-chain` / `dependency` / `goal-derived`）无法从字段推出，
  必须由事件 `payload.edges` 显式携带。

### 2.5 HumanDecision（人工裁决记录）
```text
HumanDecision { gate, decision, text, targets[], author:human, at }
```
由 `HUMAN_INPUT` 事件派生；与 `Hint` 不同，它是对 Gate 的**控制决策**，会解除
`awaiting_human`。

### 2.6 Entity / Relation（实体-关系图）
```text
Entity {
  id, name, type,          # type: person | organization | product | location | event | other
  aliases: string[],       # 同名/别名归并结果
  status,                  # verified | open | flagged
  confidence, note,
  position, evidence: Evidence[]
}

Relation {
  id, source, target,      # Entity id（有向）
  type,                    # 关系本体（见 product-overview.md 第 4 节「关系本体」表）
  label,                   # 原文表述
  status,                  # verified | inferred | open | flagged
  confidence, inferred,    # inferred=true 表示无来源推断（渲染虚线）
  note, evidence: Evidence[]
}
```
与溯源 DAG 并列的**第二张图**，共享同一 run 与事件溯源。实体按规范化名称归并
（累积 `aliases`）；关系允许无来源推断，但必须 `status=inferred` + `inferred=true`
并带置信度，渲染为虚线。本体只建正向类型，反向标签由渲染层派生。

## 3. 三层职责（对应架构红线）

| 层 | 职责 | 明确不做 |
|---|---|---|
| **Server / Blackboard** | 黑板一致性：Facts/Intents/Hints 的持久化与一致，**协议的唯一事实源** | 不做任何推理与决策 |
| **Dispatcher** | 调度与容器生命周期；任务派发与协议写回（**协议的唯一写入者**） | 不做推理 |
| **Worker** | 接收 prompt，执行任务，返回结构化结果 | 不直接认领 Intent、不发心跳、不直接调用协议接口 |

Worker 只看到两样东西：**当前完整黑板图** + **一条任务指令**。系统里没有任何一行
代码告诉 Worker"溯源该怎么做"。

**Worker 实现可替换（M6）**：Worker 的执行体由 `[worker].provider` 选择——`local` 为单轮
`model` 调用，`pi` 为经 `pi-py-sdk` 驱动的 Pi agent 运行时（可多轮、可用工具）。无论哪种，
Worker **仍只返回一个严格 JSON 对象**、**仍不写协议**；Dispatcher/Engine 依旧是唯一写入者。
一次 Worker 调用 = 一个**隔离会话**：上下文不跨调用共享，原始输入/输出与步骤链落
`sessions/<id>.json`，并以 `SESSION` / `WORKER_STEP` 事件建索引（§5）。

## 4. Agent 工作循环

### 4.1 OODA 循环
```text
Observe  → 读取黑板上的完整图（Origin/Goal/Facts/Intents/Hints + 预算）
Orient   → 判断当前态势（进展、死胡同、是否已可判定）
Decide   → 声明探索意图（写 Intent），或判定 Complete / 无操作
Act      → 执行探索（Explore：经 capability 检索、比对等）
Write Back → 把结论写回黑板（Fact + Evidence）
```

### 4.2 任务指令（每次只给其一）
| 任务 | 做什么 | 产出 |
|---|---|---|
| `Bootstrap` | 初始阶段直接尝试解决整个问题：**抽取核心抽象论点 + 直接尝试判定** | Fact + 可能的 Complete |
| `Reason` | 读图判断：完成了吗？下一步往哪走？ | Complete / 新 Intent(s) / 无操作 |
| `Explore` | 认领一条 Intent，执行探索，产出结论 | 一个 Fact（`extract`/`relate` 时产出 Entity/Relation） |
| `Validate` | 对 `Reason` 产出的候选 Intent 判重/取舍（独立 pass） | 每个候选的 keep / drop（drop → `dropped` Intent） |

Worker 的结构化输出（**冻结**）：Worker 只返回**一个 JSON 对象**——不含 id、不含边；id 与结构性
边由 Dispatcher / reducer 分配与推导（§2.4）。`kind`/`role`/`status`/`type` 取值域见 §2，
非法即视为解析失败。

```json
{
  "facts": [
    { "label": "...", "subtitle": "...", "kind": "fact", "role": "main-claim",
      "status": "open", "confidence": 0.8, "note": "...",
      "evidence": [ { "quote": "...", "sourceTitle": "...", "url": "...", "locator": "..." } ] }
  ],
  "intents": [ { "type": "decompose", "from": "f1", "question": "..." } ],
  "complete": { "verdict": "..." }
}
```

- `complete` 为 `null` 表示未判定完成。
- 一次 `Bootstrap` 的 `facts` 为 **0..N 个 `role=main-claim`**——资料 A 可能含**多个**核心抽象
  论点（`kind=fact`）；`Explore` 通常产出 1 个 Fact（`extract`/`relate` 时产 Entity/Relation，归 M5）。

`Validate` 指令的输出是**另一套 schema**（对候选 Intent 的取舍，而非新事实）：

```json
{ "keep": [0, 2],
  "drop": [ { "index": 1, "duplicateOf": "i3", "reason": "..." } ] }
```

- `index` 是候选 Intent 在本次 `Reason` 输出里的下标；`duplicateOf` 指向黑板上的既有 Intent id
  （批内重复时可空）。每个候选必须**恰好**出现在 `keep` 或 `drop` 之一，否则视为失败。
- 被判重的候选仍以 `INTENT` 事件写入，但 `status=dropped`（保留"考虑过但未采纳"的因果链）；
  keep 的写为 `status=open` 待派发。去重是**产出期**行为，发生在 Dispatcher 写入 `INTENT` 之前。
- **无结构预筛**：全部候选都交给 Validate 做语义判重（每轮 Reason 因此多一次模型调用）；
  Reason 未产出候选时跳过 Validate（不调模型、不发 `VALIDATE` 事件）。

`Explore` 指令的检索上下文由**引擎**准备：Dispatcher 先写 `EXECUTE`（认领），再由引擎调用
`search` capability（query = Intent 的 `question`），把检索结果与该 Intent（`{id, type, from,
question}`）一起经 `extra` 注入 worker 的 user 消息——**provider 选择留在引擎层**（红线 4），
worker 自身不触碰外部服务；检索结果全文随 `WorkerReply.input` 落会话快照。产出的 Fact 必须
匹配 Intent 类型：`explore` → `citation`/`source`（`role=none` 且**至少一条** `Evidence`），
`decompose` → `fact`/`sub-claim`。回复夹带 `intents` / `complete`、kind/role 不符或证据缺失
均视为失败。`verify` 型 Intent 依赖 `compare`（M2），派发时保持 `open`。

各任务（Bootstrap / Reason / Explore / Validate）的**非法回复与模板缺失一律写 `FAILED` 终态
事件**（原始回复经会话快照留痕，供审计），不向调用方抛异常——失败的因果链完整落在事件日志里，
`replay` 可复现到死亡点。

**派发（I4）**：一轮派发把快照上所有 `open` 且 `type∈{explore,decompose}` 的 Intent 先按 id 序
统一写 `EXECUTE` 认领（worker 标签按序 `worker-1..N`），再以 `[worker].max_concurrency` 为上限
并发执行。每个 Explore pass 的原始结果先缓存在内存，**提交阶段按 Intent id 序**分配 Fact id、
写 `CONCLUDE`/`SESSION`——因此完成顺序不影响 Board（结构确定）；首个硬失败（provider/解析/超时
`fail`）写 `FAILED` 并停止提交。执行期间引擎按 `[worker].heartbeat_interval` 代写 `HEARTBEAT`；
整个 pass（含 `search` 与 worker 调用）超过 `[worker].heartbeat_timeout` 即判定失活，按
`heartbeat_on_timeout` 写 `RELEASE`（Intent 回 `open`，本轮其余继续）或 `FAILED`（终止 run）。

### 4.3 一道题的完整生命周期
```text
0 init      : 黑板仅 origin(资料 A) 与 goal(停止条件) 两个特殊 Fact
1 bootstrap : Worker 尝试 origin → goal 直达；写下首个 Fact（核心抽象论点）
2 未在预算内到达 goal，但写下 Fact
3 reason    : 态势变化 → 产出 0..N 个 Intent（open，去重）
4 dispatch  : Dispatcher 派发 open Intent；认领带心跳
5 explore   : Worker 执行 Intent（decompose / explore / verify）
6 结论写成 Fact（带 Evidence）回写黑板；Intent → done
7 重复 3–6（Stigmergy：新 Fact 引出新 Intent）
8 complete  : 抽象论点全部拆解 + 回链 + 偏差判定完成 → 连到 goal，run 结束
```

关键：`extract / fetch / link / compare` **不是写死的阶段**，而是 Intent `type` 按需涌现。

`analysis` 含 `relation`（或 `both`）时，同一循环改为处理 `extract`（抽实体）与 `relate`
（判关系）两类 Intent，产出写入 `entities` / `relations` 而非 `facts`；事件溯源、
心跳释放、Stigmergy 与 Gate 机制不变。

### 4.4 走查示例：一次 Bootstrap + Reason + 单轮派发（M1 I3）

用样例 `examples/copilot_productivity`（资料 A 是宣传文，含多个论点）走一遍。调用方构造
`origin`（资料 A，`kind=origin`）与 `goal`（停止条件，`kind=goal`），调 `Engine.run(origin, goal)`：
先跑一次 Bootstrap，再跑一次 Reason，然后派发 Reason 产出的开放 Intent（`explore` / `decompose`；
`verify` 待 M2）。多轮 Stigmergy 收敛（新 Fact 再触发 Reason）归 I6。

**Bootstrap** Worker 返回（严格 JSON，无 id、无边）核心抽象论点：

```json
{ "facts": [
    { "label": "Copilot 让 Accenture 开发者快 55%", "kind": "fact", "role": "main-claim",
      "status": "open", "confidence": 0.6 },
    { "label": "Copilot 让成功构建率 +84%", "kind": "fact", "role": "main-claim",
      "status": "open", "confidence": 0.55 },
    { "label": "Copilot 让工作满意度 +90%", "kind": "fact", "role": "main-claim",
      "status": "open", "confidence": 0.5 }
  ],
  "intents": [], "complete": null }
```

**Reason** Worker 读图后只返回候选 Intent（不产 facts）：

```json
{ "facts": [], "intents": [
    { "type": "decompose", "from": "f1", "question": "Split this claim into sub-claims." }
  ], "complete": null }
```

引擎把 Bootstrap 记为一条 `explore` Intent（Bootstrap 在协议里没有自己的 Intent，这样建模
才能像其他任务一样被审计与派发），把 Reason 记为一次 `REASON` 任务（**只有真正的 Reason
pass 才写 `REASON start/end`，Bootstrap 不被包裹**），并按 kind 前缀发放确定性 id
（`fact → f1/f2/f3`，`intent → i1/i2`、子断言 `fact → f4/f5`）。派发时 `decompose` 型 Intent
不检索，直接由 Explore 拆出子断言。`events.jsonl`（各次 Worker 调用的 `SESSION` / `WORKER_STEP`
索引事件从略）：

| id | type | payload |
|---|---|---|
| `e0001` | `PROJECT` | `origin`, `goal` |
| `e0002` | `INTENT` | `intent=i1`（`type=explore`, `from=origin`） |
| `e0003` | `EXECUTE` | `intentId=i1`, `worker=worker-1`, `model=...` |
| `e0004` | `CONCLUDE` | `intentId=i1`, `facts=[f1,f2,f3]` |
| `e0005` | `REASON` | `phase=start` |
| `e0006` | `INTENT` | `intent=i2`（`type=decompose`, `from=f1`, `status=open`） |
| `e0007` | `REASON` | `phase=end` |
| `e0008` | `EXECUTE` | `intentId=i2`, `worker=worker-1`, `model=...` |
| `e0009` | `CONCLUDE` | `intentId=i2`, `facts=[f4,f5]`（`role=sub-claim`） |

`reduce(events)` 折出的 `Board`（结构性边由 reducer 派生，§2.4）：

```text
status   running
facts    f1/f2/f3（均 role=main-claim）
         f4/f5（role=sub-claim，由 i2 拆解 f1 得到）
intents  i1（status=done, producedFacts=[f1,f2,f3], claimedBy=worker-1）
         i2（status=done, type=decompose, producedFacts=[f4,f5], claimedBy=worker-1）
edges    origin → i1 (spawns)
         i1 → f1 / f2 / f3 (resolves)
         f1 → i2 (spawns)
         i2 → f4 / f5 (resolves)
         f1 → f4 / f5 (decomposes)
```

要点：**Worker 不写协议、不起 id**；**引擎是唯一写入者**且只负责「取指令 → 读图 → 调能力 →
解析 → 发 id → 写事件」这条流水线；Reason 只能产 `open` 候选 Intent（生命周期字段由引擎重建），
且 `complete` 与 `intents` 互斥；派发为**单轮**（在 Reason 留下的快照上取 `open` 且
`type∈{explore,decompose}` 的 Intent，按 id 序执行，`verify` 保持 `open`），任一 pass 写 `FAILED`
即确定性中止本轮，新 Fact 引发的新一轮 Reason 归 I6；**所有"事实"都在 append-only 事件日志里**，
Board 永远由 `reduce` 折出，故可重放。

## 5. 事件协议（冻结）

run 的全部状态由 append-only 事件派生。事件取代此前的领域事件命名；领域含义
（claim 抽取、比对等）降为 `Fact.kind/note`。

| 事件 | 含义 | `payload` 内容 |
|---|---|---|
| `PROJECT` | run 创建，初始化 origin/goal | `origin: Fact`, `goal: Fact` |
| `INTENT` | 新 Intent 写入黑板 | `intent: Intent`, `edges: Edge[]`（语义边，可空） |
| `EXECUTE` | Worker 认领并开始执行某 Intent | `intentId`, `worker`, `model` |
| `CONCLUDE` | Worker 写下结论 Fact | `intentId`, `facts: Fact[]`, `edges: Edge[]`（语义边） |
| `REASON` | Reason 任务开始/结束 | `phase`(start\|end), `triggerFacts` |
| `COMPLETE` | 判定到达 goal，run 结束 | `verdict` |
| `HEARTBEAT` | 执行中 Intent 的心跳 | `intentId` |
| `RELEASE` | 心跳超时，Intent 释放回 `open` | `intentId`, `reason` |
| `HINT` | 注入 Hint | `hint: Hint`（含 `text`） |
| `REQUEST_HUMAN` | 关键节点请求人工介入，run → `awaiting_human` | `gate`, `question` |
| `HUMAN_INPUT` | 人类输入 | `gate`, `decision`, `text?`, `targets?`, `author=human` |
| `FAILED` | 执行异常终止，run → `failed` | `reason` |
| `STOPPED` | 预算触顶或人工终止，run → `stopped` | `reason`, `budget?` |
| `VALIDATE` | Validate 判重任务开始/结束 | `phase`(start\|end), `candidates`, `kept?`, `dropped?`, `drops[]?`（`{index, duplicateOf, reason}`）|
| `SESSION` | 一次 Worker 调用的会话元数据（索引，指向会话快照） | `sessionId`, `task`, `worker`, `intentId?`, `ref`（run dir 相对路径） |
| `WORKER_STEP` | 会话内的执行步骤（turn/tool 级；文本截断） | `sessionId`, `worker`, `intentId?`, `seq`, `kind`(turn-start\|tool-call\|tool-result\|message\|turn-end), `name?`, `text?`, `ok?` |
| `ENTITY` | 抽取/归并到实体 | `entity: Entity` |
| `RELATION` | 判别出实体间关系 | `relation: Relation` |

`SESSION` / `WORKER_STEP` **不参与 Board 状态派生**（reducer 忽略，同 `REASON`）：会话的原始
输入/输出全文只在 `sessions/<id>.json` 快照里，事件只作可重放的索引。因此 Board 结构与
`replay` 确定性不受影响。

`PROJECT`/`INTENT`/`CONCLUDE`/`HINT`/`ENTITY`/`RELATION` 的 payload **携带完整对象**
（而非仅 id），使 reducer 无需回查即可重建黑板；结构性边由 reducer 从 Intent 字段自动
推导（见 §2.4），payload 只带语义边。

```text
Event {
  id,
  at,
  type,      # PROJECT | INTENT | EXECUTE | CONCLUDE | REASON | COMPLETE |
             # HEARTBEAT | RELEASE | HINT | REQUEST_HUMAN | HUMAN_INPUT |
             # FAILED | STOPPED | VALIDATE | SESSION | WORKER_STEP |
             # ENTITY | RELATION
  message,   # 人类可读摘要（UI 时间线）
  tone,      # info | success | warning | danger
  payload    # 与 type 对应的结构化字段，见上表
}
```

`type` 与 `payload` 是重放的事实依据（reducer 只消费这两者）；`message`/`tone`
仅用于展示，不参与状态派生。

## 6. 协调：Stigmergy（间接协调）

Worker 之间**不直接通信**，只通过改变共享环境（黑板）来协调：

```text
Worker A 写入新 Fact  →  图变化（环境更新）  →  Worker B 下一轮读图感知  →  调整策略
```

图就是共享的"信息素环境"：更有价值的 Fact 引出更多 Intent，探索策略从个体循环中
涌现。**Worker 没有身份，只有任务；任务从图里来，不从角色定义里来。**

## 7. 人机协同（HITL）

默认**人工介入**；`[hitl].auto` / `CreateRunRequest.auto` 切换为全自动。两种模式并存：

| 模式 | 机制 | 阻塞 |
|---|---|---|
| 主动注入 | 随时写 `Hint(author=human)` | 否 |
| 被动 Gate | 关键节点发 `REQUEST_HUMAN`，run → `awaiting_human`，输入后继续 | 是 |

三个关键 Gate：
- **Gate A · 论点确认**（Bootstrap 之后、Reason 之前）：确认核心抽象论点（`role=main-claim`）
  后再去拆解。gate id = `confirm-claim`。
- **Gate B · 歧义裁决**（verify 阶段，置信度低或来源冲突时）：人工定夺口径/取值。gate id = `arbitrate`。
- **Gate C · 最终审阅**（记分卡产出前）：确认结论，或要求重查（产生新 Intent）。gate id = `review`。

**程序化挂起/恢复（M1，库层）**：非 auto 时，`Engine.run` 在 Bootstrap 产出 main-claim 后写
`REQUEST_HUMAN{gate:"confirm-claim", question}` 并返回 `awaiting_human` 的 Board（不再往下跑）。
调用方审阅后调 `Engine.resume(decision, text?, targets?)`：写 `HUMAN_INPUT`（`author=human`）并继续
——`approve` / `edit` 继续 Reason → dispatch，`reject` 写 `STOPPED`（人工终止）。**`edit` 目前仅记录**
（`text`/`targets` 进入 `HUMAN_INPUT`，黑板不变）；修改 Fact 需要契约新增「事实取代」事件，留待后续
切片，UI 层不得直接改黑板（红线 5）。`resume` 从黑板重建确定性 id 计数器，因此在同一 run dir 上
新建的 `Engine` 也能正确恢复（server 友好）。decision 取值冻结于 proto：`approve|edit|reject`。

人类输入亦以 `HUMAN_INPUT` 事件记录（`author=human`），因此**是输入而非旁路**：
不破坏可审计与可重放原则。

## 8. 可控性（内嵌协议）

- **随时停止/恢复**：run 状态完整保留，可从任意事件点恢复。
- **终止态落盘**：异常终止写 `FAILED`（→ `status=failed`），预算触顶/人工终止写 `STOPPED`
  （→ `status=stopped`）；两者都是事件，`replay` 可复现到终止点。`paused`（可恢复）尚无事件，
  随 M3 可控性引入。
- **Intent 心跳与超时（I4）**：执行中引擎按 `[worker].heartbeat_interval` 写 `HEARTBEAT`；
  超过 `[worker].heartbeat_timeout` 判定 Worker 失活，不再永久占住 Intent：`heartbeat_on_timeout=release`
  写 `RELEASE` 把 Intent 退回 `open`（供后续轮次/重试），`=fail` 写 `FAILED` 终止 run。两值均为
  `[worker]` 时长配置（默认 `15s` / `5m`，且须 `interval < timeout`）。
- **完整因果链永久保留**：包含所有死胡同（`dropped` Intent）。
- **可重放**：`replay` 只读、不触网、复现含人工输入在内的全部结论。

## 9. 与架构红线的对齐

- 黑板的持久化与一致性归 **Server**（对应"server 拥有调度与持久化"）。
- Dispatcher 承担调度与容器生命周期（对应"server 拥有运行时生命周期"）。
- Worker 全部运行在**每次 run 一个临时容器**内（container-per-run）。
- 前端只读由黑板派生的视图，**不拥有执行编排**。
