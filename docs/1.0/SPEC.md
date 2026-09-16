# originweave 1.0 · SPEC

活跃版本：**1.0**。本文件的 checkbox 是进度的**唯一载体**，由 `checkpoint` 阶段更新。
每个 milestone 对应一个 `##` 小节，顺序即执行顺序。

参考文档：

- 产品与领域模型 → [`../overview/product-overview.md`](../overview/product-overview.md)
- 黑板协议与 HITL → [`../overview/blackboard-protocol.md`](../overview/blackboard-protocol.md)
- 执行架构与架构红线 → [`../overview/agent-design.md`](../overview/agent-design.md)
- UI 与 REST 契约 → [`../overview/dashboard.md`](../overview/dashboard.md)

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
- [x] CLI 骨架 — `src/originweave/cli.py`（`trace/ui/replay/capabilities/mcp/init` 全部声明，dispatch 到占位实现）
- [x] smoke 测试 — `tests/test_smoke.py`（版本可用、parser 可构建、无命令打印帮助、子命令为 stub）

验收：`make lint` / `make test` 通过；`originweave --help` 列出全部子命令。

---

## M0b · 配置与 capability 层骨架

目标：可配置、离线优先，外部能力以可替换 provider 接入。

- [x] `init` 生成默认配置（`originweave init`），含 `LIVE` 与 `auto`（HITL 默认人工介入）开关；落盘位置与格式在实现时确定并回写 `agent-design.md`
- [x] 配置加载与校验（`LIVE=0` 默认离线）
- [x] capability 抽象接口：`search` 与 `prompt` 两个 capability 的最小 Protocol
- [x] search provider 注册表：`exa` / `parallel`（可 import，未配置时给出清晰报错）
- [x] prompt provider 注册表：`local` / `langfuse`
- [x] 本地 cache / mock 后端：离线时返回录制内容（与 M0d 的 fixtures 对接）
- [x] capability 调用可录制：产出可重放的请求/响应记录
- [x] 单测：配置加载、provider 选择、离线/联机分支

验收：capability 层在 `LIVE=0` 下不触网且有可预期的 mock 行为（`trace` 循环属 M1，仍为 stub）。

---

## M0c · 黑板事件日志与事件溯源

目标：一次 run 的全部状态由 append-only 黑板事件派生，且可只读重放。

- [x] run 目录布局落地（`events.jsonl`、`input/`、`sources/`、`capabilities/`、`report.md`；其中 `report.md` 于 M2 生成）
- [x] 黑板协议事件 writer：`PROJECT/INTENT/EXECUTE/CONCLUDE/REASON/COMPLETE/HEARTBEAT/RELEASE/HINT/REQUEST_HUMAN/HUMAN_INPUT`（`Event{id,at,type,message,tone,payload}`）
- [x] 由事件重建黑板状态（`Board{origin,goal,facts,intents,hints}` + `edges/status/decisions/waitingFor/verdict`）的 reducer
- [x] `originweave replay <run-dir>` 只读、不触网、复现含人工输入在内的结论（替换当前 stub）
- [x] 保留策略：`runs/` 与 `*.jsonl` 不入库（`.gitignore` 已就绪，需确认新布局覆盖）
- [x] 单测：写入 → 重放一致性（byte-level 或结构级）

验收：同一 run dir 连续两次 `replay` 结果一致；replay 过程无网络访问。

---

## M0d · 迁入 obscura_kitesurf spike

目标：把真实样例固化为端到端 fixtures，供 `make demo` / `make run` 使用。

- [ ] 迁入资料 A（`examples/obscura_kitesurf/`，替换占位 README）
- [ ] 迁入来源快照（可回链的原文/存档）
- [ ] 迁入录制的 capability 响应（检索 + prompt），供离线运行
- [ ] `make demo` 端到端可跑（mock / cache）
- [ ] `make run` 可起本地环境（`LIVE=0` 默认离线）
- [ ] 文档：样例说明与预期产物

