# Dashboard · originweave

本文定义只读运行视图（dashboard）的**信息结构**与**冻结 proto 契约**。
此前的前端 mock 构建（MSW handler）已随 `frontend/` 清理移除；**本文件与 `proto/` 即契约
事实来源**，M1c-1 / M1c-2 起前后端共同遵守。

## 1. 定位

Dashboard 是 run 的**审阅台**：查看溯源 DAG、事实/意图表、事件时间线、偏差记分卡
与 report，并在 HITL Gate 处提供人工介入。发起任务（新建核验）走 server API，
但**执行编排由 server 拥有**，前端不触碰容器生命周期（见 `agent-design.md` 第 7 节）。

`originweave ui`（M1c-1 C4）在同一端口（默认 **8765**）托管 Connect API 与 `frontend/dist`
（存在时，含 SPA `index.html` 回退）；前端 `transport` 默认**同源**（`VITE_API_BASE` 可覆盖，
供 Vite dev 跨源），故无需 CORS。`--run <dir>` 进单 run 只读模式（写 RPC 被拒）；该模式下无
`run.json` 的 run（如样例）归入合成项目 `sample`，run id 取其 `run.json.id` 或目录名。

## 2. 视觉与布局

选定风格：**Swiss / Blueprint（瑞士蓝图）**，布局为三栏控制台。图渲染用 **React Flow**
（`@xyflow/react`）；`docs/design/swiss-blueprint.html` 仅作视觉 tokens / 布局参考
（该稿用 d3，不作为实现）。

设计取向：**工程制图般的秩序感**——浅色网格纸底 + 蓝图蓝强调，把颜色预算留给语义。
`Fact` 渲染为**紧凑矩形卡**：头部 `id`（mono）+ `kind` chip、正文 2–3 行截断预览，
**颜色按 `kind` 编码**（左侧色条 + chip，origin/goal 墨色、fact 蓝、citation 黄、source 绿、
boundary 灰、compare 青、deviation 红）；`Intent` 为**状态色迷你卡**（`open` 虚线灰 /
`claimed` 蓝脉冲 / `done` 青实线 / `dropped` 划除 / `awaiting_human` 警示描边）；
`Hint` 计数归于 INSPECTOR，`origin`/`goal` 为两端锚点。

参考稿：`docs/design/swiss-blueprint.html`（非契约，仅参考）。

```text
┌──────────┬───────────────────────────────────────────────┬──────────────┐
│ brand    │ 顶栏：面包屑 · 状态徽标 · 预算 · Human/Replay/Continue│              │
├──────────┼───────────────────────────────────────────────┼──────────────┤
│ run 列表  │ GRAPH | FACTS | INTENTS | EVENTS               │ INSPECTOR    │
│ (左栏)    │ ───────────────────────────────────────────── │ 选中节点详情  │
│          │ 事实图画布（hero）：origin/goal 锚点 ·           │ 证据逐字引用  │
│          │ Fact 卡 · Intent 问号 · Hint 便利贴 · Gate 面板  │ Intent/Hints │
└──────────┴───────────────────────────────────────────────┴──────────────┘
```

- 顶栏：面包屑（`Researches / <project> / <run>`）+ 状态徽标（`AWAITING_HUMAN · Gate A`）
  + 预算（`steps` / `tok` / `cost` / `intents`）+ 操作
  （Replay 步进 / Human / Continue）。
