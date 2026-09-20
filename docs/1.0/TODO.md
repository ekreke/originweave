# originweave 1.0 · TODO

滚动待办与已知阻塞。**进度真相在 `SPEC.md`**；本文件只记录跨任务的临时事项、
待确认决策与风险，不重复 SPEC 条目。

## 下一个任务

- **M2 · 偏差记分卡（已完成）**（进度真相见 `SPEC.md` M2；详情见「已完成（近期）」）：
  verify 派发 + compare pass + deviation 记分 + 严格 `COMPLETE` + `report.md` + Gate B。
  **下一步**：**M1c-2b** 前端接线（已拆为 `SPEC.md` 的 **2b-1–2b-5**；**2b-1 / 2b-2 / 2b-3 已完成**，
  下一步 **2b-4** 新建核验表单 + 顶栏）。其后 M3（容器化 runtime）；M6 P3（Settings/Search/Session proto）可并行规划。
- **M6 · Pi Worker、可配置工具与会话**（用户新增；进度真相见 `SPEC.md` M6）。计划 P0–P6：
  - **P0 契约/文档（已完成）**、**P1 Worker 抽象 + 会话 + 事件（已完成）**：`capabilities/worker.py`、
    `Engine(worker=...)`、`[worker]` 配置、`SESSION`/`WORKER_STEP` 事件、run dir `sessions/`。
  - **本轮（仅 docs）**：把「项目级完整化」写入 `SPEC.md` M6 + 本文件（见下）。
  - **下一步 P1b 配置迁移**：退役顶层 `[budget]` → `[worker].budget`；`[worker].provider` 默认 `pi`；
    worker LLM 复用 `[capability.model]`（仅 openai 兼容）。
  - **P2 `PiWorker`**（`capabilities/pi.py`，`pi-py-sdk`，每会话隔离，运行时缺失明确报错，
    Pi turns 计入 `max_steps`，注入 fake 测试）。
  - P3 proto/server（Settings/Search/Session）；**P4 TS 搜索扩展回调 server `Search`**——加载机制
    已 spike 验证（见「已完成（近期）」）；P5 前端 Settings + 会话视图；P6 容器化（并入 M3）。
  - 依赖：P1/P2 不依赖 server；P3–P5 依赖 **M1c-1**。**P2 live 遗留**（配置目录环境变量名硬编码）
    见「已知风险 / 缺口」，P4 接线前须先修。
- **M1 迭代切片**（引擎为库层、进程内 Dispatcher；`model`/`search` provider 已就绪）：
  已落地：**I1** Bootstrap、**I2a** `FAILED`/`STOPPED`、**I2** Reason、**I2b** Validate 去重、
  **I3** Explore + search（来源回链 `citation`/`source` + `Evidence`；`decompose`/`explore`
  派发分支，`verify` 后随 M2 落地；`engine.py`、`prompts/explore.txt`）、
  **I4** 并发派发 + 心跳/超时（`engine.py` `_dispatch`/`_run_explore`/`_heartbeat`；
  `[worker].heartbeat_{interval,timeout,on_timeout}`、`max_concurrency<=16`）、
  **I5** HITL Gate A（`engine.py` `run`/`resume`；`REQUEST_HUMAN`/`HUMAN_INPUT`，`auto` 跳过）、
  **I6** Stigmergy 多轮收敛（`engine.py` `_continue`；`triggerFacts`=新增 facts；`max_rounds` 安全阀）。
  M1 残留（非本轮）：**verify 型调度**随 M2 `compare`（`SPEC:107`）；**进程内 Dispatcher 接口对齐 M3**
  （`SPEC:114`）；**对样例输入的 fake-provider 确定性 Board 单测**（`SPEC:118`，已有 fake-provider
  确定性测试，尚缺「样例输入」覆盖）。
- **M1c-1 · server 骨架（进度真相见 `SPEC.md` M1c-1）**：
  - **C1 codegen + Connect app 骨架（已完成）**：依赖 `connect-python`/`protoc-gen-connect-python`/`protobuf`/
    `starlette`/`uvicorn`；`buf generate proto` → **`src/originweave/v1`**（`originweave.v1.*`，不入库）；
    `server/app.py`/`server/service.py`（`create_app`，`ListProjects` 空表，其余继承 `UNIMPLEMENTED`）；
    CI python job 先生成；`tests/test_server.py` ASGI smoke。
  - **C2 持久化（已完成）**：`persistence.py`（`Run`/`Project`、`allocate_run_id`、`summarize_run`、
    `ProjectRegistry`）；`store.py` 增 `run.json` IO；`config.py` 增 `[project].dir`（默认 `projects`）。
    `run.json` 只存**静态元数据**（结果一律由 `events.jsonl` 派生）；目录式 `projects/<id>/project.json`。
  - **C3a 只读接线（已完成）**：`server/context.py`（`ServerContext`/`Providers`，`create_app(config/providers/root)`）、
    `server/convert.py`（领域/事件 → proto）、`service.py` 实现 5 个只读 RPC（`NOT_FOUND`）。
  - **C3b 写 RPC（已完成）**：`CreateRun{source_text}`（校验 project 存在 / `source_type=text` /
    非空 `source_text` / `goal`；`input/document.md` + `input/source.json` + `run.json`；后台
    asyncio 任务跑 `Engine.run`，返回前等 `PROJECT` 落盘 → 返回事件派生的 `running` `Run`）、
    `AddHint`→`HINT`、`SubmitHumanInput`→新建 `Engine` 调 `resume`。`server/context.py` 增
    `RunScheduler`（每 run 单例 `RunStore` + 后台任务持有/`wait`/`drain`）。
  - **C4 `originweave ui`（已完成）**：`create_app` 把 Connect 挂到 proto path、SPA 静态挂 `/`
    （`index.html` 回退），lifespan 收尾 `scheduler.drain()`；`cli._cmd_ui` 起 uvicorn（`frontend/dist`
    存在即托管），`--run <dir>` 单 run 只读（`ServerContext.pinned_run`）。前端 `transport` 默认
    端口改 8765。Makefile/README/docs 同步。
  - **下一步 M1c-2b**（已拆为 `SPEC.md` 的 **2b-1–2b-5**；**2b-1 / 2b-2 / 2b-3 已完成**，下一步 **2b-4**）：
    **2b-1**（已完成）数据层 + 只读接线（`@tanstack/react-query`、`QueryClientProvider`、`api/hooks.ts`
    的 `useProjects`/`useProjectRuns`/`useRun`、`Overview`/`Project`/`AppShell`/`Console` 接真实数据 +
    `awaiting_human` 轮询、`transport` 默认同源）；**2b-2**（已完成）INSPECTOR 选中联动 + Hints
    （`useAddHint`；`Console.resolveSelection` 含 `origin`/`goal`；FACTS/INTENTS 行选中）；
    **2b-3**（已完成）HITL UI（Gate A/B → `submitHumanInput`）+ Replay 步进；**2b-4** 新建核验表单 + 顶栏；
    **2b-5** 端到端 + 冒烟 + CI/文档。**M6 P3**（Settings/Search/Session proto + RPC）亦依赖 M1c-1，可并行规划。
  - 已定：proto 加 `source_text`（`url` 暂不支持）；目录式 projects；`CreateRun` 后台调度；统一端口 `8765`。
