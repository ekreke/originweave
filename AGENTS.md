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
- **完成/checkpoint 前必须先派遣一个 subagent review 本次改动**（read-only：审 `git diff`、
  契约一致性、bug、测试质量与架构红线），按其结论修复后再提交；review 未做不得进入 checkpoint。
- **未经用户明确指示，不得 `git commit` / `git push`**：实现、测试、文档修改均**不构成**提交授权；
  只有用户明确说「提交」/「推送」（或等价指令）时才执行。

## 当前实现状态

逐片落地史见 `docs/1.0/SPEC.md` 的 checkbox（进度唯一载体），此处只留速览与持续有效的结论。

- **已落地**：
  - CLI：`init`（写 `originweave.toml`，已存在需 `--force`）/ `replay`（只读不触网，样例
    `examples/copilot_productivity/` 可复现 Board）/ `ui` / `capabilities list`；
    `mcp` 与 `capabilities install-obscura` 为 stub（打印 “not implemented yet”）。**CLI 无 `trace`**。
  - M1 库层 OODA 引擎（`engine.py`）：Bootstrap/Reason/Validate/Explore pass + Stigmergy 收敛、
    并发 + 心跳超时释放（I4）、HITL Gate A（I5，`Engine.resume`）、多轮收敛（I6）；`Engine` 是
    黑板**唯一写入者**。M2 偏差记分卡：verify 型经 `compare` pass、`deviation` Fact、严格
    `COMPLETE`、run dir `report.md`、Gate B（`arbitrate`）。任务指令模板在 `prompts/*.txt`。
  - server（M1c-1）：Connect ASGI app（`server/`，**18 个 RPC 全部实现**，含 `CreateRun`/
    `SubmitHumanInput`/`PauseRun`/`ResumeRun`/`GetSettings`/`Search`）、持久化（`run.json` 只存
    静态元数据，结果由 `events.jsonl` 派生）、`RunScheduler`、`originweave ui`（端口 8765，
    `--run <dir>` 单 run 只读、写 RPC 拒）。
  - M3a+M3b：container-per-worker（`runtime/`、`Dockerfile.runtime`、`make image`）；预算触顶
    `STOPPED{reason:"budget exceeded"}`（`pricing.py` 计价、usage 链路）；`PAUSED`/`RESUMED` +
    `PauseRun`/`ResumeRun`（`engine.request_pause`/`resume_from_pause`，轮次边界挂起）。
  - M6：可插拔 `Worker`（`[worker].provider`，默认 `pi`，`capabilities/pi.py` 经 `pi-py-sdk` 驱动
    TS agent 运行时，需 **Node + `pi` 二进制**，CI 之外）；每次调用 = 隔离会话落
    `sessions/<id>.json`；TS 搜索扩展（`pi_extensions/search.ts`）回调 server `Search`；
    前端 Settings 页 / INSPECTOR 会话视图 / EVENTS 按 worker 过滤。
  - 前端（`frontend/`）：React Query 真实数据接线（不接 mock）、React Flow + `@dagrejs/dagre`
    图渲染、Gate A/B UI、Replay 服务端折算；控制台轮询走轻量 `GetRunGraph`，点节点才取全量
    Fact，EVENTS/Sessions 按需取；浏览器 e2e 为 Playwright（真实 dist + fake-provider server）。
  - M5 仅落地契约层：`ENTITY`/`RELATION` 事件 writer + reducer、`Entity`/`Relation`/`EntityGraph`
    模型；上层（`extract`/`relate` Intent、消歧、UI 页签）未做。
- **操作要点**：server 测试与前端 e2e 需先 `make proto`（无 gen 时 server 测试整段
  `importorskip` 跳过；需 buf + `protoc` + `protoc-gen-connect-python`）；**起 run 前必须先建项目**
  （`CreateProject` + `/projects/new`；`make dev` 起可写 server，`ui`/`run` 只读样例）；
  `[worker].execution` **默认 `container`**——跑真实 run 前先 `make image`（需 Docker）。
- **Hint**：Reason 任务消费 hints——agent 在 reply 里产 `hint`、human 走 `AddHint` RPC；
  id（`h<N>`）由两处写入方**共同从事件日志推导**（`store.next_hint_id`），绝不冲突；
  agent hint 仅在收敛轮落盘（goal 满足或死胡同，与 Intent 同携的 `hint` 被忽略）。
