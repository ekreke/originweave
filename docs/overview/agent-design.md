# Agent 与运行时设计 · originweave

本文定义 originweave 的**执行架构**：分层、能力抽象、黑板循环、预算控制、
事件溯源，以及"每个 Worker 调用一个临时容器"的运行模型。

- 黑板元素、事件协议、HITL 的详细定义 → [`blackboard-protocol.md`](blackboard-protocol.md)
- 架构红线（第 7 节）任何实现都不得突破。

## 1. 分层

| 层 | 职责 |
|---|---|
| Frontend | UI、任务发起、监控、审阅（**不做执行编排**） |
| Server | API、编排、持久化、调度、容器生命周期、黑板一致性 |
| Runtime | 每个 Worker 调用一个**临时容器**（container-per-worker），执行实际任务 |
| Deployment | server 运行在 Docker 中 |

## 2. Capability 抽象

外部能力通过 **capability** 访问，provider 可替换。契约在 `overview` 层冻结。
`search` 与 `model` 已在 **Phase R** 真实落地（M1 接入编排）；`langfuse` 于 M3。

| Capability | provider 取值 | 用途 |
|---|---|---|
| `search` | `exa` / `parallel` | 检索来源、定位一手材料 |
| `prompt` | `local` / `langfuse` | 获取 prompt 模板（本地文件或 Langfuse） |
| `model` | `openai`（OpenAI 兼容） | 执行 OODA 任务（Bootstrap/Reason/Explore/Validate），返回结构化结果（Fact/Intent） |
| `worker` | `local` / `pi` | **Worker 执行体**：`local` = 单轮 `model` 调用；`pi` = 经 `pi-py-sdk` 驱动的 Pi agent 运行时（多轮 + 工具，M6 P2）。仅产出回复文本与步骤，**不写黑板** |

**Worker 与会话（M6）**：一次 Worker 调用（一个"节点"任务，含 Bootstrap/Reason/Explore/Validate）
对应一个**隔离会话**：上下文与消息历史不跨调用共享，`pi` provider 每次新建 Pi session 并于结束
`dispose`。会话原始输入/输出与步骤链落 run dir `sessions/<id>.json`（快照，类比 `sources/`），
并由 `SESSION` / `WORKER_STEP` 事件建索引；**Engine 仍是黑板唯一写入者**，事件仍是唯一事实来源与
重放源。Pi 的工具（`[worker].tools`）可配置，检索类工具经 TS 扩展**回调 server `Search` RPC**，
使 `search` provider 仍可替换（红线 5）。

**PiWorker（M6 P2）** 每次调用均创建 ephemeral Pi RPC session：使用私有临时配置目录写入
OpenAI-compatible provider 配置，复用 `[capability.model]` 与 `OPENAI_API_KEY` /
`OPENAI_BASE_URL`，不改写用户 `~/.pi`。该目录通过 Pi 的 agent-dir 环境变量指定，而**变量名由 pi
构建的 `piConfig.name` 决定**（`<NAME>_CODING_AGENT_DIR`：上游 `pi` 为 `PI_CODING_AGENT_DIR`，
改名构建会不同）——**M6 P4 已按实际二进制推导**（`capabilities/pi.py` 的
`resolve_agent_dir_env_name`，从 `package.json` 读 `piConfig.name`/旧 `n.name`，缺省
`PI_CODING_AGENT_DIR` 并同时设置）。它要求 `node` 与 `pi` 在 `PATH`，缺失时给出安装指引；禁用自动
扩展发现、skills、上下文文件，并只传递 `[worker].tools` 的白名单。**M6 P4** 起 `search` 工具由包内
TS 扩展提供（`src/originweave/pi_extensions/search.ts`，以 `pi --no-extensions -e <ext.ts>
--tools search` 显式加载）；扩展不直连检索 provider，而是回调 server 的 `Search` RPC（地址由
`ORIGINWEAVE_SERVER_URL` 注入，默认 `http://127.0.0.1:8765`），provider 选择留在 Python（红线 5）。
当 worker 拥有 `search` 工具时（`[worker].provider=pi` 且 `tools` 含 `search`），`explore` 的检索由
agent 自主执行、引擎不再预取；否则（如 `local`）维持引擎预取并经 `extra` 注入。`cwd` 仅是 P2 的
工具默认根目录，容器级安全隔离归 M3/P6。

