# originweave 1.0 · TODO

滚动待办与已知阻塞。**进度真相在 `SPEC.md`**；本文件只记录跨任务的临时事项、
待确认决策与风险，不重复 SPEC 条目。

## 下一个任务

- **M1 · 黑板与 Agent 循环**（见 `SPEC.md` 的 M1 小节）。核心新增：`model` capability
  （录制/回放）、OODA 三任务、真线程多 Worker + Dispatcher 确定性提交、进程内 Dispatcher、
  Gate A。样例的录制 query/prompt 清单见 `examples/copilot_productivity/README.md`，
  编排需与其对齐；M1 还需为样例补录 `capabilities/model/**`。
- 随后：M1c-1（server 骨架）→ M1c-2（前端接线与 UI）。

## 待确认决策

- [x] 配置文件的默认格式与落盘位置（`init` 产物）→ 项目内 `originweave.toml`（M0b 定）
- [x] `search` / `prompt` 的 provider 凭据管理方式 → 仅环境变量（M0b 定）
- [x] capability 录制格式 → 每次调用一个 JSON，`<run-dir>/capabilities/<provider>/<request_hash>.json`（M0b 定）
- [x] run dir 的默认根目录 → server 写 `runs/`（gitignored，`Makefile` 的 `RUNS_DIR`），
  `replay`/`ui` 读已入库的样例目录（`RUN_DIR`）（M0d 定）
- [x] 起 run 的入口 → **无 CLI `trace`**，走 server / proto `CreateRun`（契约重排定）
- [x] proto 方案 → **Connect / buf**，契约 `proto/originweave/v1/*.proto`（契约重排定）
- [x] 前端 → **React + Vite + `@connectrpc/connect-web`**，直连 proto、无 mock（契约重排定）
- [x] OODA 的模型抽象 → 新增 **`model` capability**（与 search/prompt 同构），provider 名 `local`（契约重排定）
- [x] 前端包管理/工具链 → **pnpm + Vite + React + TS**，ESLint + Prettier + Vitest（M1b 定）
- [x] 图渲染库 → **React Flow**（`@xyflow/react`），provenance DAG 与 RELATIONS 复用（M1b 定）
- [x] proto → TS 代码生成 → **本地插件 + 产物不入库**（`@bufbuild/protoc-gen-es`）（M1b 定）
- [ ] server 监听端口（前端 `transport` 暂用 8787；与 CLI `ui` 的 8765 区分）→ M1c-1 定
- [ ] Docker runtime 的镜像来源与构建归属（server 仓内构建 vs 独立镜像）
- [ ] HITL Gate 的默认范围与配置粒度（三个 Gate 是否可逐项开关；`auto` 是否支持 per-gate）
- [ ] Worker 并发数 N 的默认值与上限（真线程并发，Dispatcher 确定性提交；受预算约束）
- [ ] 关系样例 fixture 来源（新增含多个组织的样例 vs 复用 `copilot_productivity`）
- [ ] 实体消歧粒度：同名/别名归一的规范化规则（大小写、全称/简称、去空白）
- [ ] CLI `capabilities install-obscura` 命名：旧 `obscura_kitesurf` 占位样例已被从零构建的
      `copilot_productivity` 替换，该命令名（`product-overview.md` §5 冻结契约）语义脱节；
      是否改名留待 M3 决定

## 已知风险 / 缺口

- 前端 `frontend/` 已入库（M1b 脚手架），但**尚无真实数据**（不接 mock）：DAG/Gate UI 与
  server 接线归 M1c-2；在此之前 UI 只是可维护的界面壳。
- `Makefile` 的 `demo` target 依赖 M4 的 server + 前端，现阶段只打印提示（不执行）。
- 样例的真实数据具时效性：离线可复现的对象是 `examples/copilot_productivity/` 的**录制快照**，
  不保证重新联网再跑一遍结果一致。
- **契约重排**把 server API 与前端从 M4 提前到 **M1b/M1c-1/M1c-2**，M4 收缩为端到端 / Deployment / 文档回归；
  期间 `dashboard.md §4` 已由 REST 改为 proto，`product-overview.md §5` 已移除 `trace`。
