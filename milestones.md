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
| M0b | 配置与 capability 层骨架：`init` 生成默认配置（含 `LIVE`/`auto`）、provider 注册表、本地 cache/mock | 已完成 | M0a |
| M0c | 黑板事件日志与事件溯源：run 目录布局、黑板协议事件、`replay` 只读重放 | 已完成 | M0b |
| M0d | 迁入 `obscura_kitesurf` spike：待核资料 A、来源快照、录制的 capability 响应（真实 fixtures） | 未开始 | M0c |
| M1 | 黑板与 Agent 循环：黑板块、OODA 三任务、抽象论点拆解与来源回链、多 Worker + Stigmergy、Gate A | 未开始 | M0d |
| M2 | 偏差记分卡：`Intent(verify)`/`compare(facts × sources × goal)` → deviation 分类与 report、Gate B | 未开始 | M1 |
| M3 | agent runtime 与 capabilities：Docker container-per-run（多 Worker）、Dispatcher、MCP、`exa|parallel`、`local|langfuse`、异步 Hint、Gate C | 未开始 | M2 |
| M4 | server API 与 dashboard：冻结契约落地（含 HITL 端点）、前端源码入库并构建、端到端 `make demo` | 未开始 | M3 |
| M5 | 实体/组织关系图：从 A 抽取实体并判别关系，产出独立的关系图（本体 + 证据/推断标注） | 未开始 | M4 |

## 下一版本（待规划）

- 暂无。1.0 完成后在此登记 1.1 / 2.0 的切入方向。