- 中栏（图为主体）页签：
  - **PROVENANCE DAG** — 图视图（默认页签）。节点按 `kind` 着色
    （origin/goal/fact/citation/source/boundary/compare/deviation/**intent**）；
    Intent 以问号徽标呈现，`open/claimed/dropped` 分别用灰/蓝/划除；
    边按 `relation` 区分（`main-chain` 实线、`dependency` 虚线、
    `decomposes` 点线、`spawns`/`resolves` —— 见 `blackboard-protocol.md`）。
    **节点标签是短预览**（折叠空白、超长截断 + 省略号、CSS 3 行封顶），**完整文本在 INSPECTOR**
    （点击节点后经 `GetFactDetail` 按需加载，长文可滚动）。前端用 **dagre 自上而下分层布局**
    （`@dagrejs/dagre`，origin→claim→citation 逐层、Intent 就近其来源；纯函数、确定性；未带坐标的
    节点两两不重叠，显式坐标原样保留）；历史 proto `Fact.position` 非零时**逐节点优先**、dagre 只补
    缺口（live run 无坐标即全 dagre），符合 "`position` 渲染侧可重算" 的约定。节点可聚焦，
    Enter/Space 与点击同效（选中送 INSPECTOR）。画布提供缩放控件 / MiniMap / **图例**（kind 色点 +
    relation 线型）；选中节点与其入射边高亮、其余边变暗，无选中时 `main-chain` 微高亮。
  - **FACTS** — 事实表：`ID | Kind | Statement | Conf. | Evidence`。
  - **INTENTS** — Intent 表：`ID | Type | Question | Status | From`，含 `dropped`（死胡同）。
  - **RELATIONS** — 实体-关系图（`analysis` 含 relation 时）。复用 PROVENANCE DAG 的图
    组件：`Entity` 按 `type`（person/organization/product/location/event/other）着色，
    边标 `Relation.type`，`inferred=true` 用虚线（无来源推断）。
  - **ENTITIES** — 实体表：`ID | Name | Type | Aliases | Conf. | Mentions`。
  - **EVENTS** — 事件时间线，按 `tone` 着色（黑板协议事件）。
- 右栏 **INSPECTOR**：顶部 **run 统计块**（FACTS / INTENTS / OPEN / HINTS 四格）+
  元信息行（Status / Goal / Created / Steps / Conf. / Budget）；选中节点详情
  （Fact 摘要即时显示，`note` + 逐字引用 `quote + sourceTitle + locator` 经 `GetFactDetail`
  **按需加载**）、Intent 会话、`Hints`（含写 Hint 输入框）。
- **HITL Gate 面板**：`run.status = awaiting_human` 时，INSPECTOR 顶部高亮门控卡片
  （Gate A 论点确认 / Gate B 歧义裁决 / Gate C 最终审阅），提供 批准 / 修正 / 驳回。
- 左侧 run 列表：卡片展示 `status`、`facts`、`deviations`、`confidence`、`steps`；
  `awaiting_human` 时以警示色高亮，**当前打开的 run 以强调色高亮**（`run-card-active`）。

## 3. 路由

| 路由 | 视图 |
|---|---|
| `/` | 总览（项目与 run 汇总） |
| `/projects/new` | 新建项目（提交后走 `CreateProject`） |
| `/projects/:projectId` | 项目详情 + run 列表 |
| `/projects/:projectId/runs/new` | 新建核验（提交后走 `CreateRun`；`?from=<run_id>` 可从失败的 run 预填重试） |
| `/projects/:projectId/runs/:runId` | 审阅台（三栏：run 列表 / 图与页签 / INSPECTOR）。项目页与审阅台左栏的 **run 卡片点击即进入该 run** |
| `/settings` | 设置（主题、Worker provider / 并发上限 / 心跳与超时 / 工具开关；M6） |

## 4. 冻结 proto 契约（Connect）

前后端经 **Connect** 直连（同一份 `.proto`，浏览器无需代理）。契约文件：
[`../../proto/originweave/v1/originweave.proto`](../../proto/originweave/v1/originweave.proto)；
消息字段以 `product-overview.md` 第 4 节与 `blackboard-protocol.md` 为准。

代码生成：
- **TypeScript（前端，M1b）**：`pnpm --dir frontend gen`（`frontend/buf.gen.yaml`，本地 `protoc-gen-es`）→ `frontend/src/gen`
- **Python（server，M1c-1）**：`buf generate proto`（根 `buf.gen.yaml`，`protoc_builtin: python` + `protoc-gen-connect-python`）→ `src/originweave/v1`（import `originweave.v1.*`）

生成物均为构建产物：不入库，且排除 ruff/mypy。

### 4.1 service 方法

| RPC | 请求 | 响应 | 说明 |
|---|---|---|---|
| `ListProjects` | `ListProjectsRequest` | `ListProjectsResponse{projects}` | 列出全部项目 |
| `GetProject` | `GetProjectRequest{project_id}` | `GetProjectResponse{project}` | 单个项目；不存在 → `NOT_FOUND` |
| `CreateProject` | `CreateProjectRequest{id, name, description?, accent?}` | `CreateProjectResponse{project}` | 建目录式项目（`projects/<id>/project.json`）；id 已存在 → `ALREADY_EXISTS`，非法/保留 id（`new`）、空 name → `INVALID_ARGUMENT`，pinned 只读 → `FAILED_PRECONDITION` |
| `ListProjectRuns` | `ListProjectRunsRequest{project_id}` | `ListProjectRunsResponse{runs}` | 某项目下 run 列表 |
| `ListRuns` | `ListRunsRequest{project_id?}` | `ListRunsResponse{runs}` | 全部 run（可按项目过滤） |
| `GetRun` | `GetRunRequest{run_id, at_event?}` | `GetRunResponse{run_detail}` | run **全量详情**（重试预填 / 兼容）；不存在 → `NOT_FOUND` |
| `GetRunGraph` | `GetRunGraphRequest{run_id, at_event?}` | `GetRunGraphResponse{graph}` | **轻量图投影**（控制台轮询用，见 §4.2a）；不存在 → `NOT_FOUND`，`at_event` 越界 → `INVALID_ARGUMENT` |
| `GetFactDetail` | `GetFactDetailRequest{run_id, fact_id, at_event?}` | `GetFactDetailResponse{fact}` | 单个 Fact 全量（`note` + 逐字 `evidence`），点节点时按需取；fact 不存在 → `NOT_FOUND`，空 `fact_id` / `at_event` 越界 → `INVALID_ARGUMENT` |
| `ListEvents` | `ListEventsRequest{run_id, at_event?}` | `ListEventsResponse{events}` | 事件时间线（EVENTS 页签激活时取；`at_event` 给出时返回前缀切片，越界 → `INVALID_ARGUMENT`） |
| `ListSessions` | `ListSessionsRequest{run_id, intent_id?}` | `ListSessionsResponse{sessions}` | Worker 会话快照（INSPECTOR 按需取；`intent_id` 过滤该 Intent 的会话） |
| `CreateRun` | `CreateRunRequest` | `CreateRunResponse{run}` | 新建 run（**起一次核验的唯一入口**） |
| `AddHint` | `AddHintRequest{run_id, text}` | `AddHintResponse{hint}` | 写一条 Hint（`author=human`，非阻塞） |
| `SubmitHumanInput` | `SubmitHumanInputRequest` | `SubmitHumanInputResponse{run}` | 提交 Gate 决策，解除 `awaiting_human` |
| `GetSettings` | `GetSettingsRequest{}` | `GetSettingsResponse{settings}` | 读项目设置（`[worker]` + `[capability.model]`；**M6 P3**） |
| `UpdateSettings` | `UpdateSettingsRequest{settings}` | `UpdateSettingsResponse{settings}` | 校验后写回项目 `originweave.toml` 并应用（未知 provider/tool 报错；**M6 P3**） |
| `Search` | `SearchRequest{query, num_results?}` | `SearchResponse{text}` | 经 `[capability.search]` 执行检索；供 Pi 的 TS 搜索扩展回调（**M6 P3，消费于 P4**） |

错误沿用 Connect 的统一错误模型（`code` + `message`）。

### 4.2 RunDetail

字段见 proto `RunDetail`：
`run` · `origin` · `goal` · `facts[]` · `intents[]` · `hints[]` · `edges[]` ·
`entity_graph?`（`analysis` 含 relation 时） · `deviations[]` · `events[]` ·
`waiting_for?`（仅 `status = awaiting_human`） · `report?`（未产出时为空） ·
`decisions[]`（`HUMAN_INPUT` 裁决记录） · `sessions[]`（M6：一次 Worker 调用的会话，含原始
输入/输出与步骤链，由 run dir `sessions/*.json` 读取） · `source_text`（资料 A 正文，读自
`input/document.md`；用于「重试」预填，缺失时为空串）。

**Replay（`at_event`）**：`GetRun` 带 `at_event=k`（1..N）时，服务端用 `reduce(events[:k])`
折算 board —— `run`/`origin`/`goal`/`facts`/`intents`/`hints`/`edges`/`deviations`/`report`/
`waiting_for`/`decisions` 均为**第 k 步当时态**；`events[]` 仍返回**全量**（时间轴长度稳定）。
`k` 越界 → `INVALID_ARGUMENT`。不传 `at_event` 即全量 board。

### 4.2a RunGraph（轻量投影）

控制台**轮询** `GetRunGraph` 而非 `GetRun`，把重负载移出热路径（逐字引用 / 会话原始 IO /
事件 payload 只在需要时经 `GetFactDetail` / `ListSessions` / `ListEvents` 取）：

```text
RunGraph {
  run,                                  # 复用 Run（状态 / 计数 / 预算）
  origin, goal, facts[],                # FactSummary：id/label/subtitle/kind/role/
                                        #   status/confidence/position/evidence_count
                                        #   —— 无 note 与 evidence[]（引文留在 GetFactDetail）
  intents[],                            # 复用 Intent（本身轻量）
  edges[], hints[], waiting_for?,       # 复用；Gate 卡随轮询刷新
  event_count,                          # 全量事件数：Replay 游标上界（不随 at_event 折算）
}
```

`at_event` 语义与 `GetRun` 相同（`reduce(events[:k])`），但 `event_count` 恒为全量长度，
步进时游标稳定。四个读 RPC 均支持 pinned 单 run 只读模式。

### 4.3 CreateRunRequest

```text
project_id, title?, source_type(url|text), analysis?(provenance|relation|both),
goal, max_steps?, max_wall?, max_cost?, auto?, source_text?
```
预算三项为**覆盖**，未给出时回落 `[worker].budget` 配置；`auto=true` 跳过 HITL Gate（默认
未给定时回落 `[hitl].auto`）。
`source_text` 提供资料 A 正文，用于 `source_type="text"`（**目前仅支持 text；url 暂不支持**）。
`analysis` 目前仅 `provenance`（`relation`/`both` 归 M5）。
`CreateRun` 把资料 A 落盘为 `input/document.md`（+ `input/source.json`），并起一个后台 asyncio
任务跑 `Engine.run`；返回前**等到 `PROJECT` 事件落盘**，故返回的 `Run` 由事件派生、状态为
`running`（计数由此后的 `GetRun` 反映），任何紧随其后的 `GetRun` 都能立即读到该 run。
`project_id` 必须已存在（缺失 → `NOT_FOUND`）。

### 4.4 HITL 方法

- `AddHint`（主动注入，非阻塞）：`{ run_id, text }`，`author` 固定为 `human`。
- `SubmitHumanInput`（被动，解除 `awaiting_human`）：
  `{ run_id, gate: confirm-claim|arbitrate|review, decision: approve|edit|reject, text?, targets? }`。

两者均落为 `HINT` / `HUMAN_INPUT` 事件，因此可审计、可重放。

### 4.5 领域类型

`Project` / `Run` / `Fact` / `Intent` / `Hint` / `Edge` / `Evidence` /
`Deviation` / `Event` / `Report` / `Entity` / `Relation` / `EntityGraph` 的定义一律以
`product-overview.md` 第 4 节与
`blackboard-protocol.md` 为准，此处不重复。

### 4.6 设置与会话（M6）

```text
Settings {
  worker: WorkerSettings {
    llm: LlmSettings { provider, model, baseUrl }   # 来自 [capability.model]；baseUrl 空 = OPENAI_BASE_URL
    provider,                         # local | pi
    execution, image, containerScope, # runtime 设置；per-run 仅 Pi + container
    maxConcurrency,                   # 本项目每次 run 的 worker 上限（>0 且 <=16）
    tools: string[],                  # 启用的工具名单（扁平白名单，与 [worker].tools 一致）
    heartbeatInterval,                # 单次调用的 HEARTBEAT 间隔，如 "15s"（I4）
    heartbeatTimeout,                 # 调用失活阈值，如 "5m"；须 > interval（I4）
    heartbeatOnTimeout,               # release | fail（I4）
    budget: WorkerBudget { maxSteps, maxWall, maxCost }
  }
}

Session {                             # 一次 Worker 调用的历史（隔离）
  id, runId, worker, task,            # task: Bootstrap | Reason | Explore | Validate
  intentId?, model,                   # worker = worker 实例 id（如 "worker-1"）
  input,                              # 原始输入（渲染后的 prompt / board，Struct）
  output,                             # 原始输出（Worker 最终回复文本）
  steps: SessionStep[] { seq, kind, name, text, ok? },
  startedAt, endedAt
}
```
`GetSettings`/`UpdateSettings` 读写项目 `originweave.toml`：`UpdateSettings` 的 `worker` 块为**权威值**
（逐字段写回 `[worker]`，`llm` 写回 `[capability.model]`），校验失败 → `INVALID_ARGUMENT`；
调用后 server 重建 worker/search/prompt provider，**仅对后续新建 run 生效**；每个 run 的 `run.json`
冻结非敏感 runtime 设置，保证人工 Gate 恢复仍使用原有容器与镜像。
会话快照落 run dir `sessions/<id>.json`；`RunDetail.sessions` 直接读该快照（原始输入/输出与完整步骤链，
样例目录无 `sessions/` 则为空），与 `SESSION`/`WORKER_STEP` 事件互为索引，前端 INSPECTOR 依会话展示。
`Search` 为只读 RPC（`[capability.search]` 单一来源，切换 provider 不需改 Pi 扩展）。

## 5. 契约原型与样例

此前的 mock 数据曾提供样例：项目 `obscura-kitesurf` / `citation-watch`，run
`run_009`（running）、`run_008`（completed）、`run_007`（paused）；以及一条完整
DAG（`desc → f1 核心结论 → c1 引用 → s1 原始来源 → p1 比对 → d1/d2 偏差`）。
该产物已随 `frontend/` 清理移除，样例仅作契约与命名参考。

约定：M1c-1 落地 server/proto 后，**同一批方法与字段**应由真实服务提供；契约若变更，
先改本文件与 `proto/`，再同步前后端。