- 随后：M1c-2（前端接线与 UI）。

## 待确认决策

- [x] 配置文件的默认格式与落盘位置（`init` 产物）→ 项目内 `originweave.toml`（M0b 定）
- [x] `search` / `prompt` 的 provider 凭据管理方式 → 仅环境变量（M0b 定）
- [x] ~~capability 录制格式~~ → **已撤销**（Phase R：能力改为真实调用，无 cache/录制）
- [x] run dir 的默认根目录 → server 写 `runs/`（gitignored，`Makefile` 的 `RUNS_DIR`），
  `replay`/`ui` 读已入库的样例目录（`RUN_DIR`）（M0d 定）
- [x] server 持久化布局 → `runs/<run_id>/run.json` + 目录式 `projects/<project_id>/project.json`，
  projects 根用新配置 `[project].dir`（默认 `projects`；**C2 已落地**）；`run_00N` 全局分配（M1c-1 定）
- [x] `CreateRun` 的资料 A 输入 → proto 新增 `CreateRunRequest.source_text`（`source_type="text"`）；
  `url` 暂不支持（M1c-1 定）
- [x] 起 run 的入口 → **无 CLI `trace`**，走 server / proto `CreateRun`（契约重排定）
- [x] proto 方案 → **Connect / buf**，契约 `proto/originweave/v1/*.proto`（契约重排定）
- [x] 前端 → **React + Vite + `@connectrpc/connect-web`**，直连 proto、无 mock（契约重排定）
- [x] OODA 的模型抽象 → `model` capability，**真实 OpenAI 兼容 provider**（Phase R 定；原「录制/回放」已撤销）
- [x] 在线/离线 → **移除离线/录制**（`LIVE`/cache/`Recording*`/`Cached*`）；能力永远真实调用；
  `replay` 只重放事件日志（Phase R 定）
- [x] `[capability.model]` 默认 → `provider="openai"`、`model="deepseek-v4.1-flash"`、
  `base_url=""`（**端点由 `OPENAI_BASE_URL` 提供，内网地址不入库**）；凭据 `OPENAI_API_KEY`（Phase R 定）
- [x] 前端包管理/工具链 → **pnpm + Vite + React + TS**，ESLint + Prettier + Vitest（M1b 定）
- [x] 图渲染库 → **React Flow**（`@xyflow/react`），provenance DAG 与 RELATIONS 复用（M1b 定）
- [x] proto → TS 代码生成 → **本地插件 + 产物不入库**（`@bufbuild/protoc-gen-es`）（M1b 定）
- [x] Reason 产出 Intent 的去重 → **独立 `Validate` pass（第 4 种任务指令，复用 `model`）**：
  **纯 LLM 语义判重**（不做 L1 结构预筛）；比对范围含 `open/claimed/done/dropped` 及**批内候选**；
  判重项写成 `status=dropped` 的 Intent 留痕（新字段 `Intent.duplicateOf`，可空）；每个候选必须恰好
  keep/drop 一次；validator 非法/失败 → 写 `FAILED` 并 graceful 停止。**已于 I2b 落地**（每轮 Reason
  多一次模型调用）。契约变更：`Intent.duplicateOf`（proto `duplicate_of` + 前端重生成）+ 新增
  `VALIDATE` 事件（`events.py` + §5）。
- [x] 失败/停止如何落盘 → **新增事件 `FAILED` / `STOPPED`（现在加）**：reducer 置 `status=failed|stopped`；
  `paused` 仍无事件，随 M3 可控性。落 **I2a**。
- [x] server 监听端口 → **Connect API 与静态统一 `8765`**（前端 `transport` 默认改指它，属 M1c-2/C4）（M1c-1 定）
- [ ] Docker runtime 的镜像来源与构建归属（server 仓内构建 vs 独立镜像）
- [x] HITL Gate A 触发点与语义 → **Bootstrap 之后、Reason 之前**（先确认 main-claim 再拆解；
  非 auto 时即使 Bootstrap 没抽出 main-claim 也照常挂起，不静默绕过）。原协议「decompose 之后确认
  拆解树」改为后续 Gate/切片再评估；`edit` 目前仅记录（`text`/`targets` 入 `HUMAN_INPUT`），
  修改 Fact 需契约新增「事实取代」事件（I5 定）
- [x] Stigmergy 收敛语义（I6 定）→ 终止于 `COMPLETE` / 死胡同（无可派发 Intent）/ 本轮无新 Fact；
  死胡同与安全阀命中均保持 `running`（不写终态）；`REASON.triggerFacts` = 自上次 Reason 的新增 facts；
  安全阀 `Engine(max_rounds=…)` 默认 **10**，真正预算 `STOPPED` 归 M3
