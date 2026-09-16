# Agent 与运行时设计 · originweave

本文定义 originweave 的**执行架构**：分层、能力抽象、黑板循环、预算控制、
事件溯源，以及"每次 run 一个容器"的运行模型。

- 黑板元素、事件协议、HITL 的详细定义 → [`blackboard-protocol.md`](blackboard-protocol.md)
- 架构红线（第 7 节）任何实现都不得突破。

## 1. 分层

| 层 | 职责 |
|---|---|
| Frontend | UI、任务发起、监控、审阅（**不做执行编排**） |
| Server | API、编排、持久化、调度、容器生命周期、黑板一致性 |
| Runtime | 每个 run 一个**临时容器**，执行实际任务（内含多个 Worker） |
| Deployment | server 运行在 Docker 中 |

## 2. Capability 抽象

外部能力通过 **capability** 访问，provider 可替换。契约在 `overview` 层冻结，
具体 provider 在 M0b/M3 落地。

| Capability | provider 取值 | 用途 |
|---|---|---|
| `search` | `exa` / `parallel` | 检索来源、定位一手材料 |
| `prompt` | `local` / `langfuse` | 获取 prompt 模板（本地文件或 Langfuse） |
| `model` | `local`（录制/回放，M1）；真实 provider 于 M3 | 执行 OODA 任务（Bootstrap/Reason/Explore），返回结构化结果（Fact/Intent） |

要求：

- provider/model/runtime 关注点解耦：编排逻辑不感知具体 provider 的 SDK。
- 离线优先：`LIVE=0`（默认）时走本地 cache / mock，`LIVE=1` 才触网
  （见 `Makefile` 的 `run` target 与 `ORIGINWEAVE_LIVE`）。
- 能力调用需可录制（record）与重放（replay），录制产物即 M0d 的 fixtures。`model`
  与 `search`/`prompt` 同构：`LIVE=0` 读 `capabilities/model/<hash>.json` 回放，
  `LIVE=1` 调用真实模型并录制（真实调用 M3 落地，当前抛 `ProviderUnavailableError`）。

### 2.1 配置（`originweave.toml`）

配置为**项目内 `originweave.toml`**（由 `originweave init` 生成；已存在时不覆盖，
需 `--force`）。读取用标准库 `tomllib`，写入用 `tomli-w`。**命令行 flag 覆盖配置值**
（该合并待 M1/M3 接线；M0b 仅提供配置加载与 provider 解析）。

```toml
# 下方注释仅为说明；`originweave init` 生成的文件是纯净数据，不含注释。
[live]                 # false = 离线优先（默认）
enabled = false
[hitl]                 # false = 三个 Gate 默认人工介入
auto = false
[capability.search]
provider = "exa"       # exa | parallel
[capability.prompt]
provider = "local"     # local | langfuse
directory = "prompts"  # local provider 的模板目录
[capability.model]
provider = "local"     # local = 录制/回放；真实 provider 于 M3
[budget]
max_steps = 60
max_wall = "10m"
max_cost = 2.0
[run]
dir = "runs"
```

> `[capability.model]` 与 `[budget]` 的其他字段是 M1 的契约；在 M1 落地前，config loader
> 仍会以未知键拒绝 `[capability.model]`（见 `SPEC.md` M1）。

- **未知键会报错**（`ConfigError`），避免 `max_step` 之类的拼写错误被静默忽略。
- **离线/联机开关的三处写法与优先级**（都指同一个 `[live].enabled`）：
  1. `originweave.toml` 的 `[live].enabled`（默认 `false`）
  2. 环境变量 `ORIGINWEAVE_LIVE`（`1/true/yes/on` / `0/false/no/off`），**覆盖**配置文件
  3. `[hitl].auto` / `CreateRunRequest.auto` 只控制 HITL，不改变联网开关
  行为：`false`（离线）→ capability 走**录制回放**（`Cached*`，不触网）；
  `true`（联机）→ 走**真实调用并录制**（`Recording*`）。解析入口为
  `capabilities.build_search()` / `build_prompt()`。
- **凭据只从环境变量读取**，不写入配置：`EXA_API_KEY` / `PARALLEL_API_KEY` /
  `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`。
