# originweave 1.0 · SPEC

活跃版本：**1.0**。本文件的 checkbox 是进度的**唯一载体**，由 `checkpoint` 阶段更新。
每个 milestone 对应一个 `##` 小节，顺序即执行顺序。

参考文档：

- 产品与领域模型 → [`../overview/product-overview.md`](../overview/product-overview.md)
- 黑板协议与 HITL → [`../overview/blackboard-protocol.md`](../overview/blackboard-protocol.md)
- 执行架构与架构红线 → [`../overview/agent-design.md`](../overview/agent-design.md)
- UI 与 proto 契约 → [`../overview/dashboard.md`](../overview/dashboard.md)、[`../../proto/`](../../proto/)

> 规则：勾选前必须能指向仓库中的真实文件；仓库状态优先于文档假设。

---

## M0a · 脚手架

目标：仓库结构、依赖管理、构建/检查入口、CI 与 CLI 骨架就绪；业务逻辑留空。

- [x] 包结构（src layout）与包元数据 — `pyproject.toml`（hatchling，`requires-python>=3.11`，console script `originweave`）
- [x] 依赖与锁文件 — `pyproject.toml` dev 组（mypy/pytest/ruff）+ `uv.lock`
- [x] 开发入口 Makefile — `Makefile`（install/run/demo/test/lint/fmt/ui/replay/cloc/clean）
- [x] 代码行数统计脚本 — `scripts/cloc.py` + `make cloc`
- [x] CI — `.github/workflows/ci.yml`（ruff check + mypy + pytest）
- [x] README — `README.md`（快速开始、Makefile、结构）
- [x] CLI 骨架 — `src/originweave/cli.py`（`init/replay/capabilities/mcp/ui` 声明并 dispatch；起 run 走 server/proto，`trace` 已在契约重排中移除）
- [x] smoke 测试 — `tests/test_smoke.py`（版本可用、parser 可构建、无命令打印帮助、子命令为 stub）

验收：`make lint` / `make test` 通过；`originweave --help` 列出全部子命令。

---

## M0b · 配置与 capability 层骨架

目标：可配置，外部能力以可替换 provider 接入。

- [x] `init` 生成默认配置（`originweave init`），含 `auto`（HITL 默认人工介入）开关；落盘位置与格式在实现时确定并回写 `agent-design.md`
- [x] 配置加载与校验
- [x] capability 抽象接口：`search` 与 `prompt` 两个 capability 的最小 Protocol
- [x] search provider 注册表：`exa` / `parallel`（可 import，未配置时给出清晰报错）
- [x] prompt provider 注册表：`local` / `langfuse`
- [x] 单测：配置加载、provider 选择

> **Phase R 撤销**：原条目「`LIVE` 开关」「`LIVE=0` 默认离线」「本地 cache / mock 后端」
> 「capability 调用可录制」已移除——能力改为**真实调用**（见 `agent-design.md` §2）。
> 对应代码（`[live]`、`capabilities/cache.py`、`record.py`、样例 `capabilities/**`）已于 Phase R 代码迭代清理。

验收：配置加载与 provider 解析可用（引擎循环属 M1，仍为 stub）。

---

## M0c · 黑板事件日志与事件溯源

目标：一次 run 的全部状态由 append-only 黑板事件派生，且可只读重放。

- [x] run 目录布局落地（`events.jsonl`、`input/`、`sources/`、`report.md`；其中 `report.md` 于 M2 生成；
      `sessions/` 由 **M6** 增补，权威布局见 `agent-design.md` §5）
- [x] 黑板协议事件 writer：`PROJECT/INTENT/EXECUTE/CONCLUDE/REASON/COMPLETE/HEARTBEAT/RELEASE/HINT/REQUEST_HUMAN/HUMAN_INPUT`（`Event{id,at,type,message,tone,payload}`）
- [x] 由事件重建黑板状态（`Board{origin,goal,facts,intents,hints}` + `edges/status/decisions/waitingFor/verdict`）的 reducer
- [x] `originweave replay <run-dir>` 只读、不触网、复现含人工输入在内的结论（替换当前 stub）
- [x] 保留策略：`runs/` 与 `*.jsonl` 不入库（`.gitignore` 已就绪，需确认新布局覆盖）
- [x] 单测：写入 → 重放一致性（byte-level 或结构级）

> **M1 扩展**：事件集在 M1 增补 `FAILED` / `STOPPED`（终止态，见 §5）；
> `ENTITY` / `RELATION` 归 M5。本节的 11 种为 M0c 交付范围。

验收：同一 run dir 连续两次 `replay` 结果一致；replay 过程无网络访问。

---

## M0d · 构建 copilot_productivity 样例

目标：从零构建一份真实、可重放的溯源 fixtures（无既有 spike 可迁），供 `replay`
与后续 `make demo` 使用。

