# originweave 1.0 · TODO

滚动待办与已知阻塞。**进度真相在 `SPEC.md`**；本文件只记录跨任务的临时事项、
待确认决策与风险，不重复 SPEC 条目。

## 下一个任务

- **M0b · 配置与 capability 层骨架**（见 `SPEC.md` 的 M0b 小节）

## 待确认决策

- [ ] 配置文件的默认格式与落盘位置（`init` 产物）：`originweave.toml`？`~/.config/originweave/`？
- [ ] run dir 的默认根目录（当前 `Makefile` 用 `RUN_DIR ?= examples/obscura_kitesurf`，需与 `.gitignore` 的 `runs/` 对齐）
- [ ] `search` / `prompt` 的 provider 凭据管理方式（env / 配置文件 / 外部 secret）
- [ ] Docker runtime 的镜像来源与构建归属（server 仓内构建 vs 独立镜像）
- [ ] HITL Gate 的默认范围与配置粒度（三个 Gate 是否可逐项开关；`auto` 是否支持 per-gate）
- [ ] Worker 并发数 N 的默认值与上限（受预算 `--max-cost` 约束）

## 已知风险 / 缺口

- `frontend/`（仅有构建产物，源码从未入库）已在清理中整体移除；M4 需**从零重建前端源码工程**。
  在此之前 UI 不能视为可维护资产。
- `Makefile` 的 `demo`/`run`/`ui` target 依赖尚不存在的 `trace`/`ui` 实现，现阶段执行会命中 stub。
- `examples/obscura_kitesurf/` 仅有占位 README，M0d 才迁入真实 fixtures。
- 尚无 capability 录制的存储格式约定（M0b 需先定义，M0d 依赖它）。

## 已完成（近期）

- 引入**黑板架构**（参考 Cairn）：新增 `docs/overview/blackboard-protocol.md`，
  重写 `agent-design.md` 的循环为 OODA + Bootstrap/Reason/Explore；领域模型新增
  `Fact/Intent/Hint`、`origin/goal` 特殊 Fact、`Fact.role`、`Intent.type`，事件改为
  黑板协议事件，`Run.status` 增 `awaiting_human`，并加入三个 HITL Gate。
- 补齐 docs-first 事实来源：`milestones.md`、`docs/README.md`、`docs/overview/*`、本文件与 `SPEC.md`。
- 进度可被 `progress-tracker` 识别；下一个任务为 M0b。