- [ ] HITL Gate 的默认范围与配置粒度（三个 Gate 是否可逐项开关；`auto` 是否支持 per-gate）→
  本轮（I5）维持**全局 `[hitl].auto`**；per-gate 开关待 Gate B/C（M2/M3）再评估
- [x] Worker 并发上限的位置与默认值 → 独立 `[worker].max_concurrency`（默认 1，代码校验 `>0`）（M6 定）
- [x] Worker 并发上限的**具体上限** → 固定上界 `MAX_WORKER_CONCURRENCY=16`（I4 定；
  `max_concurrency` 需 `>0 且 <=16`）
- [x] 单次调用心跳/超时的配置与策略 → `[worker].heartbeat_interval`（默认 `"15s"`）/
  `heartbeat_timeout`（默认 `"5m"`，须 `> interval`）/ `heartbeat_on_timeout`
  （`release` 默认 | `fail`）；引擎代发 `HEARTBEAT`，超时按策略写 `RELEASE` 或 `FAILED`（I4 定）
- [ ] 关系样例 fixture 来源（新增含多个组织的样例 vs 复用 `copilot_productivity`）
- [ ] 实体消歧粒度：同名/别名归一的规范化规则（大小写、全称/简称、去空白）
- [ ] CLI `capabilities install-obscura` 命名：旧 `obscura_kitesurf` 占位样例已被从零构建的
      `copilot_productivity` 替换，该命令名（`product-overview.md` §5 冻结契约）语义脱节；
      是否改名留待 M3 决定
- [ ] **M6 P4** server URL 传递：worker 如何得知 server 地址（env `ORIGINWEAVE_SERVER_URL` 默认
      `http://127.0.0.1:8765`，vs 落 `[worker]`/`[server]` 配置）；未设置且启用 `search` 时明确报错
- [ ] **M6 P4** 扩展文件位置与 TS 测试宿主：`runtime/pi-extensions/`（独立于 `frontend/`）；TS 测试
      用新建 vitest 还是仅在 Python 侧断言「工具已注册/被调用」
- [ ] **M6 P4** `explore` 检索归属：维持引擎预取（`engine.py` 调 `search` 经 `extra` 注入）还是改由
      Pi 的 `search` 工具自主检索（影响 Evidence 可审计性与是否双重检索）

### M6 决策（均已定，2026-09）

- [x] Worker 执行体 → **可插拔 `Worker`**，`[worker].provider = local | pi`（方案 B：Worker 一等概念）
- [x] Pi 包 → **`pi-py-sdk`**（驱动官方 TS agent 运行时；运行时需 Node + `pi` 二进制；alpha）
- [x] Pi 工具 → **开启且可配置**（`[worker].tools`），设置页可改；默认建议只读 + `cwd` 沙箱
- [x] 检索 → Pi 侧 TS 扩展执行，**回调 server `Search` RPC**（provider 选择留 Python，保红线 4）
- [x] 设置存储 → 项目 `originweave.toml`，独立 **`[worker]`** 表（含 `max_concurrency`）
- [x] 会话 → 每次 Worker 调用一个**隔离会话**；原始 input/output 落 `sessions/<id>.json`，
      `SESSION` 事件做轻量索引；**保留 `WORKER_STEP` 事件**（turn/tool 级，`text` 截断）
- [x] 里程碑 → 新增 **M6**（P1/P2 不依赖 server；P3–P5 依赖 M1c-1；P6 并入 M3）
- [x] Worker 的 **LLM 配置** → **复用 `[capability.model]`**（单一来源）；仅 **openai 兼容**：
      `model` + `base_url`（端点走 `OPENAI_BASE_URL`）+ `OPENAI_API_KEY`（env，设置页不落密钥）
- [x] 预算 → **退役顶层 `[budget]`，迁至 `[worker].budget`**（`max_steps`/`max_wall`/`max_cost`；
      补 `max_wall` 时长校验）；`CreateRunRequest` 的三个预算字段语义改为**覆盖 `[worker].budget`**
- [x] 默认 provider → **`pi`**（`local` 保留为可选）
- [x] 运行时缺失 → **明确报错 + 安装指引**（Node + `pi` 二进制），不静默降级为 `local`
- [x] Pi 会话 turns → **计入 `max_steps`**，单会话受 `[worker].budget` 约束（P2 落地）

## 已知风险 / 缺口

- **M1c-1 C3b**：`SubmitHumanInput` 目前**同步 await** 整个续跑周期（Reason→dispatch 可能数秒~数十秒），
  与 SPEC 字面一致但会阻塞该 RPC；若需非阻塞可后续改为后台任务 + 前端轮询。同因，客户端取消该请求会让
  `CancelledError` 穿透 `_continue`，可能停在「Intent 已 `claimed` 无终态」的中间态（完整恢复归 M3）。
  后台引擎若在写 `FAILED` 前抛异常（设计上不应发生），run 会停在 `running`（`RunScheduler` 仅记 warning）。
  **单进程/单事件循环前提**：`allocate_run_id` 与 `RunStore` 的内存 `_count` 只在单 loop 下保证 id 唯一；
  `RunScheduler` 持有一个进程内 `RunStore` 表（`Agent` 与 `AddHint` 共用同一实例），C4 起 uvicorn **不得用
  多 worker**，否则重复 id 会破坏「黑板=唯一事实来源」（M3 容器化后再解除）。

- **I6 收敛只按「新 Fact」触发重跑**：被 `RELEASE` 退回 `open` 的 Intent 不会单独重派（无新 Fact 时
  循环即停）；完整的 Intent 重试/调度归 M3。进度判据目前只看 `facts`，M5 引入 `entities`/`relations`
  后需一并纳入。