- [x] 资料 A：`examples/copilot_productivity/input/`（真实公开页冻结快照 + `source.json`）
- [x] 来源快照：`examples/copilot_productivity/sources/`（GitHub 实验室 / Accenture 企业研究 + `manifest.json`）
- [x] run 事件日志 `events.jsonl`，由 `scripts/build_sample_fixtures.py` 生成且产物入库
- [x] `originweave replay examples/copilot_productivity` 只读复现 Board（不触网）
- [x] `.gitignore` 放行 `examples/**/*.jsonl`
- [x] 单测：replay 确定性/结构、证据逐字可回链、fixture 可重生成
- [x] 文档：样例说明与预期偏差（`examples/copilot_productivity/README.md`）

> **Phase R 撤销**：原条目「录制的 capability 响应（检索 + prompt）→ `capabilities/**`」
> 已移除；样例仅保留 `input/` + `sources/` + `events.jsonl`。

验收：全新环境 `originweave replay examples/copilot_productivity` 复现同一 Board、不触网。

---

## M1 · 黑板与 Agent 循环

目标：实现黑板块与 OODA 工作循环，从 A 抽取抽象论点并拆解、回链来源；支持多 Worker
asyncio 任务并发与 HITL Gate A。引擎为**库层**（进程内 Dispatcher），**不经 CLI 暴露**；
API 与交互由 M1c-1 / M1c-2 落地；真实接入 `model`（OpenAI 兼容）与 `search`（exa/parallel）。

- [x] 黑板模型：`Board{origin,goal,facts,intents,hints}` 与 `Fact`（kind/role/status/confidence/evidence）、`Intent`、`Hint` — `src/originweave/blackboard.py`（M0c）
- [x] `origin`/`goal` 特殊 Fact（`kind` 区分、`role=none`）；`Fact.role = main-claim | sub-claim` — `blackboard.py`（M0c）
- [x] DAG 组装与边 relation：`main-chain/dependency/goal-derived/decomposes/spawns/resolves` — `src/originweave/reduce.py`（M0c）
- [x] `model` capability：`ModelProvider` Protocol + **真实 OpenAI 兼容 provider**（`capabilities/model.py`、`[capability.model]`；`OPENAI_API_KEY` + `OPENAI_BASE_URL`（端点经环境变量提供））（Phase R）
- [x] `search` capability 真实接入：`exa` / `parallel`（`capabilities/search.py`；免费 MCP 端点，`EXA_API_KEY` / `PARALLEL_API_KEY` 可选）（Phase R）
- [x] 任务指令：`Bootstrap`（抽取核心抽象论点）— `engine.py` + `prompts/bootstrap.txt`
- [x] 任务指令：`Reason`（产出候选 Intent）— `engine.py` + `prompts/reason.txt`
- [x] 任务指令：`Explore`（认领 Intent 并执行探索）— `engine.py` + `prompts/explore.txt`
- [x] 任务指令：`Validate`（独立判重 pass）— `engine.py` + `prompts/validate.txt`
- [x] Intent 三型调度分支：`decompose` / `explore` / `verify`（decompose/explore 随 I3，`verify` 随 M2 `compare` 落地）
- [x] 抽象论点抽取：`Bootstrap` → `main-claim` — `engine.py` + `prompts/bootstrap.txt`
- [x] 抽象论点拆解：`Intent(decompose)` → `sub-claim` — `engine.py`（`_run_explore` 派发分支）+ `prompts/explore.txt`
- [x] 来源回链：`citation` / `source` 节点与 `Evidence{quote,sourceTitle,url,locator}` 登记 — `engine.py`（explore 分支调 `search`，结果经 `extra` 注入 worker）+ `prompts/explore.txt`
- [x] 多 Worker asyncio 任务并发认领 Intent + 心跳/超时释放（`HEARTBEAT`/`RELEASE`）；Dispatcher 按 Intent id 序确定性提交，保证 Board 确定 — `engine.py` `_dispatch`/`_run_explore`/`_heartbeat`、`config.py` `[worker].heartbeat_*`/`max_concurrency<=16`（I4）
- [x] Stigmergy：新 Fact 触发新一轮 Reason（去重）— `engine.py` `_continue`（多轮循环；死胡同/`max_rounds` 停止；`REASON.triggerFacts` 只记新增 facts）（I6）
- [x] Reason 产出 Intent 的去重：`Validate` pass（复用 `model`，纯 LLM 语义判重、无 L1 预筛，比对含 `done`/`dropped` 及批内候选）→ 重复项写 `status=dropped` 留痕（`Intent.duplicateOf`）— `engine.py` + `prompts/validate.txt`
- [x] Worker 执行后端可切换（`[worker].execution = in-process | container`）；Engine/Dispatcher 始终在
      server 侧编排，保持协议唯一写入者 — `server/context.py`（`worker_for`/`ContainerManager`）、
      `runtime/container.py`（M3a）
- [x] HITL 机制与 **Gate A（论点确认）**：`REQUEST_HUMAN`/`HUMAN_INPUT`，run → `awaiting_human`（程序化挂起/恢复；交互归 M1c-2）— `engine.py` `run`（Bootstrap 后写 `REQUEST_HUMAN{gate:"confirm-claim"}`）/`resume`（`approve|edit|reject`；reject→`STOPPED`）
- [x] 自动路径：`[hitl].auto=true`（或 M1c-1 的 `CreateRunRequest.auto`）跳过 Gate — `Engine(auto=...)` + `run(auto=...)`
- [x] 失败/停止事件：`FAILED` / `STOPPED` → `status=failed|stopped`（`events.py`/`reduce.py`；`paused` 随 M3）
- [x] 单测：注入 **fake provider**，对 fixture 输入产出确定性 Board/DAG（节点/边/证据断言）— `tests/test_engine_m2.py::test_scored_run_is_deterministic`

