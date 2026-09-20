# originweave

给定资料 A，定位其核心说法的真实源头，判定 A 相对源头的偏差，输出**可审计的溯源 DAG + 偏差记分卡**（每项结论带来源 URL + 逐字引用，可回链、可重放）。

> 当前 **M1 主体（I1–I6，库层）已完成** —— Bootstrap/Reason/Validate/Explore pass + Stigmergy 收敛、
> 并发 Worker/心跳、HITL Gate A；**M6（可插拔 Worker）** 的 `PiWorker`（P2）已落地（M1 残留：
> Dispatcher 接口对齐 M3、`verify` 型调度随 M2、样例输入的确定性单测）。
> **M1c-1（Connect server）**：**C1–C4 已落地**——proto codegen + Connect app、持久化、只读 + 写
> RPC（`CreateRun`/`AddHint`/`SubmitHumanInput`）、`originweave ui`（只读 API + 静态托管，端口 8765）。
> **M6 P3（Settings/Search/Session）已落地**——`GetSettings`/`UpdateSettings`（写回 `originweave.toml`）、
> `Search`（供 Pi TS 扩展回调）、`RunDetail.sessions`（读 `sessions/*.json`）。
> **M6 P4** 的 Pi TS 搜索扩展已落地（`src/originweave/pi_extensions/search.ts`，回调 server `Search`；
> 修了 agent-dir 环境变量名 bug）。
> 起 run 走 server / proto API（`CreateRun`，经 `source_text` 收资料 A），故 **CLI 无 `trace`**；
> `mcp` 仍为占位。`frontend/` 已完成 **2b-1 只读接线**（React Query 读真实数据；HITL/新建表单归
> 2b-2–2b-5）。版本与里程碑见 `milestones.md`。

## 快速开始

```bash
make install             # uv sync，安装运行 + dev 依赖
uv run originweave init  # 生成项目内 originweave.toml（已存在需 --force）
uv run originweave capabilities list   # 查看 provider 与凭据就绪情况
uv run originweave replay examples/copilot_productivity   # 重放样例事件日志（不触网）
make ui                  # 起只读 UI 服务（Connect API + frontend/dist，端口 8765）
make lint                # ruff check + mypy
make test                # pytest
make cloc                # src/originweave 逻辑代码行数
```

前端（`frontend/`，Node ≥ 24 + pnpm）：

```bash
make frontend-install    # pnpm --dir frontend install
make frontend-gen        # buf generate -> frontend/src/gen（需 buf；产物不入库）
make frontend-dev        # Vite dev server
make frontend-build      # tsc -b && vite build
```

## Makefile

| target | 作用 |
|---|---|
| `install` | `uv sync`，安装运行依赖 + dev 依赖（ruff / mypy / pytest）。 |
| `run` | 起本地只读视图（`originweave ui --run $(RUN_DIR) --port 8765`）。 |
| `demo` | 端到端跑样例（server + 前端）。**归 M4，尚未接线。** |
| `fixtures` | 重新生成样例的 `events.jsonl`（确定性、产物入库）。 |
| `proto` | 由 `proto/` 生成 server Python 代码（需 `buf` + `protoc-gen-connect-python`；M1c-1）。 |
| `frontend-install` / `frontend-gen` / `frontend-dev` / `frontend-build` / `frontend-lint` / `frontend-typecheck` / `frontend-test` | 前端（`frontend/`，M1b）：安装 / proto 生成 / dev / 构建 / lint / tsc / vitest。 |
| `test` | `pytest`。 |
| `lint` | `ruff check` + `mypy`。 |
| `fmt` | `ruff format`。 |
| `ui` | 起只读 UI 服务：Connect API + `frontend/dist`（存在时），端口 8765；`--run` 进单 run 只读模式。 |
| `replay` | `originweave replay <run-dir>`（事件日志重放，不触网）。 |
| `cloc` | 仅统计 `src/originweave` 逻辑代码行数。 |
| `clean` | 清缓存与临时 run。 |

> `demo` 依赖 M4 落地（见 `milestones.md`）；`run` / `ui` 已可用。
> `RUN_DIR=examples/copilot_productivity` 是入库样例，`RUNS_DIR=runs` 是运行产物（不入库）。

## 结构

```
src/originweave/   # 包源码（src layout）
tests/             # 单测
scripts/           # 辅助脚本
examples/          # 端到端样例（fixtures）
proto/             # Connect/buf proto 契约
frontend/          # React + Vite + TS 界面（M1b 脚手架、M1c-2 接线）
.github/workflows/ # CI
```

## 开发

```bash
uv sync                # 创建 .venv
uv run pytest          # 跑测试
uv run ruff format src tests
```

## 许可

MIT