验收：全新环境 `make demo` 产出 DAG + 记分卡（可先为简化版）且不触网。

---

## M1 · 黑板与 Agent 循环

目标：实现黑板块与 OODA 工作循环，从 A 抽取抽象论点并拆解、回链来源；
支持多 Worker 并发与 HITL Gate A。

- [ ] 黑板模型：`Board{origin,goal,facts,intents,hints}` 与 `Fact`（kind/role/status/confidence/evidence）、`Intent`、`Hint`
- [ ] `origin`/`goal` 特殊 Fact；`Fact.role = main-claim | sub-claim`
- [ ] 三种任务指令：`Bootstrap` / `Reason` / `Explore`
- [ ] Intent 三型：`decompose` / `explore` / `verify`（type 字段与调度分支）
- [ ] 抽象论点抽取与拆解（`Bootstrap` → `main-claim`；`Intent(decompose)` → `sub-claim`）
- [ ] 来源回链：`citation` / `source` 节点与 `Evidence{quote,sourceTitle,url,locator}` 登记
- [ ] DAG 组装与边 relation：`main-chain/dependency/goal-derived/decomposes/spawns/resolves`
- [ ] 多 Worker 并发认领 Intent + 心跳/超时自动释放（`HEARTBEAT`/`RELEASE`）
- [ ] Stigmergy：新 Fact 触发新一轮 Reason（去重）
- [ ] 进程内 Dispatcher（接口与 M3 的容器 Dispatcher 一致）：任务派发与协议写回
- [ ] HITL 机制与 **Gate A（论点确认）**：`REQUEST_HUMAN`/`HUMAN_INPUT`，run → `awaiting_human`
- [ ] `--auto` 全自动路径（跳过 Gate）
- [ ] 单测：给定 fixture 输入，产出确定性 Board/DAG（节点/边/证据断言）

验收：对 `obscura_kitesurf` 样例，核心抽象论点被拆解为子断言，每条子断言可回溯到
至少一条带 `quote+url` 的证据或标记为 `open`；≥2 Worker 并发时无 Intent 重复执行；
Gate A 可挂起并可恢复。

---

## M2 · 偏差记分卡

目标：`Intent(verify)` / `compare(facts × sources × goal)` 输出偏差分类与 report。

- [ ] `compare` 引擎节点（`compare` kind）汇总 facts × sources × goal
- [ ] deviation 分类（篡改 / 改写 / 省略 / 归因错误 / 时间错置等）与 `deviation` 节点
- [ ] 每项 deviation 带 `severity(high|medium|low)` 与 `confidence`
- [ ] goal 重定义生效：抽象论点全部拆解 + 回链 + 偏差判定完成才 `COMPLETE`
- [ ] 整体 `verdict` 与 `Report{summary,findings,sources}` 生成（`report.md` / `--json`）
- [ ] **Gate B（歧义裁决）**：置信度低/来源冲突时发起 `REQUEST_HUMAN`
- [ ] 单测：对样例给出预期偏差集合与阈值行为

验收：`trace --out report.md` 产出含 verdict、逐条 deviation 与来源清单的报告；
Gate B 可对冲突来源人工裁决并继续。

---

## M3 · agent runtime 与 capabilities

目标：真实执行走 container-per-run（容器内多 Worker）；能力与 prompt 可切换；
能力经 MCP 暴露；支持异步 Hint 与停止/恢复。

- [ ] Docker runtime：每次 run 一个临时容器，内含 N≥1 Worker，挂载 run dir，run 结束销毁
- [ ] server 侧容器生命周期管理（创建/监控/回收）与 Dispatcher 接入（协议唯一写入者）
- [ ] 预算执行：`--max-steps` / `--max-wall` / `--max-cost` 触顶即停并落盘中间态
- [ ] 可控性：随时停止/恢复，状态完整保留；Intent 心跳超时释放
- [ ] 异步 Hint 注入（`author=human|agent`）不阻塞 run
- [ ] **Gate C（最终审阅）**：记分卡产出前人工确认，可要求重查（新生 Intent）
- [ ] `search` provider 真实接入：`exa` / `parallel`
- [ ] `prompt` provider 真实接入：`local` / `langfuse`
- [ ] `originweave capabilities list|install-obscura` 实现
- [ ] `originweave mcp` 暴露 capability / 只读 run 视图（不承担调度）
- [ ] 集成测试：离线重放路径 + 至少一条真实 provider 冒烟（受凭据约束时可跳过）