验收：对 `copilot_productivity` 样例，核心抽象论点被拆解为子断言，每条子断言可回溯到
至少一条带 `quote+url` 的证据或标记为 `open`；≥2 Worker 并发时无 Intent 重复执行；
Gate A 可挂起并可恢复。**`replay`（事件日志）字节确定；live run（真实 provider）不保证
确定，其结构断言由注入 fake provider 的测试覆盖。**

---

## M1b · 前端脚手架

目标：初始化 `frontend/`（React + Vite + TS + Connect），交付**无数据、无 mock**的界面壳
（三栏布局 / 路由 / 页签空态 / React Flow 空画布）。仅依赖已就绪的 `proto/`，
**可与 M1 并行、可先做**；真实数据接线归 M1c-2b。

- [x] proto 契约 `proto/originweave/v1/*.proto`（Phase 0 落地；消息取自 `product-overview.md` 第 4 节）
- [x] `proto/buf.yaml` + `buf.gen.yaml` 骨架（Phase 0 落地）
- [x] 前端工程入库：`frontend/`（pnpm + Vite + React + TS strict + lockfile + `.nvmrc`/engines）
- [x] 主题 tokens：移植 Swiss/Blueprint（浅/深色，`swiss-blueprint.html`）
- [x] 三栏布局 + 路由（`/`、`/projects/:projectId`、`/projects/:projectId/runs/new`、`/projects/:projectId/runs/:runId`、`/settings`）
- [x] 页签骨架 GRAPH / FACTS / INTENTS / EVENTS（空态；RELATIONS/ENTITIES 归 M5）
- [x] React Flow 空画布壳（`@xyflow/react`）
- [x] Connect TS 生成接入（`frontend/buf.gen.yaml` + `@bufbuild/protoc-gen-es`），typed client 封装（暂无调用）
- [x] ESLint + Prettier + Vitest（含壳渲染冒烟）；`tsc --noEmit` 门禁
- [x] `Makefile` 前端 targets + CI 前端 job（含 `buf lint proto`）

验收：`pnpm --dir frontend install && pnpm --dir frontend gen` 后，`typecheck` / `lint` / `test` /
`build` 全绿；页面为**空壳**、**无 mock 数据**；`buf lint proto` 通过。

---

## M1c-1 · server 骨架

目标：把 proto 契约落地为 **Connect Python server**（Starlette + uvicorn + `connect-python`），
接线 M1 引擎（`agent-design.md` §6 的进程内临时态；容器化归 M3）；`originweave ui` 起服务与静态视图。
按 **C1–C4** 分片推进，每次迭代一片。

### C1 · Python codegen + Connect app 骨架

- [x] 依赖/工具链：`protobuf` / `connect-python`（含 `protoc-gen-connect-python`）/ `starlette` / `uvicorn`；
      `make proto` 跑通 `buf generate proto` → `src/originweave/v1`（import `originweave.v1.*`；生成物不入库，ruff/mypy 已 exclude）
- [x] CI `python` job 先生成 proto（buf-setup + 插件 PATH）再 lint/typecheck/test
- [x] `server/app.py`：构造 `OriginweaveService` 的 Connect ASGI app（初始 8 RPC；现 12 RPC，均已实现，见 `dashboard.md §4.1`）— `server/app.py`/`server/service.py`
- [x] 测试：ASGI 客户端 smoke（`ListProjects` 空列表等）— `tests/test_server.py`

### C2 · 持久化（run.json + projects 注册表）

- [x] `Run` / `Project` 领域模型；`runs/<run_id>/run.json` + 目录式 `projects/<project_id>/project.json`
      （新配置 `[project].dir`，默认 `projects`）；`events.jsonl` 仍为 board 唯一事实来源 —
      `persistence.py`、`store.py`（run.json IO）、`config.py`（`[project]`）
- [x] `run_00N` 分配；`summarize_run(...) -> Run`（使无 `run.json` 的样例目录可被只读服务；
      样例缺 `project_id`/`title`/`source_type`/`analysis`，按目录名/默认值回填）— `persistence.py`
- [x] 测试：run.json 往返、id 分配、由事件派生 Run — `tests/test_persistence.py`

### C3 · service 接线（引擎 + 只读 + HITL）

按 **C3a / C3b** 分片。

#### C3a · DI + 只读 RPC + proto 映射

- [x] DI：`create_app(config/providers/root)` + `ServerContext`/`Providers`（测试注入 fake）；
      `server/convert.py` 领域/事件 → proto 映射 — `server/context.py`、`server/convert.py`
- [x] 只读 RPC `ListProjects`/`GetProject`/`ListProjectRuns`/`ListRuns`/`GetRun`
      （`RunStore` → `reduce()` → `RunDetail`；缺失 → `NOT_FOUND`）— `server/service.py`
