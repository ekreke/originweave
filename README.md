# originweave

给定资料 A，定位其核心说法的真实源头，判定 A 相对源头的偏差，输出**可审计的溯源 DAG + 偏差记分卡**（每项结论带来源 URL + 逐字引用，可回链、可重放）。

> 当前处于 **M1b（前端脚手架）**：脚手架、配置/capability 层、事件日志与 `replay`，
> `examples/copilot_productivity/` 样例，以及 `proto/` 契约与 `frontend/` 界面壳均已就绪
> （前端为无数据空壳）。**CLI 无 `trace`**：起 run 走 server / proto API（M1c-1），`ui` / `mcp` 仍为占位。
> 版本与里程碑见 `milestones.md`。

## 快速开始

```bash
make install             # uv sync，安装运行 + dev 依赖
uv run originweave init  # 生成项目内 originweave.toml（已存在需 --force）
uv run originweave capabilities list   # 查看 provider 与凭据就绪情况
uv run originweave replay examples/copilot_productivity   # 重放样例事件日志（不触网）
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
| `run` | 起本地测试环境。**尚未实现（后续 milestone）。** |
| `demo` | 端到端跑样例（server + 前端）。**归 M4，尚未接线。** |
| `fixtures` | 重新生成样例的 `events.jsonl`（确定性、产物入库）。 |
| `proto` | 由 `proto/` 生成 server Python 代码（需 `buf` + `protoc-gen-connect-python`；M1c-1）。 |
| `frontend-install` / `frontend-gen` / `frontend-dev` / `frontend-build` / `frontend-lint` / `frontend-typecheck` / `frontend-test` | 前端（`frontend/`，M1b）：安装 / proto 生成 / dev / 构建 / lint / tsc / vitest。 |
| `test` | `pytest`。 |
| `lint` | `ruff check` + `mypy`。 |
| `fmt` | `ruff format`。 |
| `ui` | 只起只读 UI 服务。**尚未实现（后续 milestone）。** |
| `replay` | `originweave replay <run-dir>`（事件日志重放，不触网）。 |
| `cloc` | 仅统计 `src/originweave` 逻辑代码行数。 |
| `clean` | 清缓存与临时 run。 |

> `run` / `demo` / `ui` 依赖的业务逻辑由后续 milestone 落地（见 `milestones.md`）。
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
