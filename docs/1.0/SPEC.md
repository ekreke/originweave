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
> 对应代码（`[live]`、`capabilities/cache.py`、`record.py`、样例 `capabilities/**`）待后续代码迭代清理。

验收：配置加载与 provider 解析可用（引擎循环属 M1，仍为 stub）。

---

## M0c · 黑板事件日志与事件溯源

目标：一次 run 的全部状态由 append-only 黑板事件派生，且可只读重放。

- [x] run 目录布局落地（`events.jsonl`、`input/`、`sources/`、`report.md`；其中 `report.md` 于 M2 生成）
- [x] 黑板协议事件 writer：`PROJECT/INTENT/EXECUTE/CONCLUDE/REASON/COMPLETE/HEARTBEAT/RELEASE/HINT/REQUEST_HUMAN/HUMAN_INPUT`（`Event{id,at,type,message,tone,payload}`）
- [x] 由事件重建黑板状态（`Board{origin,goal,facts,intents,hints}` + `edges/status/decisions/waitingFor/verdict`）的 reducer
- [x] `originweave replay <run-dir>` 只读、不触网、复现含人工输入在内的结论（替换当前 stub）
- [x] 保留策略：`runs/` 与 `*.jsonl` 不入库（`.gitignore` 已就绪，需确认新布局覆盖）
- [x] 单测：写入 → 重放一致性（byte-level 或结构级）

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
真线程并发与 HITL Gate A。引擎为**库层**（进程内 Dispatcher），**不经 CLI 暴露**；
API 与交互由 M1c-1 / M1c-2 落地；真实接入 `model`（OpenAI 兼容）与 `search`（exa/parallel）。

- [x] 黑板模型：`Board{origin,goal,facts,intents,hints}` 与 `Fact`（kind/role/status/confidence/evidence）、`Intent`、`Hint` — `src/originweave/blackboard.py`（M0c）
- [x] `origin`/`goal` 特殊 Fact（`kind` 区分、`role=none`）；`Fact.role = main-claim | sub-claim` — `blackboard.py`（M0c）
- [x] DAG 组装与边 relation：`main-chain/dependency/goal-derived/decomposes/spawns/resolves` — `src/originweave/reduce.py`（M0c）
- [ ] `model` capability：`ModelProvider` Protocol + **真实 OpenAI 兼容 provider**（`capabilities/model.py`、`[capability.model]`；凭据 `OPENAI_API_KEY` / `OPENAI_BASE_URL`）
- [ ] `search` capability 真实接入：`exa` / `parallel`（`capabilities/search.py`；凭据 `EXA_API_KEY` / `PARALLEL_API_KEY`）
- [ ] 三种任务指令：`Bootstrap` / `Reason` / `Explore`
- [ ] Intent 三型调度分支：`decompose` / `explore` / `verify`
- [ ] 抽象论点抽取与拆解（`Bootstrap` → `main-claim`；`Intent(decompose)` → `sub-claim`）
- [ ] 来源回链：`citation` / `source` 节点与 `Evidence{quote,sourceTitle,url,locator}` 登记
- [ ] 多 Worker 真线程并发认领 Intent + 心跳/超时自动释放（`HEARTBEAT`/`RELEASE`）；Dispatcher 按确定性顺序提交，保证 Board 确定
- [ ] Stigmergy：新 Fact 触发新一轮 Reason（去重）
- [ ] 进程内 Dispatcher（接口与 M3 的容器 Dispatcher 一致）：任务派发与协议写回（唯一写入者）
- [ ] HITL 机制与 **Gate A（论点确认）**：`REQUEST_HUMAN`/`HUMAN_INPUT`，run → `awaiting_human`（程序化挂起/恢复；交互归 M1c-2）
- [ ] 自动路径：`[hitl].auto=true`（或 M1c-1 的 `CreateRunRequest.auto`）跳过 Gate
- [ ] 单测：注入 **fake provider**，对 fixture 输入产出确定性 Board/DAG（节点/边/证据断言）