- 样例 fixture 由 `scripts/build_sample_fixtures.py` 确定性生成（`--check` 校验）；改样例事件后
  要重跑。资料 A 与来源是**冻结快照**，重新联网结果具时效性。
- **能力为真实调用**（Phase R 已移除离线/cache/录制回放）：`search`（免费 MCP 端点
  `exa`/`parallel`，**免 key**）、`model`（OpenAI 兼容）、prompt `local` 已落地；
  prompt `langfuse` 仍未接入。单元测试**注入 fake provider**（`httpx.MockTransport`），不打真网。
- `proto/` 契约已定义；生成代码**不入库、勿手改**：前端 TS 由 `pnpm --dir frontend gen` 落
  `frontend/src/gen/`；server Python 由 `make proto` 落 `src/originweave/v1`（`originweave.v1.*`）。

## 常用命令

```bash
make install                # uv sync
make test                   # pytest（addopts=-q）
make lint                   # ruff check src tests scripts + mypy src（mypy strict，只查 src）
make fmt                    # ruff format src tests scripts
make proto                  # buf generate proto -> src/originweave/v1（M1c-1；需 buf + protoc + protoc-gen-connect-python）
make image                  # 烤 runtime 容器镜像（M3a；需 Docker，先跑 make proto）；execution=container 时每次调用起一个
make smoke                  # 端到端冒烟（进程内 fake worker → CreateRun/Gate/记分卡）
make dev                    # 起可写 server（cwd 下 runs/ + projects/；UI 里建项目/run）
make fixtures               # 重生成样例事件 events.jsonl（scripts/build_sample_fixtures.py，另有 --check 校验）
make cloc                   # 统计 src/originweave + frontend/src 逻辑行数（排除生成/测试/fixtures）
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
make frontend-e2e          # Playwright 浏览器 e2e（真实 dist + fake-provider server）
make frontend-dev          # Vite dev server
```

Python ≥ 3.11（CI 固定 3.11，mypy `python_version=3.11`）。所有命令走 `uv run`，不要直接调系统 Python。

## 架构红线（任何改动都不得突破）

1. 前端不拥有执行编排（只调 server API）。
2. server 拥有调度、持久化与运行时生命周期。
3. 实际任务执行必须建模为 **container-per-worker**（每个 Worker 调用一个临时容器），
   不得在 server 进程内直接跑重任务。
4. 黑板是唯一事实来源，所有状态变更经事件写回，不得旁路。
5. provider/model/runtime 解耦：替换检索 / prompt / model provider 不应改动编排代码。

## 约定与坑

- **配置**：项目内 `originweave.toml`；`tomllib` 读、`tomli-w` 写。未知键直接抛
  `ConfigError`（防 `max_step` 之类拼写错误被静默忽略）。`CONFIG_FILENAME` 是**相对路径**，
  测试靠 `monkeypatch.chdir(tmp_path)`，不要在库代码里假设绝对路径。
  `[capability.model]` 默认 `openai` / `deepseek-v4.1-flash`，端点由 `OPENAI_BASE_URL` 提供
  （内网地址不入库）。顶层 `[worker]`：`provider`(local\|pi，默认 `pi`)、`execution`(in-process\|container，
  **默认 `container`**)、`image`、`tools`(Pi 工具白名单)、`max_concurrency`(>0 且
  <=16)、`heartbeat_interval`(默认 `"15s"`)/`heartbeat_timeout`(默认 `"5m"`，
  须 `> interval`)/`heartbeat_on_timeout`(`release`\|`fail`)、`budget`（`max_steps` / `max_wall` /
  `max_cost`）；时长均为正整数加 `ms|s|m|h|d`（`config.parse_duration`）。Pi 的 model/base_url 复用
  `[capability.model]`。顶层 `[budget]` 已退役，旧配置会报错。**M1c-1** 顶层 `[project]`：
  `dir`(目录式 project 注册表根，默认 `"projects"`)；`[run].dir`(run 根，默认 `"runs"`)。
  `run.json` 只存该 run 的**静态/输入元数据**，结果（status/计数）一律由 `events.jsonl` 派生。