- 能力调用**不再可复现**：live run（真实 model/search）两次结论可能不同；「可重放」仅靠
  `events.jsonl` 事件日志成立。
- 测试/CI 不打真网 → provider 测试**必须注入 fake**（`httpx.MockTransport`）；live 冒烟需凭据，CI 跳过。
- 免费搜索走第三方公开 MCP 端点（`mcp.exa.ai` / `search.parallel.ai`），可能限流或变更；
  已兼容普通 JSON 与 SSE 两种响应。
- 旧 `originweave.toml`（含 `[live]`）会因未知键报错（仓库无提交的 toml，影响小）。
- 前端 `frontend/` 已入库（M1b 脚手架），但**尚无真实数据**（不接 mock）：DAG/Gate UI 与
  server 接线归 M1c-2；在此之前 UI 只是可维护的界面壳。
- `Makefile` 的 `demo` target 依赖 M4 的 server + 前端，现阶段只打印提示（不执行）。
- **契约重排**把 server API 与前端从 M4 提前到 **M1b/M1c-1/M1c-2**，M4 收缩为端到端 / Deployment / 文档回归；
  期间 `dashboard.md §4` 已由 REST 改为 proto，`product-overview.md §5` 已移除 `trace`。
- **契约-代码漂移（M5 范围，未实现）**：`Entity`/`Relation`/`EntityGraph`、`ENTITY`/`RELATION`
  事件、`Intent.extract`/`relate`、`CreateRun.analysis` 已在 `overview/` + `proto/` 冻结契约中，
  但 `blackboard.py` / `events.py` / `reduce.py` / server 尚未实现（归 M5）。
- **枚举定义双份**（`blackboard.py`）：`Literal` 别名（`FactKind` 等）与 `frozenset` 校验集
  （`FACT_KINDS` 等）各写一遍、靠人工同步；且 dataclass 字段仍是 `str`、未用 `Literal` 标注，
  mypy 静态检查未生效。可选收口：字段改用别名标注，或从 `Literal` 派生集合（`typing.get_args`）。
- M0b 遗留（review 判定非阻塞，可后补）：异常层次未完全收口（`LocalPrompt` 的
  `FileNotFoundError`）、`max_wall` 未做 duration 校验。（原 cache 相关遗留随 Phase R 撤销。）

- **M6 风险**：`pi-py-sdk` 为 alpha 且运行时需 Node + `pi`（CI 只能注入 fake，live 依赖 runtime 镜像）；
  **默认切 `pi` 后**，无 Node/`pi` 的环境将直接报错（不再开箱即用，须给出安装指引）；
  Pi 输出需严格 JSON（工具开启后更易夹带散文，可能需一次 repair retry）；`bash/write/edit` 是真实
  写入/执行面（须 `cwd` 沙箱 + 白名单，默认只读 + 检索走扩展）；Pi 内部轮次需计入 `max_steps`（P2）；
  **`[worker].budget` 目前只是配置，尚未强制执行**（enforcement 归 M3）；
  `sessions/` 原始输入**不得写入任何凭据**；`WORKER_STEP` 需 `text` 截断常量防事件膨胀。
- **M6 P2 live bug（P4 接线前须修）**：`capabilities/pi.py` 把 Pi 的 agent 配置目录环境变量硬编码为
  `PI_CODING_AGENT_DIR`，但该变量名由 pi 构建的 `piConfig.name` 决定（`<NAME>_CODING_AGENT_DIR`）。
  本机安装 `piConfig.name="ekreke"`，实际读 `EKREKE_CODING_AGENT_DIR`。spike 实测：硬编码名下
  `models.json` 不加载，报 `Unknown provider "originweave-openai"`（P2 测试注入 fake agent，故未暴露）。
  修法：按 `pi` 二进制推导 `<NAME>_CODING_AGENT_DIR`，或同时设置候选键，并在 `_require_runtime()`
  加一条真实冒烟。
- **`[budget]` 退役的迁移影响**：顶层 `[budget]` 迁到 `[worker].budget` 后，含 `[budget]` 的旧
  `originweave.toml` 会因未知键报错（仓库无提交的 toml，影响小，类比 Phase R 去 `[live]`）；
  `CreateRunRequest` 的 `max_steps`/`max_wall`/`max_cost` 结构不变，但语义改为覆盖 `[worker].budget`，
  需同步 `dashboard.md §4.3` 与 `agent-design.md §2.1/§4`（P1b）。
  review 遗留（低优先）：`runId = store.root.name` 在 root 为 `.` 时为空；`[worker].tools` 允许重复项；
  `_session_seq` 每次 `run()` 重置——同一 store 多次 run 仍会覆盖会话、重发 id（未随 I4 处理）。
  （I4 已把并发下的 session id 改为在 `await` 前按序分配、Explore 用 `worker-{n}` 标签，取代硬编码
  `WORKER_ID`。）

## 已完成（近期）

- **M1c-2b 2b-3 · HITL UI + Replay 步进**：INSPECTOR 抽出 `GateCard`（修正说明输入 + pending 禁用 +
  失败行内报错），`Console` 经 `useSubmitHumanInput`（`SubmitHumanInput` + invalidate `['run',runId]`）
  提交 `{gate, decision, text}`；Gate A/B 通用渲染，Gate C 随 M3。Replay：`graph/replay.ts` 的
  `firstSeenAt` 从 `events[]` 派生节点首现序号（不改 server、不复刻 reducer）；
  `mapping.runDetailToGraph(detail, visibleIds)` 过滤图（锚点恒显、悬空边剔除），`EventsTab` 按 `step`
  截断/高亮；Console 中栏 ◀/▶/live 控件，步进按 run 隔离。测试 `graph/replay.test.ts`（首现/可见集）、
  `mapping.test.ts`（过滤 + 悬空边）、`tabs.test.tsx`（截断高亮）、`routes.test.tsx`（Gate 提交/错误、
  replay 走位/过滤）、`hooks.test.ts`（`useSubmitHumanInput`）。前端
  `typecheck`/`lint`/`format:check`/`test`(56)/`build` 全绿；`originweave ui` 冒烟（只读模式写 RPC 正确 400）。
  经 subagent review（无 blocker；已修跨 run replay 泄漏 + 补过滤路径测试）。