- [x] 测试：ASGI 客户端注入（只读路径，`root=tmp` 隔离）— `tests/test_server.py`

#### C3b · CreateRun + 后台调度 + AddHint/SubmitHumanInput

- [x] `CreateRun{source_text}`：校验 project 存在（缺失 → `NOT_FOUND`）与输入（仅 `text`、非空
      `source_text`/`goal`、`analysis=provenance`），分配 id、写资料 A 到 `input/`（`document.md`）+
      落 `run.json`（**静态元数据**）、后台 asyncio 任务跑 `Engine.run`；返回前等 `PROJECT` 落盘，
      返回的 `Run` 由事件派生、状态 `running`（`server/service.py`；每 run 单例 `RunStore` 由
      `server/context.py` 的 `RunScheduler` 持有）
- [x] `AddHint` → `HINT` 事件；`SubmitHumanInput` → 重建 `Engine` 调 `resume`（I5 已支持 fresh-engine 续号；
      非 `awaiting_human` → `FAILED_PRECONDITION`，gate 不符/未知 decision → `INVALID_ARGUMENT`）
- [x] 测试：ASGI 客户端注入 fake provider，`CreateRun → GetRun`（events/facts/intents）、
      `AddHint`/`SubmitHumanInput` 落事件（含并发 id 唯一性、非阻塞后台化、错误码负例）

### C4 · `originweave ui` + 静态 + 端到端

- [x] `ui`（替换 stub）：uvicorn 起 app（`cli._cmd_ui`）、托管 `frontend/dist`（存在时，SPA
      `index.html` 回退；`server/app.py` `SPAStaticFiles`）；`--run <dir>` 单 run 只读
      （`ServerContext.pinned_run` + `service.py` 写 RPC 拒绝）；端口统一 `8765`
- [x] `Makefile` / `README` / CI 同步；`ui` 冒烟测试（`tests/test_server.py`：静态/SPA、pinned、
      lifespan 收尾、CLI）；前端 `transport` 默认端口改指 `8765`（`frontend/src/api/transport.ts`）

验收：注入 fake provider 起 server → `CreateRun{source_text}` 产出 run → `GetRun` 返回 `RunDetail`
（含 events/facts/intents）→ `AddHint`/`SubmitHumanInput` 落为事件。

---

## M1c-2a · 前端展示层（fixture 驱动，可先做）

目标：把 proto 契约类型渲染为 **props 驱动**的展示组件，**不依赖 server**；真实数据接线归
M1c-2b。仅依赖已就绪的 `proto/`，**可与 M1c-1 C2–C4 并行**。

- [x] 前置 `pnpm --dir frontend gen`（生成物不入库）— `frontend/buf.gen.yaml`
- [x] 图映射纯函数：`RunDetail` → React Flow nodes/edges；Fact 按 `kind` 形状+颜色双编码、
      Intent 问号徽标按 `status`、边按 `relation` 线型（视觉契约见 `dashboard.md` §2）；
      布局用 proto `Fact.position` — `frontend/src/graph/mapping.ts`
- [x] `GraphCanvas` props 化（nodes/edges/选中回调）+ 自定义节点渲染；无数据保留空画布 —
      `frontend/src/graph/GraphCanvas.tsx`、`frontend/src/graph/nodes.tsx`
- [x] 页签展示组件：FACTS / INTENTS / EVENTS（props 驱动，无数据时保留现有空态）—
      `frontend/src/tabs/{Facts,Intents,Events}Tab.tsx`
- [x] INSPECTOR 展示：节点详情 + 证据逐字引用（`quote + sourceTitle + locator`）+ Intent 计数 —
      `frontend/src/layout/Inspector.tsx`
- [x] RunList 卡片：状态徽标、计数、`awaiting_human` 警示高亮 — `frontend/src/layout/RunList.tsx`
- [x] HITL Gate 卡片展示（gate/question）；决策按钮回调以 props 注入（提交归 M1c-2b）—
      `frontend/src/layout/Inspector.tsx`
- [x] 组件/映射测试：proto 消息 fixture 驱动（Vitest）— `frontend/src/graph/mapping.test.ts`、
      `frontend/src/{graph/GraphCanvas,tabs/tabs,layout/layout}.test.tsx`、`frontend/src/test/fixtures.ts`

约束：不碰 `api/`、不加数据依赖、路由仍空态；fixture 只进测试文件（不接 mock 红线）。
验收：`make frontend-gen` 后 `typecheck`/`lint`/`test`/`build` 全绿；组件零 RPC 调用。

---

## M1c-2b · 前端接线与 UI（依赖 M1c-1 C3/C4 + M1c-2a）

目标：前端改为读取真实数据（**不接 mock**），在 HITL Gate 处提供人工介入。
按 **2b-1–2b-5** 分片推进，每次迭代一片。

> 已完成：`transport` 默认端口改指 `8765`（随 M1c-1 C4 — `frontend/src/api/transport.ts`）。

### 2b-1 · 数据层 + 只读接线

- [x] 依赖 `@tanstack/react-query`；`QueryClientProvider`（`main.tsx`）；hooks
      `useProjects`/`useProjectRuns`/`useRun`；**活动态轮询**（`queued`/`running`/`awaiting_human`，
      终态停轮询）— `frontend/src/api/`（`hooks.ts`/`queryClient.ts`；`activePollInterval` 纯函数可测）