验收：对 `copilot_productivity` 样例，核心抽象论点被拆解为子断言，每条子断言可回溯到
至少一条带 `quote+url` 的证据或标记为 `open`；≥2 Worker 并发时无 Intent 重复执行；
Gate A 可挂起并可恢复。**`replay`（事件日志）字节确定；live run（真实 provider）不保证
确定，其结构断言由注入 fake provider 的测试覆盖。**

---

## M1b · 前端脚手架

目标：初始化 `frontend/`（React + Vite + TS + Connect），交付**无数据、无 mock**的界面壳
（三栏布局 / 路由 / 页签空态 / React Flow 空画布）。仅依赖已就绪的 `proto/`，
**可与 M1 并行、可先做**；真实数据接线归 M1c-2。

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

- [ ] Python codegen：`protoc-gen-connect-python` + 根 `buf.gen.yaml` → `src/originweave/gen`（生成物排除 ruff/mypy）
- [ ] 持久化：`runs/<run_id>/run.json`（`Run` 元数据）+ 目录式 `projects/` 注册表；`events.jsonl` 仍为 board 唯一事实来源
- [ ] server：只读视图（`ListProjects`/`GetProject`/`ListProjectRuns`/`ListRuns`/`GetRun`）+ `CreateRun` + `AddHint` + `SubmitHumanInput`（`RunStore` → `reduce()` → `RunDetail`）
- [ ] 接线 M1 引擎（进程内 Dispatcher）；`CreateRun` 分配 `run_00N` 并调用引擎；调度与持久化归 server（红线 2）
- [ ] `originweave ui`（替换 stub）：Starlette 提供 Connect 端点 + `frontend/dist` 静态
- [ ] 测试：ASGI 客户端对 service 的读写（注入 fake provider）、`replay` 路径

验收：起 server（测试注入 fake provider）→ `CreateRun` 用 `copilot_productivity` 样例产出 run →
`GetRun` 返回 `RunDetail`（含 events/facts/intents）→ `AddHint`/`SubmitHumanInput` 落为事件。

---

## M1c-2 · 前端接线与 UI

目标：前端改为读取真实数据（**不接 mock**），渲染 DAG 并在 HITL Gate 处提供人工介入。

- [ ] Connect 数据层：React Query hooks（`listProjects`/`listProjectRuns`/`getRun`/`createRun`/`addHint`/`submitHumanInput`）+ 轮询刷新 `awaiting_human`
- [ ] React Flow 节点/边：Fact 按 `kind`（形状+颜色）、Intent 按 `status`、边按 `relation`；布局用 proto `Fact.position`
- [ ] INSPECTOR：节点详情 + 证据逐字引用（`quote + sourceTitle + locator`）+ Intent 计数 + Hints 输入
- [ ] HITL UI：`awaiting_human` → Gate A/B/C 面板（approve/edit/reject）→ `submitHumanInput`；Replay 步进（前端按 `events[]`）
- [ ] 页签 FACTS / INTENTS / EVENTS 绑定真实数据（RELATIONS/ENTITIES 归 M5）
- [ ] 顶栏 / RunList：状态徽标、预算、操作、`awaiting_human` 高亮
- [ ] 端到端：起 server → 建 run → 前端看到 DAG → Gate 处人工介入（测试以 fake provider 驱动）
- [ ] 测试：组件测试（proto 消息 fixture）+ 冒烟

验收：从前端发起一次核验（样例），看到由抽象论点拆解出的 DAG，可在 Gate 处人工介入；
架构红线未被突破（前端不编排、server 拥有调度）。

---

## M2 · 偏差记分卡

目标：`Intent(verify)` / `compare(facts × sources × goal)` 输出偏差分类与 report。