- **契约-代码漂移（M5 范围，未实现）**：`Entity`/`Relation`/`EntityGraph`、`ENTITY`/`RELATION`
  事件、`Intent.extract`/`relate`、`CreateRun.analysis` 已在 `overview/` + `proto/` 冻结契约中，
  但 `model.py` / `events.py` / `reduce.py` / server 尚未实现（归 M5）。
- M0b 遗留（review 判定非阻塞，可后补）：异常层次未完全收口（`LocalPrompt` 的
  `FileNotFoundError`、`cache.read` 的坏 JSON）、`capabilities list` 的 `ready` 文案在 M3 前有歧义、
  cache 写入非原子、`max_wall` 未做 duration 校验、部分 provider 分支测试缺失。

## 已完成（近期）

- **M1c 拆分**：原 M1c（server + 前后端接线）拆为 **M1c-1（server 骨架，依赖 M1）** 与
  **M1c-2（前端接线与 UI，依赖 M1c-1）**；M2 依赖改 M1c-2。决策：server 栈
  Starlette + uvicorn + `connect-python`、持久化 `run.json` + 目录式 `projects`、
  前端 React Query、布局用 proto `Fact.position` + 前端按 `events[]` 步进。

- **M1b 前端脚手架**：`frontend/`（pnpm + Vite 8 + React 19 + TS strict）入库；Swiss/Blueprint
  主题 tokens（浅/深）、三栏布局 + 路由 + GRAPH/FACTS/INTENTS/EVENTS 页签空态、React Flow 空画布、
  Connect TS 生成接入（`frontend/buf.gen.yaml` + `protoc-gen-es`，产物不入库）、ESLint/Prettier/Vitest；
  `Makefile` 前端 targets；CI 拆为 `python` / `proto` / `frontend` 三个 job。验收：
  `typecheck` / `lint` / `test` / `build` / `buf lint proto` 全绿，页面无 mock。

- **M1b/M1c 拆分**：原 M1b 拆为 **M1b（前端脚手架，依赖 M0d，可与 M1 并行）** 与
  **M1c（server 骨架 + 前后端接线，依赖 M1 + M1b；后又在「M1c 拆分」中拆为 M1c-1/M1c-2）**。
  前端栈定为 pnpm + Vite + React + TS + React Flow + Connect，TS 生成走本地插件、产物不入库。

- **契约重排 + proto 骨架**：`milestones.md` / `SPEC.md` 增 **M1b**（proto + server + 前端；
  后在「M1b/M1c 拆分」中拆为前端脚手架与 server 接线），
  M4 收缩；`dashboard.md §4` REST → **Connect proto**；`product-overview.md §5` 移除 CLI `trace`
  （起 run 走 server/proto）；`agent-design.md §2` 增 `model` capability；新增
  `proto/originweave/v1/originweave.proto` + `buf.yaml` / `buf.gen.yaml`；`cli.py` 移除 `trace`。

- **M0d 离线样例**：`examples/copilot_productivity/`（资料 A + 两个一手来源冻结快照 +
  录制的 `capabilities/**` + `events.jsonl`）；`scripts/build_sample_fixtures.py` 确定性生成
  事件与录制（`--check` 校验产物）；`originweave replay` 离线复现 Board；放宽 `.gitignore`
  放行 `examples/**/*.jsonl`；`Makefile` 区分 `RUN_DIR`（样例）与 `RUNS_DIR`（运行产物）。

- **M5 契约入库**（未实现）：`milestones.md` 增 M5；`SPEC.md` 增 M5 小节；`overview/` 新增
  `Entity`/`Relation`/`EntityGraph`、关系本体表、`ENTITY`/`RELATION` 事件、Intent `extract`/`relate`、
  `CreateRun.analysis`、`Run.analysis` 与 `dashboard` 的 `RELATIONS`/`ENTITIES` 页签、`RunDetail.entity_graph`；
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