- **M1c-2b 2b-2 · INSPECTOR 交互（选中联动 + Hints）**：`Console` 加 `resolveSelection`（`origin`/`goal`
  锚点优先、`intents` 兜底、未命中 `null`）+ **带 runId 标记的选中态**（跨 run 自动失效，避免同 id 碰撞）；
  `GraphTab` `onSelect` + `FactsTab`/`IntentsTab` 行 `onSelect`（行键盘可达 Enter/Space + `selected-row`
  高亮、`selectedId`）→ `Inspector` 详情；`api/hooks.ts` 加 `useAddHint`（`AddHint` mutation + invalidate
  `['run', runId]`；空 `runId` 抛错）；`Inspector` 加 `hints`/`onAddHint` + `HintsPanel`（受控输入、Enter
  提交、**IME 组合态守卫**、失败保留文本 + 内联错误、pending 防重入；无 hints 且无 handler 时不渲染）。
  `presentation.css` 加 `.selectable-row`/`.selected-row`/`.hints*`。测试 `routes.test.tsx`（图节点/FACTS/
  INTENTS 选中 → Inspector、Hint 提交）、`layout.test.tsx`（提交清空 / IME / 失败保留 / 无 handler 禁用）、
  `hooks.test.ts`（`useAddHint` 入参 + invalidate）。前端 `typecheck`/`lint`/`format:check`/`test`/`build` 全绿。
  经 subagent review（无 blocker；worktree 与 develop 两份实现已按「worktree 为底 + 补回 develop 的
  IME/失败重试/空 runId 抛错」合并）。

- **M1c-2b 2b-1 · 数据层 + 只读接线**：前端加 `@tanstack/react-query`（`api/queryClient.ts` +
  `main.tsx` 的 `QueryClientProvider`），`api/hooks.ts` 提供 `useProjects`/`useProjectRuns`/`useRun`
  （`awaiting_human` 轮询，判据抽为纯函数 `awaitingPollInterval`）；`Overview`（项目列表）、
  `Project`（run 列表）、`AppShell`（项目导航 + LIVE/OFFLINE）、`Console`（`RunList` + 四页签 +
  `Inspector` 计数）接真实数据，保留 loading/error/`NOT_FOUND`/空态（`Console` 区分 `Code.NotFound`
  与连接错误；`RunList` 增 `loading`/`error` 三态）。`transport` 默认改**同源**
  （`window.location.origin`，免 CORS；`VITE_API_BASE` 覆盖 dev）。测试：`test/providers.tsx`
  （独立 QueryClient、禁 retry）+ `App.test.tsx`/`routes.test.tsx`/`api/hooks.test.ts`（mock
  `@/api/client`，断言 RPC 入参、NOT_FOUND/错误、LIVE/OFFLINE）。文档同步 `dashboard.md §1`、
  `AGENTS.md`、`README.md`、`SPEC.md`（2b-1 勾选）。前端 `typecheck`/`lint`/`test`(32)/`build`/`format:check` 全绿。

- **M2 · 偏差记分卡（路线 B）**：库层新增 `src/originweave/report.py`（`Deviation`/`Report`、
  `parse_severity`、`derive_report`、`render_report`）；`engine.py` —— **verify 型 Intent 派发**
  （`prompts/compare.txt`、不检索、`_check_verified_facts` 校验 compare/deviation）、**语义边**
  （reply `edges` + `key` 引用同批 Fact，`_resolve_edges`；Bootstrap/Explore 携带，Reason/Validate
  携带即失败）、**严格 `COMPLETE`**（`_goal_satisfied`：论点全拆解、子断言回链或 `open`、已有
  compare，否则 Reason 的 complete 被忽略）、**Gate B**（reply `gate` → `REQUEST_HUMAN{arbitrate}`；
  `resume` 放行 `arbitrate`）；`store.write_report` 落 `report.md`（派生物，`replay` 不重写）；server
  `convert.py` 填 `RunDetail.report`/`deviations`、`service.py` 放行 `arbitrate`。**契约**：
  `blackboard-protocol §4.2`（reply `key`/`edges`/`gate`）、`§2.4`（语义边来源）、`§7`（Gate B）；
  `agent-design §3.5`。测试 `tests/test_engine_m2.py`、`tests/test_report.py`、`tests/test_server.py`；
  顺带修 live 的语义边漂移（Bootstrap `origin→claim` main-chain、Explore cite/link/evidence）。
- **M1c-1 C4 · `originweave ui` + 静态托管**：`server/app.py` 的 `create_app` 增
  `static_dir`/`run_dir`——Connect app 改挂 proto path（`OriginweaveServiceASGIApplication.path`），
  `SPAStaticFiles`（`index.html` 回退）挂 `/`，`lifespan` shutdown 时 `await scheduler.drain()`；
  `ServerContext` 增 `pinned_run`（`build(run_dir=...)`）；`service.py` 单 run 只读模式
  （`get_run`/`list_*` 只服务 pinned run，写 RPC → `FAILED_PRECONDITION`）。`cli._cmd_ui` 起
  `uvicorn`（`frontend/dist` 存在即托管，`--run` 进只读模式）。前端 `transport.ts` 默认端口
  8787 → 8765。文档同步 `README.md` / `product-overview.md §5` / `agent-design.md §6` /
  `dashboard.md §1` / `AGENTS.md`。测试 `tests/test_server.py` 增静态/SPA、pinned 只读、lifespan
  收尾、`ui` CLI 冒烟。`make lint` + `make test` 全绿。