- [ ] `compare` 引擎节点（`compare` kind）汇总 facts × sources × goal
- [ ] deviation 分类（篡改 / 改写 / 省略 / 归因错误 / 时间错置等）与 `deviation` 节点
- [ ] 每项 deviation 带 `severity(high|medium|low)` 与 `confidence`
- [ ] goal 重定义生效：抽象论点全部拆解 + 回链 + 偏差判定完成才 `COMPLETE`
- [ ] 整体 `verdict` 与 `Report{summary,findings,sources}` 生成（run dir `report.md`）
- [ ] **Gate B（歧义裁决）**：置信度低/来源冲突时发起 `REQUEST_HUMAN`
- [ ] 单测：对样例给出预期偏差集合与阈值行为

验收：run dir 产出 `report.md`（含 verdict、逐条 deviation 与来源清单），并经 server
`RunDetail.report` 暴露；Gate B 可对冲突来源人工裁决并继续。

---

## M3 · agent runtime 与 capabilities

目标：真实执行走 container-per-run（容器内多 Worker）；能力经 MCP 暴露；
支持异步 Hint 与停止/恢复。（`search`/`model`/prompt provider 已提前至 M1。）

- [ ] Docker runtime：每次 run 一个临时容器，内含 N≥1 Worker，挂载 run dir，run 结束销毁
- [ ] server 侧容器生命周期管理（创建/监控/回收）与 Dispatcher 接入（协议唯一写入者）
- [ ] 预算执行：`max_steps` / `max_wall` / `max_cost` 触顶即停并落盘中间态
- [ ] 可控性：随时停止/恢复，状态完整保留；Intent 心跳超时释放
- [ ] 异步 Hint 注入（`author=human|agent`）不阻塞 run
- [ ] **Gate C（最终审阅）**：记分卡产出前人工确认，可要求重查（新生 Intent）
- [ ] `prompt` provider `langfuse` 真实接入（`local` 已于 M1 可用）
- [ ] `originweave capabilities list|install-obscura` 实现
- [ ] `originweave mcp` 暴露 capability / 只读 run 视图（不承担调度）
- [ ] 集成测试：`replay` 路径 + 至少一条真实 provider 冒烟（受凭据约束时可跳过）

> **Phase R 调整**：原「`search`/`prompt`/`model` provider 真实接入」条目中的
> `search` 与 `model` **已提前至 M1**；M3 起不再有离线/录制回放。

验收：一次真实 run 在临时容器内完成；容器随 run 结束被回收；预算触顶、停止/恢复、
Hint 注入、Gate C 行为均可观测。

---

## M4 · 端到端、Deployment 与文档回归

目标：端到端闭环、server 容器化部署，以及文档/契约一致性回归（server 与前端已在 M1c-1 / M1c-2 落地）。

- [ ] 端到端 `make demo`：资料 A → 抽象论点 → DAG → 记分卡 → 前端可见 → `replay` 可复现
- [ ] server 运行于 Docker（Deployment 层）
- [ ] 文档一致性回归：`overview/`、`proto/` 与本文件术语/契约无漂移

验收：从 UI 发起一次核验并看到由抽象论点拆解出的 DAG + 记分卡，可在 Gate 处人工介入；
`replay` 复现同一结论；架构红线未被突破（前端不编排、server 拥有调度、执行在临时容器内）。

---

## M5 · 实体/组织关系图

目标：从资料 A 抽取实体（人 / 组织 / 产品 / 地点等）并判别实体间关系，产出独立的
**实体-关系图**（与溯源 DAG 并列、共享同一 run 与事件溯源）；关系用「预定义本体 +
`other`」，允许无来源推断但必须显式标注。

- [ ] 领域模型：`Entity` / `Relation` / `EntityGraph`（`src/originweave/blackboard.py`），字段与 `product-overview.md` 第 4 节一致
- [ ] 关系本体：预定义正向类型 + `other`（反向标签由渲染层派生，不建反向型）
- [ ] 事件 `ENTITY` / `RELATION` writer + reducer 分支（纯 fold，追加式）
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