- **HITL 开关**：`[hitl].auto` 或 `CreateRunRequest.auto` 只控制 Gate（默认人工介入）。
- **凭据只从环境变量读**，不写入配置，且**多为可选**：`EXA_API_KEY` / `PARALLEL_API_KEY`
  （search 免费端点默认免 key）、`OPENAI_API_KEY`（+ 可选 `OPENAI_BASE_URL`）、
  `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`。
- **能力为真实调用**（Phase R 已移除 `[live]`/cache/录制回放）：测试注入 fake provider，不打真网。
- **Pi 运行时（M6）**：`pi` 的 agent 配置目录环境变量名由该构建的 `piConfig.name` 决定
  （`<NAME>_CODING_AGENT_DIR`）：上游 `pi`（如 homebrew 0.85.1，`piConfig` 无 `name`）读
  `PI_CODING_AGENT_DIR`，改名构建（`piConfig.name="ekreke"`）读 `EKREKE_CODING_AGENT_DIR`。
  `capabilities/pi.py` 的 `resolve_agent_dir_env_name()` 现**按二进制 `package.json` 推导**并同时设
  `PI_CODING_AGENT_DIR`（P2 bug 已修，P4）。扩展加载：`pi --no-extensions -e <ext.ts>` 仍需显式 `-e`
  （`--no-extensions` 只关自动发现）；`--tools <name>` 按精确名同时约束内建与扩展工具；
  `typebox`/pi 类型在仓库外路径可直接 import，无需 shim。`search` 工具由包内
  `src/originweave/pi_extensions/search.ts` 提供，回调 server `Search`（`ORIGINWEAVE_SERVER_URL`）。
- **测试与工具链**：pytest `asyncio_mode = "auto"`（`pyproject.toml`），async 测试**不加**
  `@pytest.mark.asyncio`；ruff `line-length = 100`（非默认 88），mypy strict **只查 `src`**。
  前端 `pnpm --dir frontend test` 经 `frontend/scripts/test-watchdog.mjs` 包装：vitest 的
  `testTimeout` 杀不掉「microtask 自旋饿死定时器」的挂死（曾致 4 个 worker 烧 CPU 3.7h），
  看门狗默认 300s 强杀进程组，`VITEST_WATCHDOG_TIMEOUT`（秒）可调。
- **事件字段名是契约**：`Event{id,at,type,message,tone,payload}`；reducer 只消费 `type`+`payload`，
  `message`/`tone` 仅展示。已实现 **20 种类型**（M1 增 `FAILED`/`STOPPED` → `status=failed|stopped`
  与 `VALIDATE`；M3b 增 `PAUSED`/`RESUMED`；M6 增 `SESSION`/`WORKER_STEP`，reducer 忽略、Board
  不变；M5 契约层 `ENTITY`/`RELATION` 的 writer+reducer 已落地）。见
  `docs/overview/blackboard-protocol.md` §5。
- `events.jsonl` 的唯一写入口是 `RunStore.append_event()`（id 单调递增、append-only）；reducer
  是纯 fold（`reduce(events) -> Board`，`src/originweave/reduce.py`），同事件必得同 `Board`。
  语义边（`main-chain`/`dependency`/`goal-derived`）必须显式写进事件 payload，结构边由 reducer 派生。
- **实体-关系图（M5）走同一 reducer**：事件 `ENTITY`/`RELATION`、模型 `Entity`/`Relation`/`EntityGraph`
  均已落地，契约见 `blackboard-protocol.md` §2.6/§5；仅当 `Run.analysis` 含 `relation` 时启用，
  上层 Intent/消歧/UI 未做。
- `runs/` 与 `*.jsonl` 不入库（`.gitignore` 已就绪；`examples/**/*.jsonl` 例外放行，样例事件入库）；
  运行产物不要提交。
- 布局：src layout，包在 `src/originweave/`；测试 `tests/`；样例 `examples/`；proto 契约
  `proto/`（M1b）；前端 `frontend/`（M1b 脚手架、M1c-2b 接线）；CI 在 `.github/workflows/ci.yml`
  （3 个 job：`python` ruff → mypy → pytest + `make smoke`；`proto` `buf lint`；`frontend` gen →
  typecheck → lint → format:check → test → build → **Playwright e2e**（增 Python/uv/`make proto`））。
  前端 `format:check` 无 `make` target，用
  `pnpm --dir frontend format`。
- 当前 git 分支为 `develop`（`main` 为发布分支）；仓库无 CONTRIBUTING/PR 模板，未约定合并流程。
