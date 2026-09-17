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
  以及事件日志 → 黑板 reducer → `originweave replay <run-dir>`（只读、不触网）。
- **CLI 无 `trace`**：起 run 走 **server / proto API**（`CreateRun`，见 `dashboard.md` §4 与
  `proto/`），编排归 server。CLI 只保留 `init` / `replay` / `ui` / `capabilities` / `mcp`。
- **stub（打印 “not implemented yet”、返回 0）**：`ui` / `mcp` / `capabilities install-obscura`。
  `make demo` / `run` / `ui` 依赖这些实现（`demo` 归 M4，`ui` 归 M1c-1）。
  `replay` 已接线，`examples/copilot_productivity/` 已含 `events.jsonl`（M0d），`make replay`
  可不触网复现 Board。
- 样例 fixture 由 `scripts/build_sample_fixtures.py` 确定性生成（`--check` 校验）；
  改样例事件后要重跑该脚本。资料 A 与来源是**冻结快照**，重新联网结果具时效性。
- **能力为真实调用**（Phase R 已移除离线/cache/录制回放）：`search`（免费 MCP 端点，
  `exa`/`parallel`，**免 key**）与 `model`（OpenAI 兼容）已落地；`langfuse` 于 M3。
  凭据只从环境变量读、**多为可选**：`EXA_API_KEY` / `PARALLEL_API_KEY`（可选，换配额）、
  `OPENAI_API_KEY`（+ 可选 `OPENAI_BASE_URL`）、`LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`。
  单元测试**注入 fake provider**（`httpx.MockTransport`），不打真网。
- `proto/` 契约已定义；生成代码**不入库**（`buf generate` 产出）：前端 TS 由
  `pnpm --dir frontend gen`（`frontend/buf.gen.yaml`），server Python 归 M1c-1（根 `buf.gen.yaml`）。
- **前端（`frontend/`，M1b 脚手架）**：React + Vite + TS + React Flow + Connect；目前是
  **无数据空壳**（不接 mock），真实数据接线与 DAG/Gate UI 归 **M1c-2**。`prompts/` 目录仍不存在。

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
- **HITL 开关**：`[hitl].auto` 或 `CreateRunRequest.auto` 只控制 Gate（默认人工介入）。
- **凭据只从环境变量读**，不写入配置，且**多为可选**：`EXA_API_KEY` / `PARALLEL_API_KEY`
  （search 免费端点默认免 key）、`OPENAI_API_KEY`（+ 可选 `OPENAI_BASE_URL`）、
  `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`。
- **能力为真实调用**（Phase R 已移除 `[live]`/cache/录制回放）：测试注入 fake provider，不打真网。
- **事件字段名是契约**：`Event{id,at,type,message,tone,payload}`；reducer 只消费 `type`+`payload`，
  `message`/`tone` 仅展示。事件类型见 `docs/overview/blackboard-protocol.md` §5。
- `events.jsonl` 的唯一写入口是 `RunStore.append_event()`（id 单调递增、append-only）；reducer
  是纯 fold（`reduce(events) -> Board`，`src/originweave/reduce.py`），同事件必得同 `Board`。
  语义边（`main-chain`/`dependency`/`goal-derived`）必须显式写进事件 payload，结构边由 reducer 派生。
- **实体-关系图（M5）走同一 reducer**：事件 `ENTITY`/`RELATION`、模型 `Entity`/`Relation`/`EntityGraph`，
  契约见 `blackboard-protocol.md` §2.6/§5；仅当 `Run.analysis` 含 `relation` 时启用。
- `runs/` 与 `*.jsonl` 不入库（`.gitignore` 已就绪）；运行产物不要提交。
- 布局：src layout，包在 `src/originweave/`；测试 `tests/`；样例 `examples/`；proto 契约
  `proto/`（M1b）；前端 `frontend/`（M1b 脚手架、M1c-2 接线）；CI 在 `.github/workflows/ci.yml`
  （ruff → mypy → pytest 顺序）。
- 当前 git 分支为 `develop`（`main` 为发布分支）；仓库无 CONTRIBUTING/PR 模板，未约定合并流程。
