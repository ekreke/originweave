# originweave

给定资料 A，定位其核心说法的真实源头，判定 A 相对源头的偏差，输出**可审计的溯源 DAG + 偏差记分卡**（每项结论带来源 URL + 逐字引用，可回链、可重放）。

> 当前处于 **M0a 脚手架**阶段：仓库结构、依赖管理、Makefile、CI 与 README 已就绪；业务逻辑由后续子任务填充。

## 快速开始

```bash
make install     # uv sync，安装运行 + dev 依赖
make lint        # ruff check + mypy
make test        # pytest
make cloc        # src/originweave 逻辑代码行数
```

## Makefile

| target | 作用 |
|---|---|
| `install` | `uv sync`，安装运行依赖 + dev 依赖（ruff / mypy / pytest）。 |
| `run` | 起本地测试环境，离线优先（`LIVE=1` 触网）。**M0a 阶段为 stub，仅打印 not implemented。** |
| `demo` | 端到端跑样例（mock / 缓存）。**M0a 阶段为 stub，仅打印 not implemented。** |
| `test` | `pytest`。 |
| `lint` | `ruff check` + `mypy`。 |
| `fmt` | `ruff format`。 |
| `ui` | 只起只读 UI 服务。**M0a 阶段为 stub，仅打印 not implemented。** |
| `replay` | `originweave replay <run-dir>`。**M0a 阶段为 stub，仅打印 not implemented。** |
| `cloc` | 仅统计 `src/originweave` 逻辑代码行数。 |
| `clean` | 清缓存与临时 run。 |

> `run` / `demo` / `ui` / `replay` 依赖的业务逻辑由后续 milestone 落地（见 `milestones.md`）。

## 结构

```
src/originweave/   # 包源码（src layout）
tests/             # 单测
scripts/           # 辅助脚本
examples/          # 端到端样例
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