验收：一次真实 run 在临时容器内完成；容器随 run 结束被回收；预算触顶、停止/恢复、
Hint 注入、Gate C 行为均可观测。

---

## M4 · server API 与 dashboard

目标：冻结契约落地为真实 server API；前端源码入库并构建；端到端闭环。

- [ ] server 提供 `dashboard.md` 第 4.1 节的 8 个端点（含 `/hints` 与 `/human-input`），字段与领域模型一致
- [ ] `originweave ui` 起只读视图（替换 stub），默认读 run dir
- [ ] server 运行于 Docker（Deployment 层）
- [ ] 前端源码入库（仓库中当前无前端源码；需从零纳入版本控制与构建流程）
- [ ] 前端不接 mock，直连真实 `/api/*`（契约以 `dashboard.md` 为准）
- [ ] DAG 渲染 Intent 节点（open/claimed/done/dropped/awaiting_human）与 `decomposes/spawns/resolves` 边
- [ ] HITL UI：Gate A/B/C 交互、写 Hint、`awaiting_human` 提示、Replay 步进、Snapshot、Log
- [ ] 端到端 `make demo`：A → 抽象论点 → DAG → 记分卡 → UI 可见 → `replay` 可复现
- [ ] 文档一致性回归：`overview/` 与本文件术语/契约无漂移

验收：从 UI 发起一次核验并看到由抽象论点拆解出的 DAG + 记分卡，可在 Gate 处人工介入；
`replay` 复现同一结论；架构红线未被突破（前端不编排、server 拥有调度、执行在临时容器内）。

---

## M5 · 实体/组织关系图

目标：从资料 A 抽取实体（人 / 组织 / 产品 / 地点等）并判别实体间关系，产出独立的
**实体-关系图**（与溯源 DAG 并列、共享同一 run 与事件溯源）；关系用「预定义本体 +
`other`」，允许无来源推断但必须显式标注。

- [ ] 领域模型：`Entity` / `Relation` / `EntityGraph`（`src/originweave/model.py`），字段与 `product-overview.md` 第 4 节一致
- [ ] 关系本体：预定义正向类型 + `other`（反向标签由渲染层派生，不建反向型）
- [ ] 事件 `ENTITY` / `RELATION` writer + reducer 分支（纯 fold，追加式）
- [ ] Intent 类型 `extract`（实体抽取）/ `relate`（关系判别），复用 OODA 与 Dispatcher
- [ ] 实体消歧/合并：按规范化名称归并同名实体，`aliases` 累积（保证重放确定性）
- [ ] `originweave trace <target> --mode relation|both`（替换 stub），离线可跑
- [ ] run dir 产物 `entity-graph.json`（可由事件重建，非事实来源）+ `--json` 输出
- [ ] 无来源推断标注：`Relation.status=inferred` + 置信度，渲染为虚线
- [ ] server：`RunDetail.entityGraph` 与 `POST /api/runs` 的 `analysis` 字段
- [ ] dashboard：`RELATIONS`（关系图，复用图组件）与 `ENTITIES`（实体表）页签
- [ ] 单测：给定 fixture 输入产出确定性 `EntityGraph`（实体 / 关系 / 证据或 `inferred` 断言）
- [ ] 关系样例 fixture（含多个组织，新增于 `examples/`）

验收：`trace <target> --mode relation` 离线产出一张实体-关系图，每条关系或带
`quote+url` 证据、或标记 `inferred`（虚线 + 置信度）；UI 的 `RELATIONS` 页签可查看并
回链证据；`replay` 复现同一张图；架构红线未被突破。