要求：

- provider/model/runtime 关注点解耦：编排逻辑不感知具体 provider 的 SDK。
- **能力为真实调用**：无离线缓存、无录制回放；网络与凭据是运行前提。
- 单元测试**注入 fake provider**，不打真网；CI 不依赖网络与凭据。
- 凭据**只从环境变量读取**（见 §2.1）。

### 2.1 配置（`originweave.toml`）

配置为**项目内 `originweave.toml`**（由 `originweave init` 生成；已存在时不覆盖，
需 `--force`）。读取用标准库 `tomllib`，写入用 `tomli-w`。**命令行 flag 覆盖配置值**
（该合并待 M1/M3 接线；M0b 仅提供配置加载与 provider 解析）。

```toml
# 下方注释仅为说明；`originweave init` 生成的文件是纯净数据，不含注释。
[hitl]                 # false = 三个 Gate 默认人工介入
auto = false
[capability.search]
provider = "exa"       # exa | parallel
[capability.prompt]
provider = "local"     # local | langfuse
directory = "prompts"  # local provider 的模板目录
[capability.model]
provider = "openai"     # OpenAI 兼容
model    = "deepseek-v4.1-flash"
base_url = ""           # 端点由 OPENAI_BASE_URL 提供（内网地址不入库）
[worker]                # Worker 执行体（M6）
provider = "pi"         # local | pi；Pi 运行时缺失会明确报错
max_concurrency = 1     # 本项目每次 run 的 worker 并发上限（>0 且 <=16；server 调度处强制）
tools = []              # Pi 工具白名单：search|read|grep|find|ls|bash|edit|write；空 = 不启用
heartbeat_interval = "15s"    # 单次 Worker 调用的 HEARTBEAT 上报间隔（I4）
heartbeat_timeout = "5m"      # 超过此值判定调用失活（须 > interval）
heartbeat_on_timeout = "release"  # release（Intent 回 open）| fail（run -> failed）
[worker.budget]         # 每次 Worker 会话的预算默认值
max_steps = 60
max_wall = "10m"        # 正整数 + ms|s|m|h|d
max_cost = 2.0
[run]
dir = "runs"
[project]
dir = "projects"        # 目录式 project 注册表根（M1c-1）
```

- `heartbeat_*` 是**单次调用**的租约（liveness），`[worker.budget].max_wall` 是**会话总预算**
  （M3 执行 → `STOPPED`）；两者语义不同。`release` 忠于协议 §8「超时自动释放」，`fail` 则终止 run。
- **持久化（M1c-1）**：`[run].dir` 下每次 run 一个目录（`events.jsonl` 为唯一事实来源，另有
  `run.json` 元数据与 `sessions/`）；`[project].dir` 是**目录式 project 注册表**根
  （`projects/<project_id>/project.json`）。`run_00N` 全局分配。**`run.json` 只存静态/输入元数据**
  （project/title/source_type/analysis/goal/budget 覆盖等）；status/计数由 `events.jsonl` + `reduce()`
  派生，样例等无 `run.json` 的目录也可只读服务。
- **workspace 存储（[storage].db）**：`WorkspaceStore` 把 runs/projects 的**静态元数据**收进一个
  SQLite 库（顶层 `[storage].db`，默认 `originweave.db`），`run.json`/`project.json` 仍写（双写、
  读优先 DB）；server 启动 `bootstrap_from_dirs` 幂等导入旧目录式注册表。**事件日志仍以
  `events.jsonl` 为准**（live server 写它）；`SqliteEventLog` 是事件后端的迁移目标，目前仅为
  显式导入/测试预留（仓库样例仍写 `events.jsonl`）——`open_run_store` 仅当库内已有该 run 的事件、
  或 run dir 自带含该 run 事件的 `events.db` 时才优先 SQLite。
