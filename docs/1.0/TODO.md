# originweave 1.0 · TODO

滚动待办与已知阻塞。**进度真相在 `SPEC.md`**；本文件只记录跨任务的临时事项、
待确认决策与风险，不重复 SPEC 条目。

## 下一个任务

- **M0d · 迁入 obscura_kitesurf spike**（见 `SPEC.md` 的 M0d 小节）

## 待确认决策

- [x] 配置文件的默认格式与落盘位置（`init` 产物）→ 项目内 `originweave.toml`（M0b 定）
- [x] `search` / `prompt` 的 provider 凭据管理方式 → 仅环境变量（M0b 定）
- [x] capability 录制格式 → 每次调用一个 JSON，`<run-dir>/capabilities/<provider>/<request_hash>.json`（M0b 定）
- [ ] run dir 的默认根目录（配置 `[run].dir = "runs"` 与 `Makefile` 的 `RUN_DIR ?= examples/obscura_kitesurf` 需对齐）
- [ ] Docker runtime 的镜像来源与构建归属（server 仓内构建 vs 独立镜像）
- [ ] HITL Gate 的默认范围与配置粒度（三个 Gate 是否可逐项开关；`auto` 是否支持 per-gate）
- [ ] Worker 并发数 N 的默认值与上限（受预算 `--max-cost` 约束）
- [ ] 关系图渲染库选型（M4 前端从零重建时统一选定，provenance DAG 与 RELATIONS 复用同一渲染器）
- [ ] 关系样例 fixture 来源（新增含多个组织的样例 vs 复用 `obscura_kitesurf`）
- [ ] 实体消歧粒度：同名/别名归一的规范化规则（大小写、全称/简称、去空白）

## 已知风险 / 缺口

- `frontend/`（仅有构建产物，源码从未入库）已在清理中整体移除；M4 需**从零重建前端源码工程**。
  在此之前 UI 不能视为可维护资产。
- `Makefile` 的 `demo`/`run`/`ui` target 依赖尚不存在的 `trace`/`ui` 实现，现阶段执行会命中 stub。
- `examples/obscura_kitesurf/` 仅有占位 README，M0d 才迁入真实 fixtures。
- **契约-代码漂移（M5 范围，未实现）**：`Entity`/`Relation`/`EntityGraph`、`ENTITY`/`RELATION`
  事件、`Intent.extract`/`relate`、CLI `--analysis` 已在 `overview/` 冻结契约中，但
  `model.py` / `events.py` / `reduce.py` / `cli.py` 尚未实现（归 M5）。
  另：`stopped`/`failed` 已进 `Run.status` 契约，但 `model.RUN_STATUSES` 未同步（M1/M5 落地时一并改）。
- M0b 遗留（review 判定非阻塞，可后补）：异常层次未完全收口（`LocalPrompt` 的
  `FileNotFoundError`、`cache.read` 的坏 JSON）、`capabilities list` 的 `ready` 文案在 M3 前有歧义、
  cache 写入非原子、`max_wall` 未做 duration 校验、部分 provider 分支测试缺失。

## 已完成（近期）

- **M5 契约入库**（未实现）：`milestones.md` 增 M5；`SPEC.md` 增 M5 小节；`overview/` 新增
  `Entity`/`Relation`/`EntityGraph`、关系本体表、`ENTITY`/`RELATION` 事件、Intent `extract`/`relate`、
  CLI `trace --analysis`、`Run.analysis` 与 `dashboard` 的 `RELATIONS`/`ENTITIES` 页签、`RunDetail.entityGraph`；
  `dashboard.md` 新建 run body 的 `mode` 改名 `sourceType` 并新增 `analysis`。

- **M0c 黑板事件日志与事件溯源**：`model.py`（Board/Fact/Intent/Hint/Edge/HumanDecision）、
  `events.py`（`Event` + 11 种 type）、`store.py`（run 目录 + append-only `events.jsonl`）、
  `reduce.py`（纯函数 fold，自动推导 `spawns`/`resolves`/`decomposes`，语义边来自 payload）、
  CLI 接线 `replay`（只读 stdout，`--json`）。63 测试通过，ruff + mypy strict 全绿。
- **M0b 配置与 capability 层骨架**：`config.py`（`originweave.toml`，`tomllib` 读 / `tomli-w` 写，
  未知键报错，`ORIGINWEAVE_LIVE` 覆盖）、`capabilities/`（Protocol + exa/parallel/local/langfuse
  注册表 + 录制/回放 + `build_search`/`build_prompt` 离线-联机接线）、CLI 接线 `init` 与
  `capabilities list`。
- 引入**黑板架构**（参考 Cairn）：新增 `docs/overview/blackboard-protocol.md`，
  重写 `agent-design.md` 的循环为 OODA + Bootstrap/Reason/Explore；领域模型新增
  `Fact/Intent/Hint`、`origin/goal` 特殊 Fact、`Fact.role`、`Intent.type`，事件改为
  黑板协议事件，`Run.status` 增 `awaiting_human`，并加入三个 HITL Gate。
- 补齐 docs-first 事实来源：`milestones.md`、`docs/README.md`、`docs/overview/*`、本文件与 `SPEC.md`。