- **M1c-1 C3b · CreateRun + 后台调度 + AddHint/SubmitHumanInput**：`server/service.py` 实现
  `create_run`（project 必须已存在；`source_type=text` + 非空 `source_text` + `goal`，否则
  `INVALID_ARGUMENT`；`analysis` 仅 `provenance`；资料 A 正文写 `input/document.md`（+ `source.json`）、
  静态元数据写 `run.json`（含 budget 覆盖与 `auto`）；构造 `origin`（正文入 `note`）/`goal` Fact，
  起后台任务跑 `Engine.run`，有界等到 `PROJECT` 落盘后返回事件派生的 `running` `Run`）、
  `add_hint`（`HINT`，`h{N}` 按现有 HINT 计数）、`submit_human_input`（非 `awaiting_human` →
  `FAILED_PRECONDITION`；gate 不符/未知 decision → `INVALID_ARGUMENT`；新建 `Engine` 调 `resume`）。
  `server/context.py` 增 `RunScheduler`（每 run 单例 `RunStore`——避免多实例 `append_event` 的 event id
  冲突；后台任务持有 + `wait`/`drain`）与 `ServerContext.scheduler`；`store.py` 增 `write_input()`。
  顺带修正 `_lookup_project` 中 `BlackboardError`（`ValueError` 子类）不可达的 except 顺序。
  契约同步 `dashboard.md §4.3`。测试 `tests/test_server.py` 增 C3b 用例（注入 fake provider）。
  `make lint` + `make test`（266 passed, 1 skipped）+ `make replay` 全绿。

- **M1c-1 C3a · DI + 只读 RPC + proto 映射**：新增 `server/context.py`（`Providers` 与 `ServerContext`，
  从 config 构建 `build_worker/search/prompt`；`create_app(config/providers/root/service)` 注入）、
  `server/convert.py`（`Board`/`Run`/`Project`/`Event`/`Hint` 等 → `originweave.v1.*`；`Event.payload`
  经 `json_format.ParseDict` 落 `Struct`；`Intent.from` 用映射 splat 绕过 Python 关键字）。
  `service.py` 实现 `ListProjects`/`GetProject`/`ListProjectRuns`/`ListRuns`/`GetRun`
  （`RunStore`→`reduce()`→`RunDetail`；缺失 → Connect `NOT_FOUND`）。mypy 补 `google.protobuf.*`
  override（无 stubs）。测试 `tests/test_server.py` 扩展（只读路径 + `root=tmp` 隔离 + 注入）。
  `make lint` + `make test`（259 passed, 1 skipped）+ fixture `--check` + `make replay` 全绿。

- **M6 P4 · T1 Pi TS 扩展加载 spike（调研，无仓库改动）**：在临时目录（`pi` 0.84.4 + Node，本地
  stub，零真实模型/网络）验证了 P4 的关键机制——① 仓库外 `.ts` 经 `pi --no-extensions -e <path>`
  可由 jiti 加载（`--no-extensions` 仅关自动发现，显式 `-e` 仍生效，且无需 `--approve`）；
  ② `typebox` 与 `@earendil-works/pi-coding-agent` 类型在扩展路径可直接 import，**无需
  `package.json`/shim**；③ `--tools search` 按精确名启用扩展工具、`--no-tools` 关闭
  （`getAllTools`/`getActiveTools` 同步反映）；④ 扩展可见 `PiConfig.env` 注入的
  `ORIGINWEAVE_SERVER_URL`，Node 全局 `fetch` 回调 `POST .../OriginweaveService/Search`
  （body `{query,numResults}`）成功；⑤ 模型→工具→回调全链路可跑通，stdout 的
  `tool_execution_start/end`（`toolName:"search"`）正是 `PiWorker._append_step` 消费的
  `ToolExecutionStartEvent/EndEvent`，**投影逻辑无需改**。免模型验证法（RPC + 扩展命令）可复用为
  P4 的 CI 测试形态。**顺带定位 P2 live bug**（配置目录环境变量名，见「已知风险 / 缺口」）。

- **M1c-1 C2 · 持久化**：新增 `src/originweave/persistence.py`——`Run`/`Project` 领域模型（对齐 proto）、
  `allocate_run_id`（全局 `run_00N`）、`summarize_run`（静态字段取 `run.json`，其余一律由 `events.jsonl`
  + `reduce()` 派生；无 `run.json` 的样例目录也能服务）、`ProjectRegistry`（目录式
  `projects/<id>/project.json`，`run_count`/`updated_at` 读取时派生、不落盘）。`store.py` 增
  `run_json_path`/`read_run_meta`/`write_run_meta`（**不改 `init_layout`**，样例 fixture 不受影响）；
  `config.py` 增 `[project].dir`（默认 `projects`）。**`run.json` 只存静态/输入元数据**（资料 A 正文在
  `input/`），结果面每次由事件现算。契约同步 `agent-design §2.1/§5`、`AGENTS.md`。测试
  `tests/test_persistence.py`（新增）+ `test_config.py`（`[project]`）。`make lint` + `make test`
  （251 passed, 1 skipped）+ fixture `--check` + `make replay` 全绿。

- **M1c-1 C1 · Python codegen + Connect app 骨架**：依赖加 `connect-python==0.9.0`、
  `protoc-gen-connect-python==0.9.0`、`protobuf`、`starlette`、`uvicorn`；`make proto` 带 `.venv/bin` PATH
  跑 `buf generate proto`。**生成物落在 `src/originweave/v1`（`originweave.v1.*`）**——proto 文件路径决定
  模块名，而 `protoc-gen-connect-python` 硬编码 `import originweave.v1.originweave_pb2`，故 `out: src`
  （原计划的 `gen/` 目录与包名 `originweave` 冲突），sync `.gitignore`/ruff/mypy。新增
  `server/app.py`（`create_app`：Starlette 挂载 Connect ASGI app）与 `server/service.py`
  （`Service(OriginweaveService)`：`list_projects` 返回空表，其余继承 `UNIMPLEMENTED`）；mypy override
  `originweave.v1.*`（`follow_imports=skip`）；`protobuf>=7.36.1`（匹配 gencode）；hatch
  `artifacts` 强制把生成树打进 wheel（否则 server 包在安装后损坏）。CI python job 加 buf-setup +
  `make proto`（三个 job 的 buf 统一 `1.70.0`）。测试 `tests/test_server.py`（ASGI smoke + 注入 +
  未实现 501，无 gen 时 `importorskip`）。`buf lint proto` + `make lint` + `make test`
  （232 passed, 1 skipped）全绿，wheel 内含 `originweave/v1/*`。