- **HITL（M1 I5；Gate C 为 M3）**：`[hitl].auto=false`（默认）时 server 以 `auto=False` 构造 `Engine`，
  run 在 Bootstrap 后停在 **Gate A**（`REQUEST_HUMAN{gate:"confirm-claim"}`，run → `awaiting_human`），
  由 `Engine.resume(decision, text?, targets?)` 写 `HUMAN_INPUT` 后继续（`approve`/`edit` 继续
  Reason→dispatch，`reject` → `STOPPED`）；**Gate B**（`arbitrate`）由 verify pass 请求；**Gate C**
  （`review`，M3）在 Reason 满足严格判据后、写 `COMPLETE`/`report.md` 前挂起，`approve`/`edit` 确认
  记分卡、`reject` **生成重查 Intent**（`targets` 的 fact id → `verify`，否则一个 `explore` off
  `origin`）后继续循环（Gate A/B 的 `reject` 才是 `STOPPED`；`edit` 目前仅记录，Fact 修改待契约新增
  取代事件）；`auto=true` / `CreateRunRequest.auto` 跳过 Gate。
  `resume` 从黑板重建 id 计数器，可在新 `Engine` 实例上恢复。

- **未知键会报错**（`ConfigError`），避免 `max_step` 之类的拼写错误被静默忽略。
- **凭据只从环境变量读取**，不写入配置，且**多为可选**：
  - `search` 走公开的免费 MCP 端点（`https://mcp.exa.ai/mcp` / `https://search.parallel.ai/mcp`），
    **无需 key**；`EXA_API_KEY` / `PARALLEL_API_KEY` 存在时会被附带（换更高配额）。
  - `model` 用 `OPENAI_API_KEY`（`OPENAI_BASE_URL` 可覆盖配置里的 `base_url`）。
  - `prompt` 的 `langfuse` 用 `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`。
- `local` prompt provider 从仓库 `prompts/` 目录读取 `*.txt` / `*.md` 模板。
- 现状：`search`（exa/parallel 免费 MCP）与 `model`（OpenAI 兼容）已**真实落地**；
  `prompt` 的 `local` 可用（读文件），`langfuse` 于 M3。**能力无离线/录制回放**（Phase R 移除）。

## 3. 黑板循环

originweave 采用**黑板架构**：一块共享的 append-only 全局状态（黑板），
Worker 平等、无固定角色，路径从黑板上涌现。取代早期设计里的固定流水线。

### 3.1 OODA 循环
```text
Observe → Orient → Decide → Act → Write Back → (回 Observe)
```

### 3.2 任务指令（每次只给其一）
| 任务 | 做什么 | 产出 |
|---|---|---|
| `Bootstrap` | 直接尝试解决整个问题：抽取核心抽象论点 + 直接尝试判定 | Fact + 可能的 Complete |
| `Reason` | 读图判断：完成了吗？下一步往哪走？ | Complete / 新 Intent / 无操作（收敛时可附 `hint`，M3） |
| `Explore` | 认领一条 Intent，执行探索 | 一个 Fact |
| `Validate` | 对 `Reason` 的候选 Intent 判重/取舍（独立 pass，复用 `model`） | 候选的 keep / drop（drop → `dropped` Intent） |

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
- **多 Worker 并发（I4）**：一轮派发内，所有 `open` 的 `explore`/`decompose`/`verify` Intent 先按
  id 序统一 `EXECUTE` 认领，再以 `[worker].max_concurrency` 为上限并发执行；结果仍按 Intent id 序
  **提交回写**（分配 Fact id、写 `CONCLUDE`），故并发不改变 Board 结构（确定性）。`verify` 型
  （M2）走 compare pass（不检索），产出 compare + deviation。
