# AGENTS.md · originweave

给定资料 A，定位其核心说法的真实源头、判定偏差，产出可审计的溯源 DAG + 偏差记分卡。
**`docs/` 文档用中文；代码标识符、字段名、CLI/事件名保留英文。** 现有代码的 docstring 与
行内注释是英文，跟随时保持一致。

## 事实来源与工作流

- `docs/` 是唯一事实来源；活跃版本 **1.0**（`docs/1.0/SPEC.md`）。开工前先读
  `milestones.md` 定位活跃版本，再读 `docs/1.0/SPEC.md` 确定下一个子任务。
- **进度只写回 SPEC 的 checkbox**（由 `checkpoint` 阶段更新，且必须能指向仓库真实文件）。
  `milestones.md` 的表格只是索引，不要手改其状态。
- 领域模型 / 黑板协议 / proto 契约 / CLI / run dir 布局是**冻结契约**，定义在
  `docs/overview/*` 与 `proto/`；改代码时若动到契约，必须同步改对应文档。
- 本仓库按 `dev-workflow` 流水线推进（progress-tracker → implement → testing-stage →
  checkpoint），每次迭代只推进一个子任务。

## 当前实现状态（别假设业务逻辑已存在）

- 已实现：`originweave init`（写 `originweave.toml`，已存在需 `--force`）、
  `originweave capabilities list`、配置加载/校验、capability 注册表，
  事件日志 → 黑板 reducer → `originweave replay <run-dir>`（只读、不触网），
  以及 **M1 库层 OODA 引擎的 Bootstrap / Reason / Validate / Explore pass**（I1–I3：
  `src/originweave/engine.py`、`prompts/{bootstrap,reason,validate,explore}.txt`）。
- **引擎是库层**：`Engine` 是黑板的**唯一写入者**（事件经 `RunStore.append_event`），
  进程内 Dispatcher 是 M3 容器化前的临时态。**不经 CLI / server 暴露**（server 归 M1c-1）；
  Explore 派发为**单轮**（`verify` 型 Intent 留待 M2 `compare`）。**I4 并发已落地**：一轮内先按
  id 序 `EXECUTE` 认领，再受 `[worker].max_concurrency`（<=16）并发执行、**按 id 序提交**（Board
  确定）；执行期引擎代发 `HEARTBEAT`，超过 `[worker].heartbeat_timeout` 按
  `heartbeat_on_timeout=release|fail` 写 `RELEASE`/`FAILED`。**I5 HITL 已落地**：`Engine(auto=...)`
  非 auto 时 `run` 在 Bootstrap 后写 `REQUEST_HUMAN{gate:"confirm-claim"}` 停在 Gate A，
  `Engine.resume(decision, text?, targets?)` 写 `HUMAN_INPUT` 继续（`reject`→`STOPPED`）或
  `run(auto=True)` 跳过。多轮 Stigmergy 收敛（I6）为后续 M1 切片（见 `docs/1.0/TODO.md`「下一个任务」）。
- **CLI 无 `trace`**：起 run 走 **server / proto API**（`CreateRun`，见 `dashboard.md` §4 与
  `proto/`），编排归 server。CLI 只保留 `init` / `replay` / `ui` / `capabilities` / `mcp`。
- **stub（打印 “not implemented yet”、返回 0）**：`ui` / `mcp` / `capabilities install-obscura`。
  `make demo` / `run` / `ui` 依赖这些实现（`demo` 归 M4，`ui` 归 M1c-1）。
  `replay` 已接线，`examples/copilot_productivity/` 已含 `events.jsonl`（M0d），`make replay`
  可不触网复现 Board。
- 样例 fixture 由 `scripts/build_sample_fixtures.py` 确定性生成（`--check` 校验）；
  改样例事件后要重跑该脚本。资料 A 与来源是**冻结快照**，重新联网结果具时效性。
- **能力为真实调用**（Phase R 已移除离线/cache/录制回放）：`search`（免费 MCP 端点，
  `exa`/`parallel`，**免 key**）、`model`（OpenAI 兼容）与 prompt `local` 已落地；
  prompt `langfuse` 为 M3 前 stub。凭据只从环境变量读、**多为可选**：`EXA_API_KEY` /
  `PARALLEL_API_KEY`（可选，换配额）、`OPENAI_API_KEY`（+ 可选 `OPENAI_BASE_URL`）、
  `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`。
  单元测试**注入 fake provider**（`httpx.MockTransport`），不打真网。
- **prompt 模板在 `prompts/`**（已存在，如 `prompts/bootstrap.txt`）：`local` provider 按
  `[capability.prompt].directory` 读 `<name>.txt|.md`；新增任务指令要同时加模板文件。
- `proto/` 契约已定义；生成代码**不入库**（`buf generate` 产出、**勿手改**）：前端 TS 由
  `pnpm --dir frontend gen`（`frontend/buf.gen.yaml`，落到 `frontend/src/gen/`），
  server Python 归 M1c-1（根 `buf.gen.yaml`）。
- **前端（`fronten*d/`，M1b 脚手架）**：React + Vite + TS + React Flow + Connect；目前是
  **无数据空壳**（不接 mock），真实数据接线与 DAG/Gate UI 归 **M1c-2**。