- [x] 真实数据接入只读视图：`Overview`（项目列表）、`Project`（run 列表）、`AppShell`
      （项目导航 + 连接指示）、`Console`（`RunList` + 页签 GRAPH/FACTS/INTENTS/EVENTS + `Inspector` 计数）；
      loading/error/`NOT_FOUND` 与空态保留 — `frontend/src/{routes,layout,tabs}/`
- [x] 测试：Vitest（mock `@/api/client`，测试专属；生产不接 mock）— `frontend/src/App.test.tsx`、
      `frontend/src/routes/routes.test.tsx`、`frontend/src/api/hooks.test.ts`、`frontend/src/test/providers.tsx`

### 2b-2 · INSPECTOR 交互（选中联动 + Hints）

- [x] 选中状态与图联动：`GraphCanvas` `onSelect` / 页签（FACTS/INTENTS 行）选择 → `Inspector`
      详情；含 `origin`/`goal` 锚点；选中态带 runId（跨 run 自动失效）、行键盘可达（Enter/Space）
      且高亮 — `frontend/src/routes/Console.tsx`（`resolveSelection`）、`frontend/src/layout/Inspector.tsx`、
      `frontend/src/tabs/{Facts,Intents}Tab.tsx`
- [x] Hints 输入（`AddHint` mutation + invalidate refetch，非阻塞；IME 组合态守卫、失败保留文本、
      pending 防重入、内联错误；无 hints 且无 handler 时不渲染）— `frontend/src/layout/Inspector.tsx`、
      `frontend/src/api/hooks.ts`（`useAddHint`）

### 2b-3 · HITL UI 与 Replay

- [x] `awaiting_human` → Gate A（`confirm-claim`）/ Gate B（`arbitrate`）面板（approve/edit/reject）→
      `submitHumanInput`；含修正说明输入、pending 禁用、失败行内报错；Gate C（`review`）随 M3 —
      `frontend/src/layout/Inspector.tsx`（`GateCard`）、`frontend/src/api/hooks.ts`（`useSubmitHumanInput`）、
      `frontend/src/routes/Console.tsx`
- [x] Replay 步进：**服务端折算**（`reduce(events[:k])`，复用唯一 reducer、零漂移），前端只做步进/
      高亮与折算 board 的展示（步进随 run 隔离；replay 期间禁用写操作）。初版走 `GetRun(at_event=k)`；
      图数据拆分后 console 折算走 **`GetRunGraph(at_event=k)`**（`event_count` 为全量游标上界），
      事件时间线走 `ListEvents(at_event=k)` — `proto/`（`GetRunGraphRequest.at_event` 等）、
      `service.py`（`_run_detail`/`_folded_events`/`get_run_graph`/`list_events`）、
      `persistence.py`（`summarize_run(events=…)`）、`frontend/src/api/hooks.ts`
      （`useRunGraph(runId, atEvent)`/`useRunEvents`）、`frontend/src/routes/Console.tsx`、
      `frontend/src/tabs/EventsTab.tsx`、`frontend/src/tabs/GraphTab.tsx`

### 2b-4 · 新建核验表单 + 顶栏

- [x] 新建核验表单（`CreateRun`：`source_text`/`title`/`goal`/`auto`，含可选预算覆盖）→ 导航到
      Console；失败行内报错 — `frontend/src/routes/NewRun.tsx`、`frontend/src/api/hooks.ts`（`useCreateRun`）
- [x] 顶栏：run 状态/预算徽标（`status` + `steps`/`tok`/`cost`/`intents`，置于 Console 中栏 header）
      与连通性（LIVE/OFFLINE，`AppShell`，2b-1 已落地）指示 — `frontend/src/routes/Console.tsx`、
      `frontend/src/layout/AppShell.tsx`、`frontend/src/styles/presentation.css`

### 2b-5 · 端到端与冒烟

- [x] 端到端：起 server → 建 run → 前端看到 DAG → Gate 处人工介入（测试以 fake provider 驱动）+ 冒烟 —
      `tests/test_server.py`（`test_end_to_end_create_run_to_scorecard`：CreateRun→Gate A→verify→COMPLETE+`report.md`）、
      `scripts/smoke.py`（`make smoke`，进程内 fake worker）、`frontend/src/routes/routes.test.tsx`（NewRun→DAG→Gate 串联）
- [x] CI / 文档同步（`Makefile` / `README.md`）— `.github/workflows/ci.yml`（`python` job 加 `make smoke`）、
      `Makefile`（`smoke` target）、`README.md`
- [x] 浏览器端到端（`@playwright/test`）：驱动**真实 `frontend/dist`** + fake-provider server
      （`scripts/e2e_server.py` / `run_e2e_server.sh`，复用 `scripts/smoke.py` 的脚本化 worker）——
      新建表单 → DAG → Gate A `approve` → Replay 步进 — `frontend/playwright.config.ts`、
      `frontend/e2e/flow.spec.ts`；CI `frontend` job 增 Python/uv/`make proto`/Playwright + `pnpm e2e`

