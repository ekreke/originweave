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
  createdAt
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

## 4. Agent 工作循环

### 4.1 OODA 循环
```text
Observe  → 读取黑板上的完整图（Origin/Goal/Facts/Intents/Hints + 预算）
Orient   → 判断当前态势（进展、死胡同、是否已可判定）
Decide   → 声明探索意图（写 Intent），或判定 Complete / 无操作
Act      → 执行探索（Explore：经 capability 检索、比对等）
Write Back → 把结论写回黑板（Fact + Evidence）
```

### 4.2 三种任务指令（每次只给其一）
| 任务 | 做什么 | 产出 |
|---|---|---|
| `Bootstrap` | 初始阶段直接尝试解决整个问题：**抽取核心抽象论点 + 直接尝试判定** | Fact + 可能的 Complete |
| `Reason` | 读图判断：完成了吗？下一步往哪走？ | Complete / 新 Intent(s) / 无操作 |
| `Explore` | 认领一条 Intent，执行探索，产出结论 | 一个 Fact（`extract`/`relate` 时产出 Entity/Relation） |

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

`--analysis relation`（或 `both`）时，同一循环改为处理 `extract`（抽实体）与 `relate`
（判关系）两类 Intent，产出写入 `entities` / `relations` 而非 `facts`；事件溯源、
心跳释放、Stigmergy 与 Gate 机制不变。

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
| `ENTITY` | 抽取/归并到实体 | `entity: Entity` |
| `RELATION` | 判别出实体间关系 | `relation: Relation` |

`PROJECT`/`INTENT`/`CONCLUDE`/`HINT`/`ENTITY`/`RELATION` 的 payload **携带完整对象**
（而非仅 id），使 reducer 无需回查即可重建黑板；结构性边由 reducer 从 Intent 字段自动
推导（见 §2.4），payload 只带语义边。

```text
Event {
  id,
  at,
  type,      # PROJECT | INTENT | EXECUTE | CONCLUDE | REASON | COMPLETE |
             # HEARTBEAT | RELEASE | HINT | REQUEST_HUMAN | HUMAN_INPUT |
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

默认**人工介入**；`--auto` 切换为全自动。两种模式并存：

| 模式 | 机制 | 阻塞 |
|---|---|---|
| 主动注入 | 随时写 `Hint(author=human)` | 否 |
| 被动 Gate | 关键节点发 `REQUEST_HUMAN`，run → `awaiting_human`，输入后继续 | 是 |

三个关键 Gate：
- **Gate A · 论点确认**（Bootstrap/decompose 之后）：确认核心抽象论点与其拆解树。
- **Gate B · 歧义裁决**（verify 阶段，置信度低或来源冲突时）：人工定夺口径/取值。
- **Gate C · 最终审阅**（记分卡产出前）：确认结论，或要求重查（产生新 Intent）。

人类输入亦以 `HUMAN_INPUT` 事件记录（`author=human`），因此**是输入而非旁路**：
不破坏可审计与可重放原则。

## 8. 可控性（内嵌协议）

- **随时停止/恢复**：run 状态完整保留，可从任意事件点恢复。
- **Intent 心跳超时自动释放**：Worker 崩溃不会永久占住 Intent。
- **完整因果链永久保留**：包含所有死胡同（`dropped` Intent）。
- **可重放**：`replay` 只读、不触网、复现含人工输入在内的全部结论。

## 9. 与架构红线的对齐

- 黑板的持久化与一致性归 **Server**（对应"server 拥有调度与持久化"）。
- Dispatcher 承担调度与容器生命周期（对应"server 拥有运行时生命周期"）。
- Worker 全部运行在**每次 run 一个临时容器**内（container-per-run）。
- 前端只读由黑板派生的视图，**不拥有执行编排**。