- `local` prompt provider 从仓库 `prompts/` 目录读取 `*.txt` / `*.md` 模板。
- 现状：`search`/`prompt` 的 provider 注册表、离线/联机接线与凭据校验就绪（M0b）；
  `model` capability 于 M1 引入（录制/回放）；三者的**真实联网/模型调用在 M3 落地**，
  当前 `LIVE=1` 调用会给出明确错误。

### 2.2 录制与重放布局

每次 capability 调用存成**一个 JSON 文件**，按请求哈希直查，保证离线重放确定且不触网：

```text
<run-dir>/capabilities/<provider>/<request_hash>.json
{
  "provider": "exa",
  "op": "search",
  "params": { "query": "...", "limit": 10 },
  "response": [ ... ],
  "recordedAt": "<ISO-8601 UTC>"
}
```

`request_hash = sha256(canonical(provider + op + params))[:16]`（参数排序后哈希，
与书写顺序无关）。`LIVE=1` 时边调用边写入；`LIVE=0` 时只读该目录，未命中即报错。

## 3. 黑板循环

originweave 采用**黑板架构**：一块共享的 append-only 全局状态（黑板），
Worker 平等、无固定角色，路径从黑板上涌现。取代早期设计里的固定流水线。

### 3.1 OODA 循环
```text
Observe → Orient → Decide → Act → Write Back → (回 Observe)
```

### 3.2 三种任务指令（每次只给其一）
| 任务 | 做什么 | 产出 |
|---|---|---|
| `Bootstrap` | 直接尝试解决整个问题：抽取核心抽象论点 + 直接尝试判定 | Fact + 可能的 Complete |
| `Reason` | 读图判断：完成了吗？下一步往哪走？ | Complete / 新 Intent / 无操作 |
| `Explore` | 认领一条 Intent，执行探索 | 一个 Fact |

### 3.3 Intent 三型（抽象论点适配）
`decompose`（拆解抽象论点）/ `explore`（找来源）/ `verify`（比对判偏差），外加
`extract`（抽实体）/ `relate`（判关系）用于实体-关系图。
五者不是写死的阶段，而是按需涌现的 Intent 类型。

### 3.4 抽象论点落图
```text
origin(资料 A) --Bootstrap--> f1 核心抽象论点(role=main-claim)
f1 --Intent(decompose)--> f2/f3/f4 子断言(role=sub-claim)
f2 --Intent(explore)--> c1 引用 --> s1 源头(Evidence: quote+url+locator)
f1..f4 × s* --Intent(verify)--> p1 比对 --> d1/d2 偏差
全部子断言回链且偏差判定完成 --> COMPLETE(记分卡)
```

`analysis` 含 `relation`（或 `both`）时并行产出**实体-关系图**（`blackboard-protocol.md` §2.6）：
```text
origin(资料A) --Intent(extract)--> e1/e2/e3 实体(Entity: name+type+evidence?)
e1 × e2 --Intent(relate)--> r1 关系(Relation: type+quote 或 inferred 虚线)
实体按规范化名称归并(aliases) --> COMPLETE(关系图)
```

细节（字段、边 relation、事件协议）见 [`blackboard-protocol.md`](blackboard-protocol.md)。

### 3.5 协调与并发
- **Stigmergy（间接协调）**：Worker 不互相通信，只通过往黑板写 Fact 改变环境，
  其他 Worker 下轮读图感知并调整策略。
- **多 Worker 并发**：1.0 起支持 ≥2 个 Worker 并发认领 Intent；认领带心跳，
  超时自动释放（`HEARTBEAT` / `RELEASE`）。
- **Dispatcher**：调度与容器生命周期，是协议的唯一写入者；Worker 不直接认领
  Intent、不发心跳，只接收 prompt 并返回结构化结果。

## 4. 预算与停止条件

`CreateRun` / 配置支持三重预算，任一触顶即停止并落盘当前中间态：

| 参数 | 含义 |
|---|---|
| `max_steps` | 最大步数（对应 Run.steps.total） |
| `max_wall` | 最大墙钟时间 |
| `max_cost` | 最大花费（对应 Run.budget.cost） |