约束：前端只调 RPC、不编排；RELATIONS/ENTITIES 页签归 M5；不改 `proto/`；fixture 只进测试文件。
验收：从前端发起一次核验（样例），看到由抽象论点拆解出的 DAG，可在 Gate 处人工介入；
架构红线未被突破（前端不编排、server 拥有调度）。

---

## M2 · 偏差记分卡

目标：`Intent(verify)` / `compare(facts × sources × goal)` 输出偏差分类与 report。

- [x] `compare` 引擎节点（`compare` kind）汇总 facts × sources × goal — `engine.py` `_check_verified_facts` + `prompts/compare.txt`
- [x] deviation 分类（篡改 / 改写 / 省略 / 归因错误 / 时间错置等）与 `deviation` 节点 — verify pass 产出，`engine.py` `_check_verified_facts`
- [x] 每项 deviation 带 `severity(high|medium|low)` 与 `confidence` — `Fact.subtitle`（`severity=… · confidence=…`）+ `report.parse_severity`
- [x] goal 重定义生效：抽象论点全部拆解 + 回链 + 偏差判定完成才 `COMPLETE` — `engine.py` `_goal_satisfied`
- [x] 整体 `verdict` 与 `Report{summary,findings,sources}` 生成（run dir `report.md`）— `report.py` `derive_report`/`render_report` + `store.write_report`
- [x] **Gate B（歧义裁决）**：置信度低/来源冲突时发起 `REQUEST_HUMAN` — verify reply `gate` → `REQUEST_HUMAN{arbitrate}`；`resume` 支持 `arbitrate`
- [x] 单测：对样例给出预期偏差集合与阈值行为 — `tests/test_engine_m2.py`、`tests/test_report.py`、`tests/test_server.py`

验收：run dir 产出 `report.md`（含 verdict、逐条 deviation 与来源清单），并经 server
`RunDetail.report` 暴露；Gate B 可对冲突来源人工裁决并继续。

---

## M3 · agent runtime 与 capabilities

目标：真实执行走 **container-per-worker**（每个 Worker 调用一个临时容器；Engine/Dispatcher
仍在 server 进程内编排并写黑板）；能力经 MCP 暴露；支持异步 Hint 与停止/恢复。
（`search`/`model`/prompt provider 已提前至 M1。）

- [x] Docker runtime：每次 Worker 调用一个临时容器（container-per-worker），挂载 run dir，调用结束销毁；
      并发上限见 `[worker].max_concurrency`；镜像内置 Node + `pi` + TS 扩展 — **M3a**：`Dockerfile.runtime`、
      `make image`、`runtime/container.py`（`ContainerWorker`）、`runtime/runner.py`
- [ ] 容器池（后续优化）：`[worker].max_concurrency` 预热 N 个容器、调用时复用（先 per-call 起/销毁）
- [x] server 侧容器生命周期管理（创建/监控/回收）与 Dispatcher 接入（协议唯一写入者）— **M3a**：
      `ContainerWorker` 每次起/销毁容器（`docker run/rm`）+ `GET /health` 就绪轮询；Engine 仍为唯一写入者
- [x] 预算执行：`max_steps` / `max_wall` / `max_cost` 触顶即停并落盘中间态 — **M3b**：`engine.py`
      （`_budget_exceeded` / `_stop_for_budget`，轮次边界检查 → `STOPPED{reason:"budget exceeded",budget}`）、
      `pricing.py`（models.dev 定价）、usage 链路（`ModelResult`/`WorkerReply.usage`/SESSION payload）；
      事件日志即中间态（append-only，可 replay 到 STOPPED）
- [x] 可控性：随时停止/恢复，状态完整保留；Intent 心跳超时释放 — **M3b**：`PAUSED`/`RESUMED` 事件 +
      `PauseRun`/`ResumeRun` RPC（`engine.request_pause`/`resume_from_pause`，轮次边界挂起，计数器从黑板重建）；
      心跳释放 I4 已落地
- [ ] 异步 Hint 注入（`author=human|agent`）不阻塞 run
- [ ] **Gate C（最终审阅）**：记分卡产出前人工确认，可要求重查（新生 Intent）
- [ ] `prompt` provider `langfuse` 真实接入（`local` 已于 M1 可用）
- [ ] `originweave capabilities list|install-obscura` 实现
- [ ] `originweave mcp` 暴露 capability / 只读 run 视图（不承担调度）
- [ ] 集成测试：`replay` 路径 + 至少一条真实 provider 冒烟（受凭据约束时可跳过）

> **Phase R 调整**：原「`search`/`prompt`/`model` provider 真实接入」条目中的
> `search` 与 `model` **已提前至 M1**；M3 起不再有离线/录制回放。

验收：一次真实 run 的每个 Worker 调用在临时容器内完成并随调用结束回收；预算触顶、停止/恢复、
Hint 注入、Gate C 行为均可观测。

---

## M4 · 端到端、Deployment 与文档回归

目标：端到端闭环、server 容器化部署，以及文档/契约一致性回归（server 与前端已在 M1c-1 / M1c-2a/2b 落地）。