- **M1 I6 · Stigmergy 多轮收敛**：`engine.py` `_continue` 改为循环——每轮 Reason→dispatch 后，若产生了
  **新 Fact** 就对新增 facts 再跑 Reason（`REASON.start.triggerFacts` 只记自上次以来的新增 facts），
  直至 Reason 写 `COMPLETE`（→ `completed`）、死胡同（无可派发的 `open` Intent，如仅 `verify`）或本轮
  无新 Fact。新增 `Engine(max_rounds=…，默认 10)` 安全阀，命中/死胡同均保持 `running`（无终态事件；
  真正预算 `STOPPED` 归 M3）。确定性：跨轮 id 续号、每轮按 id 序提交、`triggerFacts` 确定。
  契约同步 `blackboard-protocol §4.2/§4.4`、`agent-design §3.5`。`make lint` + `make test`
  （229 passed, 1 skipped）全绿，`make replay` 不变。

- **M1 I5 · HITL Gate A（挂起/恢复）**：`engine.py` 增 `auto`（默认 `False`，产品默认人工介入）与
  `GATE_A="confirm-claim"`。`run(origin, goal, auto=None)` 在 Bootstrap 后、Reason 之前，非 auto 时
  写 `REQUEST_HUMAN{gate, question}` 并返回 `awaiting_human` 的 Board（即使未抽出 main-claim 也挂起，
  不静默绕过）；`run(auto=True)` / 构造 `auto=True` 跳过。新增 `resume(decision, text?, targets?)`：
  校验当前处于该 gate → 写 `HUMAN_INPUT{author:"human"}` → `approve`/`edit` 继续 Reason→dispatch
  （`edit` 仅记录，Fact 取代事件待补）、`reject` 写 `STOPPED`。`_restore_counters` 从黑板重建
  `_fact_seq`/`_intent_seq` 并从 `SESSION` 事件的**最大后缀**重建 `_session_seq`，使 resume 可在
  **新 Engine 实例**上正确续号（server 友好）。契约同步 `blackboard-protocol §7`、`agent-design §2.1`；
  样例行 `examples/copilot_productivity/events.jsonl` 的 gate id/decision 已对齐冻结契约
  （`confirm-claim`/`arbitrate`、`approve`/`edit`，`build_sample_fixtures.py` + README + 契约测试）。
  `make lint` + `make test`（223 passed, 1 skipped）全绿，`make replay` 不变。

- **M1 I4 · 并发派发 + 心跳/超时**：`engine.py` 重写 `_dispatch`——一轮内按 id 序统一 `EXECUTE`
  认领（标签 `worker-{n}`），以 `asyncio.Semaphore([worker].max_concurrency)` 并发跑 `_run_explore`
  （不写黑板；每个 pass 经 `_guarded_run_explore` 包裹，任何异常都转成 `_ExploreOutcome` 提交，
  不逃逸、不泄漏兄弟任务），`gather` 后**按 Intent id 序提交** `CONCLUDE`/`SESSION`，故完成顺序
  不影响 Board；首个硬失败写 `FAILED` 并停止提交。`_invoke` 的 session id 改为在 `await` 前按序分配
  （并发确定）。
  **心跳/超时（I4b）**：执行期引擎按 `heartbeat_interval` 代写 `HEARTBEAT`，`asyncio.wait_for`
  按 `heartbeat_timeout` 判定失活（**租约覆盖 search 与 worker 调用**），`heartbeat_on_timeout=release`
  写 `RELEASE`（Intent 回 `open`，本轮继续）/`=fail` 写 `FAILED`。`config.py` 增 `[worker].heartbeat_interval`（`"15s"`）/
  `heartbeat_timeout`（`"5m"`，须 `> interval`）/`heartbeat_on_timeout`（`release`|`fail`）、
  `parse_duration()` 与新上界 `MAX_WORKER_CONCURRENCY=16`；契约同步 `overview/`（`agent-design §2.1/§3.5`、
  `blackboard-protocol §4.2/§8`、`dashboard §4.6`、`product-overview`）。多轮收敛归 I6。
  `make lint` + `make test`（209 passed, 1 skipped）全绿，`make replay` 不变。

- **M1 I3 · Explore + search（来源回链）**：新增任务指令 `Explore`（`prompts/explore.txt`）；
  `engine.py` 增 `_dispatch`/`_run_explore`（I3 时名为 `_explore`，I4 拆分重命名）——`run()` 变为 Bootstrap → Reason → 单轮派发（open 且
  `type∈{explore,decompose}` 的 Intent 按 id 序执行；`verify` 留待 M2）。explore 型由**引擎**调
  `search`（query = intent question），结果与 intent 一起经 `extra` 注入 worker（红线 4）；产出
  `citation`/`source` Fact（引擎强制 `role=none` 且**至少一条** `Evidence`），decompose 型产出
  `sub-claim`；`EXECUTE` 先于能力调用。**错误路径统一**：任何 pass 的非法回复（含 Reason/Bootstrap，
  原为向调用方 raise）与模板缺失均 → 会话留痕 + `FAILED`，不抛异常。多轮 Stigmergy 收敛归 I6，
  多 Worker 并发归 I4。`make lint` + `make test`（186 passed, 1 skipped）全绿，`make replay` 不变。