停止条件（`goal`）由第一性原理定义：日期边界、原始 benchmark、适用范围等。
**注意**：originweave 的 goal 不是"到达某节点即结束"，而是"停止条件 + 偏差判定
完成标准"——抽象论点全部拆解、回链、判定偏差之后才算 COMPLETE。
`goal` 同时派生 `boundary` 边缘事实节点，用于判定"是否越过停止条件"。

其他停止情形：① 证据链连通 ② 无可用 Intent（dead-end）③ 人工 Gate 挂起。

## 5. 事件溯源与 run 目录

一次 run 的全部状态由 **append-only 事件日志**派生，禁止原地修改历史。
事件类型见 [`blackboard-protocol.md`](blackboard-protocol.md) 第 5 节。

```text
<run-dir>/
├── events.jsonl        # append-only，每行一个 Event
├── input/              # 资料 A 快照（URL 抓取或文本）
├── sources/            # 来源快照（可回链的原文/存档）
├── capabilities/       # 录制的 capability 请求/响应（离线重放用）
├── entity-graph.json   # 实体-关系图快照（可重建，非事实来源）
└── report.md           # 最终产物（可再生成）
```

`events.jsonl` 每行一个 Event（`id` 单调 `e0001`、`at` 为 ISO-8601 UTC）：
```json
{"id":"e0001","at":"2026-09-16T00:00:00+00:00","type":"PROJECT","message":"","tone":"info","payload":{"origin":{...},"goal":{...}}}
{"id":"e0002","at":"2026-09-16T00:00:01+00:00","type":"INTENT","message":"","tone":"info","payload":{"intent":{"id":"i001","type":"explore","from":"origin",...},"edges":[]}}
```

约定：

- `runs/` 与 `*.jsonl` 已加入 `.gitignore`，运行产物不入库。
- `originweave replay <run-dir>` 必须**只读**：`reduce(events) -> Board` 后输出到 stdout
  （默认摘要，`--json` 为 canonical Board），**不写任何文件**、不触网。
- 事件是唯一事实来源；任何视图（UI、report）都可由事件重建。
- 人类输入（`HUMAN_INPUT`）同样是事件，重放时一并复现。

## 6. Runtime：container-per-run

- 每个 run 启动一个**临时容器**执行实际任务；run 结束即销毁。
- 容器内运行**多个平等 Worker**（运行时可配置 N ≥ 1）。
- 容器生命周期（创建/监控/回收）由 **server** 拥有，前端与 CLI 不直接管理容器。
- 容器需要挂载该 run 的 run 目录，以写入事件与快照。
- 容器镜像与 server 镜像分离：server 常驻，runtime 短命。
- 安全边界：容器内可触网执行检索；server 仅负责编排与持久化。

> **M1/M1c-1 的临时态**：容器化在 M3 落地。在此之前，引擎以**库层 + 进程内 Dispatcher**
> 运行（M1 单测驱动；M1c-1 由 server 进程内调用以打通 proto/前端）。这是**显式、临时**的
> 例外，红线 3 的正式满足在 M3；Dispatcher 接口必须与 M3 的容器 Dispatcher 一致，
> 使 M3 只需替换执行后端而不改编排。

## 7. 架构红线（不可突破）

1. **前端不拥有执行编排**：前端只调用 server API，不启动/调度任务。
2. **server 拥有调度与运行时生命周期**：run 的排队、执行、停止、回收都归 server。
3. **实际任务执行发生在临时容器**：任何执行路径都必须显式建模为 container-per-run，
   不允许在 server 进程内直接跑重任务（M1/M1c-1 的进程内 Dispatcher 为第 6 节所述临时态，
   正式满足在 M3）。
4. **provider/model/runtime 解耦**：替换检索 / prompt / model provider 不应改动编排代码。
5. **黑板是唯一事实来源**：所有状态变更经事件写回黑板，不得旁路。

## 8. MCP 暴露

`originweave mcp` 将 capability（以及只读的 run 视图）以 MCP 形式暴露，供外部
agent/工具复用。MCP 是**消费能力**的入口，不承担容器调度职责。