- [x] **前置：`CreateProject` + 可写服务入口**（demo 从零起步）— proto `CreateProject` RPC + 消息；
  `server/service.py` `create_project`（id 校验 / 空 name → `INVALID_ARGUMENT`、重复 → `ALREADY_EXISTS`、
  pinned 拒绝）；`dashboard.md §3/§4.1`；前端 `/projects/new`（`routes/NewProject.tsx` + `useCreateProject` +
  Overview 入口）；`Makefile` `dev`（可写，`ui`/`run` 仍为只读样例）
- [ ] 端到端 `make demo`：资料 A → 抽象论点 → DAG → 记分卡 → 前端可见 → `replay` 可复现
- [ ] server 运行于 Docker（Deployment 层）
- [ ] 文档一致性回归：`overview/`、`proto/` 与本文件术语/契约无漂移

验收：从 UI 发起一次核验并看到由抽象论点拆解出的 DAG + 记分卡，可在 Gate 处人工介入；
`replay` 复现同一结论；架构红线未被突破（前端不编排、server 拥有调度、执行在临时容器内
（container-per-worker））。

---

## M5 · 实体/组织关系图

目标：从资料 A 抽取实体（人 / 组织 / 产品 / 地点等）并判别实体间关系，产出独立的
**实体-关系图**（与溯源 DAG 并列、共享同一 run 与事件溯源）；关系用「预定义本体 +
`other`」，允许无来源推断但必须显式标注。

- [x] 领域模型：`Entity` / `Relation` / `EntityGraph`（`src/originweave/blackboard.py`），字段与 `product-overview.md` 第 4 节一致 — `blackboard.py`（`Entity`/`Relation`/`EntityGraph` + `Board.entities/relations`）
- [x] 关系本体：预定义正向类型 + `other`（反向标签由渲染层派生，不建反向型）— `blackboard.py` `RELATION_TYPES`/`RelationType`（渲染端反向标签归 M5d）
- [x] 事件 `ENTITY` / `RELATION` writer + reducer 分支（纯 fold；事件追加式，`ENTITY` 按 id upsert）— `events.py`（`ENTITY`/`RELATION`）+ `reduce.py`（`ENTITY` 按 id upsert、`RELATION` 追加）
- [ ] Intent 类型 `extract`（实体抽取）/ `relate`（关系判别），复用 OODA 与 Dispatcher
- [ ] 实体消歧/合并：按规范化名称归并同名实体，`aliases` 累积（保证重放确定性）
- [ ] server `CreateRun(analysis=relation|both)` 触发关系图抽取（测试注入 fake provider）
- [ ] run dir 产物 `entity-graph.json`（可由事件重建，非事实来源）
- [ ] 无来源推断标注：`Relation.status=inferred` + 置信度，渲染为虚线
- [ ] server：`RunDetail.entity_graph` 与 `CreateRunRequest.analysis`（proto）
- [ ] dashboard：`RELATIONS`（关系图，复用图组件）与 `ENTITIES`（实体表）页签
- [ ] 单测：给定 fixture 输入产出确定性 `EntityGraph`（实体 / 关系 / 证据或 `inferred` 断言）
- [ ] 关系样例 fixture（含多个组织，新增于 `examples/`）

验收：`CreateRun(analysis=relation)` 产出一张实体-关系图，每条关系或带
`quote+url` 证据、或标记 `inferred`（虚线 + 置信度）；UI 的 `RELATIONS` 页签可查看并
回链证据；`replay` 复现同一张图；架构红线未被突破。

---

## M6 · Pi Worker、可配置工具与会话

目标：把执行体抽为**可插拔 `Worker`**（`local` / `pi`），接入 Pi（`pi-py-sdk`，驱动官方
TS agent 运行时）作为 Worker 实现，并**以 `pi` 为项目级默认**；每个 agent 任务（节点）= 一次
Worker 调用 = 一个**隔离会话**，历史以会话为单位保留**原始输入/输出**与步骤链；worker 为
**项目级配置**（`[worker]`：provider / max_concurrency / tools / budget），其 **LLM 复用
`[capability.model]`**（openai 兼容：model + base_url，密钥 `OPENAI_API_KEY` 仅 env）；工具可配置；
检索由 Pi 侧 TS 扩展执行但**回调 server `Search` RPC**（provider 选择留在 Python，保红线 5）。
**Engine 始终是编排者与黑板唯一写入者**，事件溯源契约不变。

> 依赖：P1/P2 不依赖 server；P3–P5 依赖 **M1c-1**（server 骨架）先落地；容器化并入 M3。

- [x] P0 契约/文档：`agent-design.md`（`[worker]`、run dir `sessions/`、Pi 于 runtime）、
      `blackboard-protocol.md`（`SESSION`/`WORKER_STEP`）、`dashboard.md`（设置页 + Settings/Search RPC +
      会话视图）、`product-overview.md`（`Session`）、`docs/README.md`（术语）
- [x] P1 `Worker` 抽象：`capabilities/worker.py`（`Worker` Protocol / `WorkerReply{text,input,steps}` /
      `WorkerStep` / `LocalWorker`）；`Engine` 改接 `worker`，发 `SESSION`/`WORKER_STEP`、落会话文件