- **M6（进行中，见 `SPEC.md` M6）**：把执行体抽为可插拔 **`Worker`**（`[worker].provider = local | pi`）；
  **P2 `PiWorker` 已落地**，经固定 `pi-py-sdk` 驱动官方 TS agent 运行时（运行时需 **Node + `pi` 二进制**，
  仅 CI 之外）。
  每次 Worker 调用 = 一个**隔离会话**，原始输入/输出 + 步骤链落 run dir `sessions/<id>.json`，
  并由 `SESSION`/`WORKER_STEP` 事件索引（reducer 忽略，Board 不变）。检索类工具由 **TS 扩展回调
  server `Search` RPC*（provider 选择留 Python）。P1/P2 不依赖 server；P3–P5 依赖 M1c-1；P6 并入 M3。

## 常用命令

```bash
make install                # uv sync
make test                   # pytest（addopts=-q）
make lint                   # ruff check src tests scripts + mypy src（mypy strict，只查 src）
make fmt                    # ruff format src tests scripts
make cloc                   # 仅统计 src/originweave 逻辑行数
uv run pytest tests/test_config.py::test_default_values   # 跑单个测试
```

前端（`frontend/`，Node ≥ 24 + pnpm；M1b）：

```bash
make frontend-install      # pnpm --dir frontend install
make frontend-gen          # buf generate -> frontend/src/gen（需 buf；产物不入库）
make frontend-typecheck    # tsc -b --noEmit
make frontend-lint         # ESLint
make frontend-test         # Vitest（jsdom）
make frontend-build        # tsc -b && vite build
make frontend-dev          # Vite dev server
```

Python ≥ 3.11（CI 固定 3.11，mypy `python_version=3.11`）。所有命令走 `uv run`，不要直接调系统 Python。

## 架构红线（任何改动都不得突破）

1. 前端不拥有执行编排（只调 server API）。
2. server 拥有调度、持久化与运行时生命周期。
3. 实际任务执行必须建模为 **container-per-run**，不得在 server 进程内直接跑重任务。
4. 黑板是唯一事实来源，所有状态变更经事件写回，不得旁路。
5. provider/model/runtime 解耦：替换检索 / prompt / model provider 不应改动编排代码。

## 约定与坑

- **配置**：项目内 `originweave.toml`；`tomllib` 读、`tomli-w` 写。未知键直接抛
  `ConfigError`（防 `max_step` 之类拼写错误被静默忽略）。`CONFIG_FILENAME` 是**相对路径**，
  测试靠 `monkeypatch.chdir(tmp_path)`，不要在库代码里假设绝对路径。
  `[capability.model]` 默认 `openai` / `deepseek-v4.1-flash`，端点由 `OPENAI_BASE_URL` 提供
  （内网地址不入库）。**M6** 顶层 `[worker]`：`provider`(local\|pi，默认 `pi`)、`max_concurrency`(>0 且
  <=16)、`tools`(Pi 工具白名单)、`heartbeat_interval`(默认 `"15s"`)/`heartbeat_timeout`(默认 `"5m"`，
  须 `> interval`)/`heartbeat_on_timeout`(`release`\|`fail`)、`budget`（`max_steps` / `max_wall` /
  `max_cost`）；时长均为正整数加 `ms|s|m|h|d`（`config.parse_duration`）。Pi 的 model/base_url 复用
  `[capability.model]`。顶层 `[budget]` 已退役，旧配置会报错。
- **HITL 开关**：`[hitl].auto` 或 `CreateRunRequest.auto` 只控制 Gate（默认人工介入）。
- **凭据只从环境变量读**，不写入配置，且**多为可选**：`EXA_API_KEY` / `PARALLEL_API_KEY`
  （search 免费端点默认免 key）、`OPENAI_API_KEY`（+ 可选 `OPENAI_BASE_URL`）、
  `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`。
- **能力为真实调用**（Phase R 已移除 `[live]`/cache/录制回放）：测试注入 fake provider，不打真网。
- **事件字段名是契约**：`Event{id,at,type,message,tone,payload}`；reducer 只消费 `type`+`payload`，
  `message`/`tone` 仅展示。已实现 16 种类型（M1 增 `FAILED`/`STOPPED` → `status=failed|stopped`；
  M6 增 `SESSION`/`WORKER_STEP`，reducer 忽略、Board 不变）；`ENTITY`/`RELATION` 属 M5。见
  `docs/overview/blackboard-protocol.md` §5。
- `events.jsonl` 的唯一写入口是 `RunStore.append_event()`（id 单调递增、append-only）；reducer
  是纯 fold（`reduce(events) -> Board`，`src/originweave/reduce.py`），同事件必得同 `Board`。
  语义边（`main-chain`/`dependency`/`goal-derived`）必须显式写进事件 payload，结构边由 reducer 派生。
- **实体-关系图（M5）走同一 reducer**：事件 `ENTITY`/`RELATION`、模型 `Entity`/`Relation`/`EntityGraph`，
  契约见 `blackboard-protocol.md` §2.6/§5；仅当 `Run.analysis` 含 `relation` 时启用。
- `runs/` 与 `*.jsonl` 不入库（`.gitignore` 已就绪）；运行产物不要提交。
- 布局：src layout，包在 `src/originweave/`；测试 `tests/`；样例 `examples/`；proto 契约
  `proto/`（M1b）；前端 `frontend/`（M1b 脚手架、M1c-2 接线）；CI 在 `.github/workflows/ci.yml`
  （3 个 job：`python` ruff → mypy → pytest；`proto` `buf lint`；`frontend` gen → typecheck →
  lint → format:check → test → build）。前端 `format:check` 无 `make` target，用
  `pnpm --dir frontend format`。
- 当前 git 分支为 `develop`（`main` 为发布分支）；仓库无 CONTRIBUTING/PR 模板，未约定合并流程。