- **M6 P0/P1 · Worker 抽象与会话**：契约（`[worker]`、`sessions/`、`SESSION`/`WORKER_STEP`、
  `Session` 领域模型、Settings/Search proto 草案）落 `overview/`；代码新增
  `capabilities/worker.py`（`Worker`/`WorkerReply`/`WorkerStep`/`LocalWorker`/`render_messages`），
  `Engine` 改接 `worker` 并把每次调用落为**隔离会话**（`sessions/sess_NNN.json` 存原始输入/输出/步骤，
  `SESSION`/`WORKER_STEP` 事件做索引，reducer 忽略）；`config.py` 增顶层 `[worker]`
  （`provider`/`max_concurrency`/`tools`）；`store.py` 增 `sessions_dir`/`write_session`；
  CLI `capabilities list` 展示 worker。`make lint`（ruff+mypy strict）与 `make test`
  （139 passed, 1 skipped）全绿；`make replay` 样例不变。P2（`PiWorker`）待做。
  经 subagent review 后的加固：worker/provider 异常→`FAILED`（Bootstrap 失败不再进 Reason）、
  会话 id 按调用顺序分配、`SESSION` 先于 `WORKER_STEP`、`event_count()` 去 O(n²)、
  `WORKER_STEP` 端到端测试与失败/负例、proto `Event.type` 注释与文档事实错误修正
  （`WorkerReply{text,input,steps}`、`tools` 扁平白名单、M6 计划项标注）。当前 146 passed。

- **Phase R · 移除离线/录制（代码部分）**：删 `capabilities/cache.py` / `record.py` 与样例
  `capabilities/**`；`config.py` 去 `[live]`/`ORIGINWEAVE_LIVE`、加 `ModelConfig`
  （`openai` / `deepseek-v4.1-flash` / `base_url`）；`capabilities/` 改 `get_*`/`build_*`
  + `MODEL_PROVIDERS`；`search.py` 改为**免费 MCP 端点**（`mcp.exa.ai` / `search.parallel.ai`，
  免 key、可选 key；普通 JSON + SSE 解析，返回文本）；新增 `capabilities/model.py`（OpenAI 兼容，async）；
  `cli.capabilities list` 去 live、加 model；`build_sample_fixtures.py` 只出 `events.jsonl`；
  `Makefile` 去 `LIVE`；依赖加 `httpx`、dev 加 `pytest-asyncio`；测试重写（`httpx.MockTransport`，75 passed）。

- **Phase R · 移除离线/录制（文档部分）**：契约改为「能力真实调用」——`agent-design.md`
  §2/§2.1 去「离线优先」与 `[live]`、删 §2.2「录制与重放布局」、run dir 去 `capabilities/`、
  加 `[capability.model]`（OpenAI 兼容：`deepseek-v4.1-flash`）；`product-overview.md`（可重放
  语义 + 非目标）；`SPEC.md`（M0b/M0d 标注撤销、M1 扩为真实 `model`+`search`、M3 瘦身、
  M1c/M4/M5 去离线、M1 验收改为「`replay` 确定 + live 结构断言」）；`milestones.md`；
  `AGENTS.md` / `README.md`；样例 README。（代码清理见上条「Phase R · 代码部分」。）

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

- **M0d 离线样例**（**Phase R 撤销**样例的 `capabilities/**` 录制；现仅 `input/`+`sources/`+`events.jsonl`）：
  `examples/copilot_productivity/`（资料 A + 两个一手来源冻结快照 +
  录制的 `capabilities/**` + `events.jsonl`）；`scripts/build_sample_fixtures.py` 确定性生成
  事件与录制（`--check` 校验产物）；`originweave replay` 离线复现 Board；放宽 `.gitignore`
  放行 `examples/**/*.jsonl`；`Makefile` 区分 `RUN_DIR`（样例）与 `RUNS_DIR`（运行产物）。

- **M5 契约入库**（未实现）：`milestones.md` 增 M5；`SPEC.md` 增 M5 小节；`overview/` 新增
  `Entity`/`Relation`/`EntityGraph`、关系本体表、`ENTITY`/`RELATION` 事件、Intent `extract`/`relate`、
  `CreateRun.analysis`、`Run.analysis` 与 `dashboard` 的 `RELATIONS`/`ENTITIES` 页签、`RunDetail.entity_graph`；
  `dashboard.md` 新建 run body 的 `mode` 改名 `sourceType` 并新增 `analysis`。

- **M0c 黑板事件日志与事件溯源**：`blackboard.py`（Board/Fact/Intent/Hint/Edge/HumanDecision）、
  `events.py`（`Event` + 11 种 type）、`store.py`（run 目录 + append-only `events.jsonl`）、
  `reduce.py`（纯函数 fold，自动推导 `spawns`/`resolves`/`decomposes`，语义边来自 payload）、
  CLI 接线 `replay`（只读 stdout，`--json`）。63 测试通过，ruff + mypy strict 全绿。
- **M0b 配置与 capability 层骨架**：`config.py`（`originweave.toml`，`tomllib` 读 / `tomli-w` 写，
  未知键报错，`ORIGINWEAVE_LIVE` 覆盖）、`capabilities/`（Protocol + exa/parallel/local/langfuse
  注册表 + 录制/回放 + `build_search`/`build_prompt` 离线-联机接线）、CLI 接线 `init` 与
  `capabilities list`。（**Phase R 撤销**：`ORIGINWEAVE_LIVE`、cache、录制/回放部分。）
- 引入**黑板架构**（参考 Cairn）：新增 `docs/overview/blackboard-protocol.md`，
  重写 `agent-design.md` 的循环为 OODA + Bootstrap/Reason/Explore；领域模型新增
  `Fact/Intent/Hint`、`origin/goal` 特殊 Fact、`Fact.role`、`Intent.type`，事件改为
  黑板协议事件，`Run.status` 增 `awaiting_human`，并加入三个 HITL Gate。
- 补齐 docs-first 事实来源：`milestones.md`、`docs/README.md`、`docs/overview/*`、本文件与 `SPEC.md`。