- [x] P1 配置 `[worker]`（`provider` / `max_concurrency` / `tools`）+ `config.py` 校验
- [x] P1 事件 `SESSION`/`WORKER_STEP`（reducer 忽略，Board 不变、`replay` 确定）+ run dir `sessions/`
- [x] P1b 配置迁移（项目级完整化）：**退役顶层 `[budget]`，迁至 `[worker].budget`**
      （`max_steps` / `max_wall` / `max_cost`；补 `max_wall` 时长校验）；`[worker].provider` **默认 `pi`**；
      worker 的 LLM **复用 `[capability.model]`**（仅 openai 兼容：`model` + `base_url` + `OPENAI_API_KEY` env，
      设置页不落密钥）。同步 `agent-design.md §2.1/§4`、`dashboard.md §4.3`（`CreateRun` 预算 override 回落
      `[worker].budget`）、`product-overview.md`、`AGENTS.md`；改 `tests/test_config.py`、`tests/test_worker.py`
- [x] P2 `PiWorker`（`capabilities/pi.py`）：每会话新建并 `dispose`、`prompt_stream → WorkerStep`、
      工具白名单 + `cwd` 沙箱、`[capability.model]` → Pi model/auth 映射；**运行时（Node + `pi` 二进制）
      缺失时明确报错并给安装指引（不静默降级）**；**Pi 会话 turns 计入 `max_steps`，单会话受
      `[worker].budget` 约束**（注入 fake 测试，不打真网）
- [x] P3a proto + `GetSettings`/`UpdateSettings`：`Session`/`SessionStep`、`Settings`/`WorkerSettings`
      （`LlmSettings{provider,model,baseUrl}`（来自 `[capability.model]`）、`provider`、`tools` 扁平
      `string[]`、`WorkerBudget{maxSteps,maxWall,maxCost}`）+ `GetSettings`/`UpdateSettings` RPC；
      `config.save`（校验后落 toml）+ `ServerContext.apply_settings`（重建 worker/search/prompt，
      **后续 run 生效**，含 `max_concurrency` = engine 信号量、仅按 run）—
      `proto/originweave/v1/originweave.proto`、`server/{service,convert,context}.py`、`config.py`
- [x] P3b `Search` RPC：经 `[capability.search]` 执行检索（只读、provider 选择留 Python），
      供 Pi TS 扩展回调（P4 消费、P6 容器内）— `server/service.py`（`search`；空 query/非法
      `num_results` → `INVALID_ARGUMENT`，provider 失败 → `UNAVAILABLE`）
- [x] P3c `RunDetail.sessions[]`：读 run dir `sessions/*.json`（原始输入/输出 + 完整步骤链；
      样例目录无 `sessions/` 则为空）— `store.read_sessions`、`convert.session_pb`/`session_step_pb`、
      `service._run_detail`（`RunStore` → `sessions`）
- [x] P4 TS 搜索扩展：注册 `search` 工具，仅回调 server `Search` RPC —
      `src/originweave/pi_extensions/search.ts`（包内资源；`ORIGINWEAVE_SERVER_URL`，默认
      `http://127.0.0.1:8765`）；`PiWorker` 注入 `-e <ext>` + `--tools search` 与 server URL、
      暴露 `tools`；`explore` 检索归属：**worker 拥有 `search` 工具时由 agent 自主检索、引擎不预取**
      （否则维持引擎预取）；顺带修 P2 live bug（`resolve_agent_dir_env_name` 按二进制推导 agent-dir
      环境变量名）
- [x] P5 前端：Settings 页（worker provider（默认 pi）/ LLM（model、base_url；密钥仅占位提示）/
      budget（max_steps、max_wall、max_cost）/ 工具开关）+ INSPECTOR 会话视图（原始输入 + 原始输出 +
      步骤链）+ EVENTS 按 worker 过滤 — `frontend/src/routes/Settings.tsx`（+ `settingsModel.ts`）、
      `api/hooks.ts`（`useSettings`/`useUpdateSettings`，全量 worker 块）、`layout/Inspector.tsx`
      （`SessionView`；任务会话另列）、`tabs/{EventsTab.tsx,events.ts}`（worker 过滤）、`routes/Console.tsx`
- [x] P6 容器化（由 M3a 落地）：runtime 镜像内置 Node + `pi` + TS 扩展（包内资源）；会话 `cwd` 沙箱
      （`docker run -w <run_dir> -v <run_dir>`）— `Dockerfile.runtime`、`make image`、`runtime/container.py`。
      备注：容器模式下 `search` 工具被过滤，检索仍由引擎在 host 侧预取（M3a 取舍）

验收：`[worker].provider="pi"`（默认）时，一次 run 的每个节点产生隔离会话（`sessions/*.json` 含原始
输入/输出与步骤链），`WORKER_STEP` 事件可按 worker 复原执行链路；worker 的 LLM 由 `[capability.model]`
提供，预算由 `[worker].budget` 约束；运行时缺失时给出可操作的报错而非静默失败；`parse_*`/`reduce`/`replay`
行为不变；TS 扩展检索经 server `Search`，切换 `[capability.search]` provider 不需改 Pi；架构红线未被突破。
