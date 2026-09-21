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
不改变事实，只影响 Reason 的取向。两种写入方（M3）：
- **human**：经 `AddHint` 随时写入，非阻塞（§7）。
- **agent**：引擎在 **Reason 收敛时**写入（Reason reply 带可选 `hint`，§4.2）——
  仅当本轮真正收敛（结构判据满足的 `complete`，或提不出任何新 Intent 的死胡同）才落盘；
  与 `intents` 同携的 `hint` 被忽略。id（`h<N>`）由两处写入方共同从事件日志推导，绝不冲突。

### 2.4 Edge（provenance 边）
```text
Edge { id, source, target, relation, note }
     # relation: main-chain | dependency | goal-derived | decomposes | spawns | resolves
```
- **结构性边**由 reducer 自动推导：`spawns`（`intent.from → intent`）、
  `resolves`（`intent → producedFacts`）、`decomposes`（`decompose` 型 intent 的
  `from → producedFacts`）。
- **语义性边**（`main-chain` / `dependency` / `goal-derived`）无法从字段推出，必须由事件
  `payload.edges` 显式携带——由 Worker 在 reply 的 `edges` 中给出（`source`/`target` 可用 `key`
  引用同批新 Fact），引擎分配 id 后解析并写入 `CONCLUDE`（§4.2）。

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
| `Reason` | 读图判断：完成了吗？下一步往哪走？ | Complete / 新 Intent(s) / 无操作（收敛时可附 `hint`） |
| `Explore` | 认领一条 Intent，执行探索，产出结论 | 一个 Fact（`extract`/`relate` 时产出 Entity/Relation） |
| `Validate` | 对 `Reason` 产出的候选 Intent 判重/取舍（独立 pass） | 每个候选的 keep / drop（drop → `dropped` Intent） |

Worker 的结构化输出（**冻结**）：Worker 只返回**一个 JSON 对象**——不含 id；id 与**结构性**边由
Dispatcher / reducer 分配与推导（§2.4），**语义**边由 Worker 显式携带（`edges`，见下）。`kind`/
`role`/`status`/`type` 取值域见 §2，非法即视为解析失败。

```json
{
  "facts": [
    { "key": "c1", "label": "...", "subtitle": "...", "kind": "fact", "role": "main-claim",
      "status": "open", "confidence": 0.8, "note": "...",
      "evidence": [ { "quote": "...", "sourceTitle": "...", "url": "...", "locator": "..." } ] }
  ],
  "edges": [ { "source": "origin", "target": "c1", "relation": "main-chain", "note": "..." } ],
  "gate": { "gate": "arbitrate", "question": "..." },
  "intents": [ { "type": "decompose", "from": "f1", "question": "..." } ],
  "complete": { "verdict": "..." },
  "hint": "..."
}
```

- `complete` 为 `null` 表示未判定完成；`gate` 为 `null` 表示无需人工介入。
- 一次 `Bootstrap` 的 `facts` 为 **0..N 个 `role=main-claim`**——资料 A 可能含**多个**核心抽象
  论点（`kind=fact`）；`Explore` 通常产出 1 个 Fact（`extract`/`relate` 时产 Entity/Relation，归 M5）。
- **`key`**（M2，可选，仅限本 reply 内唯一）：新 Fact 的本地引用，供 `edges` 引用**同批** Fact；引擎
  分配真实 id 后丢弃，**不写入 `Fact`**。
- **`edges`**（M2，可选）：语义边 `main-chain | dependency | goal-derived`（结构边由 reducer 派生，
  携带结构边即失败）。`source`/`target` 取黑板已有 Fact id 或本 reply 的 `key`；`Bootstrap` 与
  `Explore` 可携带，`Reason`/`Validate` 携带即失败。
- **`gate`**（M2，可选）：`gate` 仅 `arbitrate`（Gate B），与 `complete`/`intents` 互斥；**仅
  `Explore`（verify 型）可携带**。
- **`hint`**（M3，可选）：一条经验提示文本，**仅 `Reason` 可携带**（其余任务携带即失败）。
  引擎只在**收敛**时落盘为 `HINT{author:"agent"}`（结构判据满足的 `complete`，或无新 Intent 的
  死胡同）；与 `intents` 同携时忽略，非收敛的 `complete`（结构判据未满足）也不落盘。