- **心跳/超时释放（I4）**：执行期间引擎按 `[worker].heartbeat_interval` 写 `HEARTBEAT`；调用超过
  `[worker].heartbeat_timeout` 时按 `heartbeat_on_timeout` 写 `RELEASE`（Intent 回 `open`）或
  `FAILED`（终止 run）。心跳由引擎（唯一写入者）代发，Worker 不自行认领/心跳（红线 5）。
- **收敛（I6，Stigmergy）**：每个 dispatch 轮产生新 Fact 后，对新增 facts 再跑一次 Reason，循环至
  Reason 判定 `COMPLETE`，或三个非完成出口写 `STOPPED`（死胡同 `dead-end: no runnable intent`、本轮
  无新 Fact `stalled: dispatch produced no new facts`、`Engine(max_rounds=…)` 安全阀
  `max rounds reached`）——都落终态，run 不再停在 `running`；预算触顶同样 `STOPPED`（M3）。**M2 起**
  `COMPLETE` 需过严格判据（论点全部拆解、子断言回链或 `open`、已有 compare），否则被忽略；完成后落
  run dir `report.md`。
- **异步 Hint（M3）**：`HINT` 是普通事件、非阻塞——dispatch 期间经 `AddHint` 注入的 Hint，
  只要循环继续（本轮产生了新 Fact），必然进入下一轮 Reason 的 Observe（引擎每轮从事件日志折
  Board）；agent 侧 Hint 由引擎在 Reason 收敛时写入（`author=agent`，id 与 human hint 共用事件
  日志计数，见 `blackboard-protocol.md` §2.3/§7）。已落终态的 run（`stopped`/`completed`/`failed`）
  不因 Hint 到达而自动重启（归 M3 完整调度）。
- **Dispatcher**：调度与容器生命周期，是协议的唯一写入者；Worker 不直接认领
  Intent、不发心跳，只接收 prompt 并返回结构化结果。

## 4. 预算与停止条件

`CreateRun` / `[worker].budget` 配置支持三重预算，任一触顶即停止并落盘当前中间态：

| 参数 | 含义 |
|---|---|
| `max_steps` | 最大步数（对应 Run.steps.total） |
| `max_wall` | 最大墙钟时间 |
| `max_cost` | 最大花费（对应 Run.budget.cost） |

`max_wall` 采用无空白的正整数加单位：`ms`、`s`、`m`、`h` 或 `d`，例如 `500ms`、`10m`、`2h`。
`CreateRun` 的预算字段是覆盖值；未给出时回落项目的 `[worker].budget`。预算强制执行仍归 M3。

停止条件（`goal`）由第一性原理定义：日期边界、原始 benchmark、适用范围等。
**注意**：originweave 的 goal 不是"到达某节点即结束"，而是"停止条件 + 偏差判定
完成标准"——抽象论点全部拆解、回链、判定偏差之后才算 COMPLETE。
`goal` 同时派生 `boundary` 边缘事实节点，用于判定"是否越过停止条件"。

其他停止情形：① 证据链连通（`COMPLETE`）② 无可用 Intent（dead-end → `STOPPED`）③ 人工 Gate 挂起
（`awaiting_human`）。

## 5. 事件溯源与 run 目录

一次 run 的全部状态由 **append-only 事件日志**派生，禁止原地修改历史。
事件类型见 [`blackboard-protocol.md`](blackboard-protocol.md) 第 5 节。

