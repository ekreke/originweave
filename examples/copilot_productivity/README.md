# copilot_productivity sample

样例：核验一份**二手页**对 GitHub Copilot 生产力研究的转述，产出可审计的溯源 DAG
与偏差记分卡。这是 `originweave replay`（以及后续 `make demo`）的端到端 fixture。

样例无既有 spike 可迁，是从零构建的（M0d）。

## 资料与来源

| | 内容 |
|---|---|
| **资料 A** | `input/document.md` — Sityos AI *“55% Faster Code, 84% Better Builds: GitHub Copilot's Real Enterprise Impact”*（`sourceType: url`） |
| **S1（一手）** | `sources/github_copilot_lab_2022.md` — GitHub 2022 实验室研究 |
| **S2（一手）** | `sources/github_copilot_accenture_2024.md` — GitHub + Accenture 2024 企业研究 |

`input/source.json` 记录资料 A 的 `url`/`sourceType`/`fetchedAt`；`sources/manifest.json`
登记两个来源及其快照文件。所有 `Evidence.quote` 均可回链到这些快照（保留原文标点，软换行按
空白折叠）。

## 预期偏差（记分卡）

| id | 资料 A 的说法 | 一手来源实际说法 | 类型 | severity |
|---|---|---|---|---|
| d1 | “55% faster”归因于与 Accenture 的企业研究 | 55% 出自 2022 实验室研究（n=95、单个 JS HTTP server 任务） | 归因错误 | high |
| d2 | “1,000+ 开发者、6 周”“PR 周期 9.6→2.4 天（−75%）” | S1、S2 均无这些数据（S2 只报告 8.69% PR 增长、15% 合并率、84% 构建成功率） | 无来源数字 | high |
| d3 | “55% faster”直陈 | 原文 95% 置信区间为 [21%, 89%]，属单任务小样本 | 省略边界 | high |
| d4 | 把 84% 构建成功率、90% 满意度并列为同一结论 | 84% 为遥测指标、90% 为开发者自报比例，性质不同却被并列陈述 | 指标混用 | medium |
| d5 | 称其为 “peer-reviewed enterprise data” | 两篇均为厂商博客，未经同行评审 | 表述夸大 | medium |
| d6 | “90% higher job satisfaction” | 原文为“90% 表示更有成就感”，非满意度提升 90% | 数值口径 | low |

`verdict = 部分偏差`。

## 产物结构

```text
examples/copilot_productivity/
├── README.md              # 本文件
├── input/                 # 资料 A 冻结快照 + source.json
├── sources/               # 一手来源快照 + manifest.json
└── events.jsonl           # append-only 事件日志（该次 run）
```

## 能力

能力为**真实调用**（Phase R 起无离线缓存 / 录制回放）：

- `search`（exa / parallel，免费 MCP 端点）：检索来源、定位一手材料，返回文本上下文
- `model`（OpenAI 兼容）：OODA 的 `Bootstrap` / `Reason` / `Explore`
- `prompt`（`local`）：模板位于仓库 `prompts/` 目录

凭据只从环境变量读、**多为可选**：`EXA_API_KEY` / `PARALLEL_API_KEY`（search 免费端点默认免 key）、
`OPENAI_API_KEY`（+ 可选 `OPENAI_BASE_URL`）。
**本样例不再提供录制响应**；`replay` 复现的是 `events.jsonl` 这份事件日志，而非能力调用。

## 运行

```bash
make replay       # = originweave replay examples/copilot_productivity（只读、不触网）
make fixtures     # 重新生成 events.jsonl（应逐字节一致）
```

`make demo`（server + 前端的端到端）依赖 M1c-1 / M1c-2 / M4；真实 provider 的结果具时效性，
因此**可复现的对象是这份 `events.jsonl`**，而不是“重新联网再跑一遍”。

## 事件日志

`events.jsonl` 由 `scripts/build_sample_fixtures.py` 用 `RunStore.append_event()` 生成
（固定时间戳），产物入库；测试会重生成并逐字节比对。事件覆盖 `PROJECT → HINT →
INTENT/CONCLUDE（Bootstrap/explore 抽取 → decompose 拆解 → explore 回链 → verify 比对）→
REQUEST_HUMAN/HUMAN_INPUT（Gate A `confirm-claim` / Gate B `arbitrate`）→ COMPLETE`。事件类型
只用 `blackboard-protocol.md` §5 已实现类型中的 10 种（本样例未用 `RELEASE`；`ENTITY`/`RELATION`
属 M5）。
`spawns`/`resolves`/`decomposes` 结构性边由 reducer 派生；`main-chain`/`dependency`/
`goal-derived` 语义边显式写在事件 payload。