`Validate` 指令的输出是**另一套 schema**（对候选 Intent 的取舍，而非新事实）：

```json
{ "keep": [0, 2],
  "drop": [ { "index": 1, "duplicateOf": "i3", "reason": "..." } ] }
```

- `index` 是候选 Intent 在本次 `Reason` 输出里的下标；`duplicateOf` 指向黑板上的既有 Intent id
  （批内重复时可空）。每个候选必须**恰好**出现在 `keep` 或 `drop` 之一，否则视为失败。
- **判重对象**：只有真正可运行/已执行的 Intent（`open`/`claimed`/`done`）才可作为重复依据；`dropped`
  的 Intent 从未执行，只作「曾考虑过」的上下文。引擎因此对**指向 `dropped` 的 drop 做确定性翻盘**——
  该候选保留为 `open`（`dropped` 的重做是合法方向，例如新证据到达后），被翻盘的 drop 记入
  `VALIDATE{phase:"end"}.overridden` 留痕。这防止 Validate 误杀重做导致无可派发 Intent 的死胡同。
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
均视为失败。

`verify` 型 Intent（M2）改为**派发**：引擎用 `prompts/compare.txt` 指令、**不检索**，让 Worker 在
已有 facts × sources × goal 上评分偏差，产出**恰好一个** `compare`（`role=none`、`status=verified`）
与 0..N 个 `deviation`（`role=none`、≥1 条 `Evidence`、`subtitle` 形如
`severity=<high|medium|low> · confidence=<c>` 且 `status` 与之匹配：high→`flagged`、medium/low→
`review`）。verify pass 可经 `gate` 请求 **Gate B**（§7）。

各任务（Bootstrap / Reason / Explore / Validate）的**非法回复与模板缺失一律写 `FAILED` 终态
事件**（原始回复经会话快照留痕，供审计），不向调用方抛异常——失败的因果链完整落在事件日志里，
`replay` 可复现到死亡点。

**派发（I4）**：一轮派发把快照上所有 `open` 且 `type∈{explore,decompose,verify}` 的 Intent 先按 id 序
统一写 `EXECUTE` 认领（worker 标签按序 `worker-1..N`），再以 `[worker].max_concurrency` 为上限
并发执行。每个 Explore pass 的原始结果先缓存在内存，**提交阶段按 Intent id 序**分配 Fact id、
写 `CONCLUDE`/`SESSION`——因此完成顺序不影响 Board（结构确定）；首个硬失败（provider/解析/超时
`fail`）写 `FAILED` 并停止提交。执行期间引擎按 `[worker].heartbeat_interval` 代写 `HEARTBEAT`；
整个 pass（含 `search` 与 worker 调用）超过 `[worker].heartbeat_timeout` 即判定失活，按
`heartbeat_on_timeout` 写 `RELEASE`（Intent 回 `open`，本轮其余继续）或 `FAILED`（终止 run）。

**收敛（I6）**：派发轮结束后，若产生了新 Fact，则对**新增 facts** 再跑一次 Reason（`REASON.start` 的
`triggerFacts` 只记自上次 Reason 以来的新增 facts），如此循环（Stigmergy）。循环终止于：Reason 写
`COMPLETE`（→ `completed`）；或三个非完成出口各写 `STOPPED`（→ `stopped`，携带 `reason`）：Reason 未
产出可派发的 `open` Intent（死胡同，`reason="dead-end: no runnable intent"`）、本轮未新增 Fact（无进展，
`reason="stalled: dispatch produced no new facts"`）、命中安全阀 `Engine(max_rounds=…)`
（`reason="max rounds reached"`）。三者都落终态，run 不再停在 `running`。**M2 起 `COMPLETE` 需过严格判据**（§4.3 第 8 步）：抽象论点全部拆解、
子断言全部被 `explore` 或 `verify` 处理（追过来源或判定过）、且已有 compare 判定偏差，否则 Reason 的
`complete` 被忽略、run 继续（`running`）。**注意**：被 `RELEASE` 退回 `open` 的 Intent 只有在后续某轮因其他新 Fact 触发 Reason 时
才会被重新派发；本轮若再无新 Fact，循环即停并写 `STOPPED{reason="stalled: dispatch produced no new facts"}`
（完整的重试/调度归 M3）。**非 auto 时**（HITL 开），判据满足后不直接写 `COMPLETE`，而是停在
**Gate C**（`REQUEST_HUMAN{gate:"review", verdict}`，run → `awaiting_human`）等人工确认记分卡
（§7）；`auto=true` 才直接 `COMPLETE` + `report.md`。

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
              （非 auto 时先停 Gate C 审阅记分卡，approve/edit 才落 COMPLETE + report.md）
