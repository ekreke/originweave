# AGENTS.md · originweave

给定资料 A，定位其核心说法的真实源头、判定偏差，产出可审计的溯源 DAG + 偏差记分卡。
**`docs/` 文档用中文；代码标识符、字段名、CLI/事件名保留英文。** 现有代码的 docstring 与
行内注释是英文，跟随时保持一致。

## 事实来源与工作流

- `docs/` 是唯一事实来源；活跃版本 **1.0**（`docs/1.0/SPEC.md`）。开工前先读
  `milestones.md` 定位活跃版本，再读 `docs/1.0/SPEC.md` 确定下一个子任务。
- **进度只写回 SPEC 的 checkbox**（由 `checkpoint` 阶段更新，且必须能指向仓库真实文件）。
  `milestones.md` 的表格只是索引，不要手改其状态。
- 领域模型 / 黑板协议 / REST / CLI / run dir 布局是**冻结契约**，定义在
  `docs/overview/*`；改代码时若动到契约，必须同步改对应文档。
- 本仓库按 `dev-workflow` 流水线推进（progress-tracker → implement → testing-stage →
  checkpoint），每次迭代只推进一个子任务。

## 当前实现状态（别假设业务逻辑已存在）

- 已实现：`originweave init`（写 `originweave.toml`，已存在需 `--force`）、
  `originweave capabilities list`、配置加载/校验、capability 注册表与录制/回放，
  以及事件日志 → 黑板 reducer → `originweave replay <run-dir>`（只读、不触网）。
- **stub（打印 “not implemented yet”、返回 0）**：`trace` / `ui` / `mcp` /
  `capabilities install-obscura`。`make demo` / `run` / `ui` 依赖这些实现，现在只会命中 stub。
  `replay` 已接线，`examples/copilot_productivity/` 已含录制好的 `events.jsonl` 与
  `capabilities/**`（M0d），`make replay` 可离线复现 Board。
- 样例 fixture 由 `scripts/build_sample_fixtures.py` 确定性生成（`--check` 校验）；
  改样例事件/录制后要重跑该脚本。资料 A 与来源是**冻结快照**，重新联网结果具时效性。
- **默认离线**（`LIVE=0`）：capability 走录制回放，不触网。`exa` / `parallel` / `langfuse`
  的**真实联网调用 M3 才落地**，现在调用会抛 `ProviderUnavailableError`。
- `prompts/` 目录与前端源码当前都不存在（前端 M4 从零重建）。

## 常用命令

```bash
make install                # uv sync
make test                   # pytest（addopts=-q）
make lint                   # ruff check src tests scripts + mypy src（mypy strict，只查 src）
make fmt                    # ruff format src tests scripts
make cloc                   # 仅统计 src/originweave 逻辑行数
uv run pytest tests/test_config.py::test_default_values   # 跑单个测试
```

Python ≥ 3.11（CI 固定 3.11，mypy `python_version=3.11`）。所有命令走 `uv run`，不要直接调系统 Python。

## 架构红线（任何改动都不得突破）

1. 前端不拥有执行编排（只调 server API）。
2. server 拥有调度、持久化与运行时生命周期。
3. 实际任务执行必须建模为 **container-per-run**，不得在 server 进程内直接跑重任务。
4. 黑板是唯一事实来源，所有状态变更经事件写回，不得旁路。
5. provider/model/runtime 解耦：替换检索或 prompt provider 不应改动编排代码。

## 约定与坑

- **配置**：项目内 `originweave.toml`；`tomllib` 读、`tomli-w` 写。未知键直接抛
  `ConfigError`（防 `max_step` 之类拼写错误被静默忽略）。`CONFIG_FILENAME` 是**相对路径**，
  测试靠 `monkeypatch.chdir(tmp_path)`，不要在库代码里假设绝对路径。
- **离线开关优先级**：`ORIGINWEAVE_LIVE` 环境变量覆盖 `[live].enabled`；`--auto` 只控制
  HITL，不改变联网开关。
- **凭据只从环境变量读**，不写入配置：`EXA_API_KEY` / `PARALLEL_API_KEY` /
  `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`。
- **capability 录制布局**：`<run-dir>/capabilities/<provider>/<request_hash>.json`，
  `request_hash = sha256(canonical(provider+op+params))[:16]`（与参数书写顺序无关）。
  `LIVE=1` 边调用边写，`LIVE=0` 只读、未命中报错。
- **事件字段名是契约**：`Event{id,at,type,message,tone,payload}`；reducer 只消费 `type`+`payload`，
  `message`/`tone` 仅展示。事件类型见 `docs/overview/blackboard-protocol.md` §5。
- `events.jsonl` 的唯一写入口是 `RunStore.append_event()`（id 单调递增、append-only）；reducer
  是纯 fold（`reduce(events) -> Board`，`src/originweave/reduce.py`），同事件必得同 `Board`。
  语义边（`main-chain`/`dependency`/`goal-derived`）必须显式写进事件 payload，结构边由 reducer 派生。
- **实体-关系图（M5）走同一 reducer**：事件 `ENTITY`/`RELATION`、模型 `Entity`/`Relation`/`EntityGraph`，
  契约见 `blackboard-protocol.md` §2.6/§5；仅当 `Run.analysis` 含 `relation` 时启用。
- `runs/` 与 `*.jsonl` 不入库（`.gitignore` 已就绪）；运行产物不要提交。
- 布局：src layout，包在 `src/originweave/`；测试 `tests/`；样例 `examples/`；CI 在
  `.github/workflows/ci.yml`（ruff → mypy → pytest 顺序）。
- 当前 git 分支为 `develop`（`main` 为发布分支）；仓库无 CONTRIBUTING/PR 模板，未约定合并流程。
