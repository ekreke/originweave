# Milestones

originweave 的版本与里程碑索引。**当前唯一活跃版本：`1.0`**（定义于 `docs/1.0/SPEC.md`）。

约定：

- 一个版本内按 `M<major><stage>` 切分，每个 milestone 对应 `docs/1.0/SPEC.md` 中的一个 `##` 小节。
- 状态取值：`未开始` / `进行中` / `已完成`。
- 进度只由 checkpoint 阶段写回；勾选必须能指向仓库中的真实文件。

## 1.0

| Milestone | 一句话目标 | 状态 | 依赖 |
|---|---|---|---|
| M0a | 仓库脚手架：依赖管理、Makefile、CI、README、CLI 骨架与 smoke 测试 | 已完成 | — |
| M0b | 配置与 capability 层骨架：`init` 生成默认配置（含 `auto`）、provider 注册表（离线/cache/录制已于 Phase R 撤销） | 已完成 | M0a |
| M0c | 黑板事件日志与事件溯源：run 目录布局、黑板协议事件、`replay` 只读重放 | 已完成 | M0b |
| M0d | 构建 `copilot_productivity` 样例：资料 A、来源快照、事件日志 | 已完成 | M0c |
| M1 | 黑板与 Agent 循环（库层）：OODA 三任务、真实 `model`(OpenAI 兼容) + `search`(exa/parallel)、抽象论点拆解与来源回链、真线程多 Worker + Stigmergy、Gate A | 进行中 | M0d |
| M1b | 前端脚手架：React + Vite + TS + Connect、Swiss/Blueprint 布局与页签空态（无 mock；可与 M1 并行） | 已完成 | M0d |
| M1c-1 | server 骨架：Connect Python server（Starlette + uvicorn）、`Run`/`Project` 持久化、接线 M1 引擎、`originweave ui` | 进行中 | M1 |
| M1c-2 | 前端接线与 UI：React Query 数据层、DAG/React Flow 渲染、HITL Gate UI、端到端 | 未开始 | M1c-1 |
| M2 | 偏差记分卡：`Intent(verify)`/`compare(facts × sources × goal)` → deviation 分类与 report、Gate B | 未开始 | M1c-2 |
| M3 | agent runtime：Docker container-per-run（多 Worker）、容器 Dispatcher、MCP、`langfuse`、预算、异步 Hint、Gate C（`search`/`model` 已提前至 M1） | 未开始 | M2 |
| M4 | 端到端、Deployment 与文档回归：`make demo` 闭环、server Docker、`overview/`+`proto/` 契约无漂移 | 未开始 | M3 |
| M5 | 实体/组织关系图：从 A 抽取实体并判别关系，产出独立的关系图（本体 + 证据/推断标注） | 未开始 | M4 |
| M6 | Pi Worker 与可配置工具：执行体抽为可插拔 `Worker`（默认 `pi`，经 `pi-py-sdk`）；节点级隔离会话（原始输入/输出 + 步骤链）；项目级 `[worker]`（provider / 并发 / 工具 / `[worker].budget`，LLM 复用 `[capability.model]`）；TS 搜索扩展回调 server | 进行中 | M1c-1（P3+；P1/P2 不依赖） |

## 下一版本（待规划）

- 暂无。1.0 完成后在此登记 1.1 / 2.0 的切入方向。