```

关键：`extract / fetch / link / compare` **不是写死的阶段**，而是 Intent `type` 按需涌现。

`analysis` 含 `relation`（或 `both`）时，同一循环改为处理 `extract`（抽实体）与 `relate`
（判关系）两类 Intent，产出写入 `entities` / `relations` 而非 `facts`；事件溯源、
心跳释放、Stigmergy 与 Gate 机制不变。（M1 I6 的「本轮是否产生新 Fact」进度判据目前只看 `facts`；
待 M5 引入 `entities`/`relations` 后，判据一并纳入。）

### 4.4 走查示例：一次 Bootstrap + Reason + 单轮派发（M1 I3）

用样例 `examples/copilot_productivity`（资料 A 是宣传文，含多个论点）走一遍。调用方构造
`origin`（资料 A，`kind=origin`）与 `goal`（停止条件，`kind=goal`），调 `Engine.run(origin, goal)`：
先跑一次 Bootstrap，再跑一次 Reason，然后派发 Reason 产出的开放 Intent（`explore` / `decompose`；
`verify` 自 M2 起派发）。多轮 Stigmergy 收敛（新 Fact 再触发 Reason）归 I6。

**Bootstrap** Worker 返回（严格 JSON，无 id；语义边可选）核心抽象论点：

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
且 `complete` 与 `intents` 互斥；派发在 Reason 留下的快照上取 `open` 且
`type∈{explore,decompose,verify}` 的 Intent，按 id 序执行；任一 pass 写 `FAILED`
即确定性中止。示例为单轮快照；真实运行时每轮 dispatch 产生新 Fact 后会再跑 Reason（I6 收敛），
见 §4.2。**所有"事实"都在 append-only 事件日志里**，Board 永远由 `reduce` 折出，故可重放。

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
| `STOPPED` | 预算触顶、人工终止，或收敛循环的非完成出口（死胡同/无新 Fact/`max_rounds`），run → `stopped`（终态） | `reason`, `budget?`（`{steps, wall_seconds, cost, limits}`）, `rounds?`（`max_rounds` 命中时） |
| `PAUSED` | 可恢复暂停（`PauseRun`），run → `paused` | `reason?` |
| `RESUMED` | 从 `paused` 恢复（`ResumeRun`），run → `running` | — |
| `VALIDATE` | Validate 判重任务开始/结束 | `phase`(start\|end), `candidates`, `kept?`, `dropped?`, `drops[]?`（`{index, duplicateOf, reason}`）, `overridden[]?`（`{index, duplicateOf, reason}`，被引擎翻盘的 drop） |
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
             # FAILED | STOPPED | PAUSED | RESUMED | VALIDATE | SESSION |
             # WORKER_STEP | ENTITY | RELATION
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
| 主动注入 | 随时写 `Hint(author=human\|agent)` | 否 |
| 被动 Gate | 关键节点发 `REQUEST_HUMAN`，run → `awaiting_human`，输入后继续 | 是 |

主动注入的**消费时机**（M3）：`HINT` 是普通事件，引擎每轮循环从事件日志折出 Board，因此
**dispatch 执行期间注入的 Hint，只要循环继续（本轮产生了新 Fact），必然进入下一轮 Reason 的
Observe**，run 不会被阻塞或打断。边界：循环已停止的 run（死胡同、或本轮无新 Fact 而退出，均落
`stopped` 终态）不因 Hint 到达而自动重启——重启/重试归 M3 的完整调度；注入的 Hint 会留在
Board 上等下一轮 Reason。

三个关键 Gate：
- **Gate A · 论点确认**（Bootstrap 之后、Reason 之前）：确认核心抽象论点（`role=main-claim`）
  后再去拆解。gate id = `confirm-claim`。
- **Gate B · 歧义裁决**（verify 阶段，置信度低或来源冲突时）：人工定夺口径/取值。gate id =
  `arbitrate`。**M2**：由 verify 型 `Explore` pass 在 reply 的 `gate` 字段中请求（引擎写
  `REQUEST_HUMAN{gate:"arbitrate"}`，本轮已提交的 facts 不丢）；`resume` 支持 `arbitrate`。
- **Gate C · 最终审阅**（记分卡产出前）：确认结论，或要求重查（产生新 Intent）。gate id = `review`。
  **M3**：非 auto 时，Reason 满足**严格判据**（§4.3 第 8 步）后不直接写 `COMPLETE`，而是写
  `REQUEST_HUMAN{gate:"review", question, verdict}`（verdict = Reason 的结论文本，随 payload 携带供
  resume 折回）并停在 `awaiting_human`；`resume` 的 `approve`/`edit` 把该 verdict 写进 `COMPLETE` 并落
  `report.md`，`reject` 则**生成重查 Intent** 后继续循环——`targets` 里每个板上 fact id 生成一个
  `verify` Intent（重跑 compare 重评分），无有效 `targets` 时退化为一个 `explore`（`from=origin`），
  再次收敛会重新触发 Gate C。

**程序化挂起/恢复（M1，库层）**：非 auto 时，`Engine.run` 在 Bootstrap 产出 main-claim 后写
`REQUEST_HUMAN{gate:"confirm-claim", question}` 并返回 `awaiting_human` 的 Board（不再往下跑）。
调用方审阅后调 `Engine.resume(decision, text?, targets?)`：写 `HUMAN_INPUT`（`author=human`）并继续
——Gate A/B 的 `reject` 写 `STOPPED`（人工终止），Gate C 的 `reject` 生成重查 Intent 并继续（见上）。
**`edit` 目前仅记录**（`text`/`targets` 进入 `HUMAN_INPUT`，黑板不变）；修改 Fact 需要契约新增「事实
取代」事件，留待后续切片，UI 层不得直接改黑板（红线 5）。`resume` 从黑板重建确定性 id 计数器，因此在
同一 run dir 上新建的 `Engine` 也能正确恢复（server 友好）。decision 取值冻结于 proto：
`approve|edit|reject`。

人类输入亦以 `HUMAN_INPUT` 事件记录（`author=human`），因此**是输入而非旁路**：
不破坏可审计与可重放原则。

## 8. 可控性（内嵌协议）

- **随时停止/恢复**：run 状态完整保留，可从任意事件点恢复。
- **终止态落盘**：异常终止写 `FAILED`（→ `status=failed`）；预算触顶、人工终止，以及收敛循环的非完成
  出口（死胡同/无新 Fact/`max_rounds`）写 `STOPPED`（→ `status=stopped`）；两者都是事件，`replay` 可复现
  到终止点。**`PAUSED`/`RESUMED`（M3b）**：
  `PauseRun` 在轮次边界写 `PAUSED`（→ `status=paused`，可恢复），`ResumeRun` 写 `RESUMED` 续跑；
  `paused` 状态下计数器从黑板重建，可在新 `Engine` 上恢复。
- **Intent 心跳与超时（I4）**：执行中引擎按 `[worker].heartbeat_interval` 写 `HEARTBEAT`；
  超过 `[worker].heartbeat_timeout` 判定 Worker 失活，不再永久占住 Intent：`heartbeat_on_timeout=release`
  写 `RELEASE` 把 Intent 退回 `open`（后续轮次若因新 Fact 触发 Reason 才会重派；完整重试/调度归 M3），
  `=fail` 写 `FAILED` 终止 run。两值均为
  `[worker]` 时长配置（默认 `15s` / `5m`，且须 `interval < timeout`）。
- **完整因果链永久保留**：包含所有死胡同（`dropped` Intent）。
- **可重放**：`replay` 只读、不触网、复现含人工输入在内的全部结论。

## 9. 与架构红线的对齐

- 黑板的持久化与一致性归 **Server**（对应"server 拥有调度与持久化"）。
- 容器生命周期由 server 侧承担（`ServerContext`/`ContainerWorker`，M3a；对应"server 拥有运行时生命周期"）。
- Worker **每次调用**运行在**一个临时容器**内（container-per-worker）；Engine/Dispatcher 仍在
  server 进程内编排并写黑板。
- 前端只读由黑板派生的视图，**不拥有执行编排**。
