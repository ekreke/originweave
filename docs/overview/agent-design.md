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

要求：

- provider/model/runtime 关注点解耦：编排逻辑不感知具体 provider 的 SDK。
- 离线优先：`LIVE=0`（默认）时走本地 cache / mock，`LIVE=1` 才触网
  （见 `Makefile` 的 `run` target 与 `ORIGINWEAVE_LIVE`）。
- 能力调用需可录制（record）与重放（replay），录制产物即 M0d 的 fixtures。

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
`decompose`（拆解抽象论点）/ `explore`（找来源）/ `verify`（比对判偏差）。
三者不是写死的阶段，而是按需涌现的 Intent 类型。

### 3.4 抽象论点落图
```text
origin(资料 A) --Bootstrap--> f1 核心抽象论点(role=main-claim)
f1 --Intent(decompose)--> f2/f3/f4 子断言(role=sub-claim)
f2 --Intent(explore)--> c1 引用 --> s1 源头(Evidence: quote+url+locator)
f1..f4 × s* --Intent(verify)--> p1 比对 --> d1/d2 偏差
全部子断言回链且偏差判定完成 --> COMPLETE(记分卡)
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

`trace` 支持三重预算，任一触顶即停止并落盘当前中间态：

| 参数 | 含义 |
|---|---|
| `--max-steps` | 最大步数（对应 Run.steps.total） |
| `--max-wall` | 最大墙钟时间 |
| `--max-cost` | 最大花费（对应 Run.budget.cost） |

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
└── report.md           # 最终产物（可再生成）
```

约定：

- `runs/` 与 `*.jsonl` 已加入 `.gitignore`，运行产物不入库。
- `originweave replay <run-dir>` 必须**只读**，不触网，字节级复现结论。
- 事件是唯一事实来源；任何视图（UI、report）都可由事件重建。
- 人类输入（`HUMAN_INPUT`）同样是事件，重放时一并复现。

## 6. Runtime：container-per-run

- 每个 run 启动一个**临时容器**执行实际任务；run 结束即销毁。
- 容器内运行**多个平等 Worker**（运行时可配置 N ≥ 1）。
- 容器生命周期（创建/监控/回收）由 **server** 拥有，前端与 CLI 不直接管理容器。
- 容器需要挂载该 run 的 run 目录，以写入事件与快照。
- 容器镜像与 server 镜像分离：server 常驻，runtime 短命。
- 安全边界：容器内可触网执行检索；server 仅负责编排与持久化。

## 7. 架构红线（不可突破）

1. **前端不拥有执行编排**：前端只调用 server API，不启动/调度任务。
2. **server 拥有调度与运行时生命周期**：run 的排队、执行、停止、回收都归 server。
3. **实际任务执行发生在临时容器**：任何执行路径都必须显式建模为 container-per-run，
   不允许在 server 进程内直接跑重任务。
4. **provider/model/runtime 解耦**：替换检索或 prompt provider 不应改动编排代码。
5. **黑板是唯一事实来源**：所有状态变更经事件写回黑板，不得旁路。

## 8. MCP 暴露

`originweave mcp` 将 capability（以及只读的 run 视图）以 MCP 形式暴露，供外部
agent/工具复用。MCP 是**消费能力**的入口，不承担容器调度职责。