```text
<run-dir>/
├── events.jsonl        # append-only，每行一个 Event（board 唯一事实来源；live server 写它）
├── events.db           # 可选：自包含 SQLite 事件日志（迁移/bundled；live server 不用）
├── run.json            # Run 静态/输入元数据（M1c-1；status/计数由 events 派生；可空）
├── input/              # 资料 A 快照（URL 抓取或文本）
├── sources/            # 来源快照（可回链的原文/存档）
├── sessions/           # 会话快照：一次 Worker 调用的原始输入/输出 + 步骤链（M6）
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

## 6. Runtime：container-per-worker

- **每个 Worker 调用一个临时容器**：一次 `Worker.run()`（Bootstrap/Reason/Explore/Validate/
  verify）起一个容器，执行完即销毁。Engine/Dispatcher 仍在 **server 进程**内（编排 + 黑板唯一
  写入者，红线 2/4），容器只承载**实际任务执行**（红线 3）。
- 并发上限 `[worker].max_concurrency` = **同时并发的容器数**（= 并发 Worker 调用数，<=16）；I4 的
  派发并发门限即作用于容器数量。
- **Worker 执行体可插拔（M6）**：`[worker].provider=pi` 时容器内以 Pi agent 运行时执行任务，
  镜像需内置 **Node + `pi` 二进制 + TS 搜索扩展**；每次 Worker 调用一个隔离会话（见 §2 与 §5）。
- 容器生命周期（创建/监控/回收）由 **server 拥有**（`ContainerWorker` 每次调用起/销毁；
  server 的 Dispatcher 决定何时调用），前端与 CLI 不直接管理容器。
- 容器挂载该 run 的 run 目录（读 `input/`、写会话 `cwd` 沙箱产物）；**黑板事件仍由 server 的
  Engine 写**（唯一写入者），容器内 Worker 不写协议。
- 容器镜像与 server 镜像分离：server 常驻，runtime 短命。
- 安全边界：容器内可触网执行检索；server 仅负责编排与持久化。

> **容器池（后续优化，2026-09）**：设置 `[worker].max_concurrency` 时**预热启动** N 个 runtime
> 容器（池），实际调用从池中取容器下发任务、调用后归还复用（而非每次 `docker run`）。M3 先落地
> per-call 起/销毁；池化待评估（启动开销 vs 复用收益）。见 `docs/1.0/TODO.md`。

`originweave ui`（M1c-1 C4）把 **Connect API 与构建产物 `frontend/dist`**（存在时，含 SPA
`index.html` 回退）统一托管在同一端口（默认 **8765**）；带 `--run <dir>` 时进**单 run 只读模式**：
只服务该 run，写 RPC（`CreateRun`/`AddHint`/`SubmitHumanInput`）被拒绝。前端只读视图，不拥有编排
（红线 1）。

> **M1/M1c-1 的临时态**：容器化在 M3 落地。在此之前，引擎以**库层 + 进程内 Worker**
> 运行（M1 单测驱动；M1c-1 由 server 进程内调用以打通 proto/前端）。这是**显式、临时**的
> 例外，红线 3 的正式满足在 M3；`Worker` 接口必须与 M3 的 `ContainerWorker` 一致，
> 使 M3 只需替换 Worker 执行后端而不改编排。

## 7. 架构红线（不可突破）

1. **前端不拥有执行编排**：前端只调用 server API，不启动/调度任务。
2. **server 拥有调度与运行时生命周期**：run 的排队、执行、停止、回收都归 server。
3. **实际任务执行发生在临时容器**：任何执行路径都必须显式建模为 **container-per-worker**
   （每个 Worker 调用一个容器），不允许在 server 进程内直接跑重任务（M1/M1c-1 的进程内
   Worker 为第 6 节所述临时态，正式满足在 M3）。
4. **provider/model/runtime 解耦**：替换检索 / prompt / model provider 不应改动编排代码。
5. **黑板是唯一事实来源**：所有状态变更经事件写回黑板，不得旁路。

## 8. MCP 暴露

`originweave mcp` 将 capability（以及只读的 run 视图）以 MCP 形式暴露，供外部
agent/工具复用。MCP 是**消费能力**的入口，不承担容器调度职责。
