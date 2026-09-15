# Dashboard · originweave

本文定义只读运行视图（dashboard）的**信息结构**与**冻结 REST 契约**。
此前的前端 mock 构建（MSW handler）已随 `frontend/` 清理移除；**本文件即契约事实来源**，
M4 时前后端共同遵守。

## 1. 定位

Dashboard 是 run 的**审阅台**：查看溯源 DAG、事实/意图表、事件时间线、偏差记分卡
与 report，并在 HITL Gate 处提供人工介入。发起任务（新建核验）走 server API，
但**执行编排由 server 拥有**，前端不触碰容器生命周期（见 `agent-design.md` 第 7 节）。

## 2. 视觉与布局

选定风格：**Swiss / Blueprint（瑞士蓝图）**，布局为三栏控制台。

设计取向：**工程制图般的秩序感**——浅色网格纸底 + 蓝图蓝强调，把颜色预算留给语义。
`Fact` 按 `kind` 用**形状 + 颜色双编码**（origin/goal 圆环、fact 方块、citation 三角、
source 菱形、boundary 虚线框、compare 六边、deviation 警示三角）；`Intent` 为**虚线问号徽标**
（`open` 虚线 / `claimed` 脉冲 / `done` 实线 / `dropped` 划除 / `awaiting_human` 警示描边）；
`Hint` 计数归于 INSPECTOR，`origin`/`goal` 为两端锚点。

参考稿：`docs/design/swiss-blueprint.html`（非契约，仅参考）。

```text
┌──────────┬───────────────────────────────────────────────┬──────────────┐
│ brand    │ 顶栏：面包屑 · 状态徽标 · 预算 · Human/Replay/Continue│              │
├──────────┼───────────────────────────────────────────────┼──────────────┤
│ run 列表  │ GRAPH | FACTS | INTENTS | EVENTS               │ INSPECTOR    │
│ (左栏)    │ ───────────────────────────────────────────── │ 选中节点详情  │
│          │ 事实图画布（hero）：origin/goal 锚点 ·           │ 证据逐字引用  │
│          │ Fact 卡 · Intent 问号 · Hint 便利贴 · Gate 面板  │ Intent/Hints │
└──────────┴───────────────────────────────────────────────┴──────────────┘
```

- 顶栏：面包屑（`Researches / <project> / <run>`）+ 状态徽标（`AWAITING_HUMAN · Gate A`、
  `LIVE`）+ 预算（`steps` / `tok` / `cost` / `intents`）+ 操作
  （Replay 步进 / Human / Continue）。
- 中栏（图为主体）页签：
  - **PROVENANCE DAG** — 图视图（默认页签）。节点按 `kind` 着色
    （origin/goal/fact/citation/source/boundary/compare/deviation/**intent**）；
    Intent 以问号徽标呈现，`open/claimed/dropped` 分别用灰/蓝/划除；
    边按 `relation` 区分（`main-chain` 实线、`dependency` 虚线、
    `decomposes` 点线、`spawns`/`resolves` —— 见 `blackboard-protocol.md`）。
  - **FACTS** — 事实表：`ID | Kind | Statement | Conf. | Evidence`。
  - **INTENTS** — Intent 表：`ID | Type | Question | Status | From`，含 `dropped`（死胡同）。
  - **EVENTS** — 事件时间线，按 `tone` 着色（黑板协议事件）。
- 右栏 **INSPECTOR**：选中节点详情（`role`/`from`/`spawns`/`resolved-by`）、
  逐字引用（`quote + sourceTitle + locator`）、`Intent open/claimed/done/dropped` 计数、
  `Hints`（含写 Hint 输入框）、预算状态。
- **HITL Gate 面板**：`run.status = awaiting_human` 时，INSPECTOR 顶部高亮门控卡片
  （Gate A 论点确认 / Gate B 歧义裁决 / Gate C 最终审阅），提供 批准 / 修正 / 驳回。
- 左侧 run 列表：卡片展示 `status`、`facts`、`deviations`、`confidence`、`steps`；
  `awaiting_human` 时以警示色高亮。

## 3. 路由

| 路由 | 视图 |
|---|---|
| `/` | 总览（项目与 run 汇总） |
| `/projects/:projectId` | 项目详情 + run 列表 |
| `/projects/:projectId/runs/new` | 新建核验（提交后走 `POST /api/runs`） |
| `/settings` | 设置（主题等） |

## 4. 冻结 REST 契约

所有响应为 JSON；错误沿用 `{ "message": ... }` + 合适状态码。

### 4.1 端点

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/projects` | 列出全部项目 → `Project[]` |
| GET | `/api/projects/:projectId` | 单个项目 → `Project`；不存在 → 404 |
| GET | `/api/projects/:projectId/runs` | 某项目下 run 列表 → `Run[]` |
| GET | `/api/runs` | 全部 run；支持 `?projectId=` 过滤 → `Run[]` |
| GET | `/api/runs/:runId` | run 详情 → `RunDetail`；不存在 → 404 |
| POST | `/api/runs` | 新建 run，body 见 4.3 → `Run` |
| POST | `/api/runs/:runId/hints` | 写一条 Hint，body 见 4.4 → `Hint` |
| POST | `/api/runs/:runId/human-input` | 提交 HITL Gate 决策，body 见 4.4 → 更新后的 `Run` |

### 4.2 RunDetail

```text
RunDetail {
  run:        Run,          # 见 product-overview.md 第 4 节
  origin:     Fact,         # 黑板起点
  goal:       Fact,         # 黑板终点
  facts:      Fact[],       # provenance DAG 事实节点
  intents:    Intent[],     # 待探索/进行中/已完成
  hints:      Hint[],
  edges:      Edge[],
  deviations: Deviation[],
  events:     Event[],
  waitingFor?: { gate, question },   # 仅当 run.status = awaiting_human
  report: {
    runId:    string,
    verdict:  string,       # 如 "部分偏差"
    summary:  string,
    findings: Deviation[],
    sources:  Evidence[]
  }
}
```

### 4.3 POST /api/runs 请求体

```text
{
  projectId: string,
  title?:    string,        # 缺省时按 mode 生成（"网页资料核验" / "文本主张核验"）
  mode:      "url" | "text",
  goal:      string,
  maxSteps:  number,
  auto?:     boolean        # true = 全自动，跳过 HITL Gate（默认 false）
}
```
新建的 run 初始化为 `status: "queued"`、计数为 0、`budget` 归零。

### 4.4 HITL 端点

写 Hint（主动注入，非阻塞）：
```text
POST /api/runs/:runId/hints
{ text: string }            # author 固定为 "human"
```

提交 Gate 决策（被动，解除 `awaiting_human`）：
```text
POST /api/runs/:runId/human-input
{
  gate:      "confirm-claim" | "arbitrate" | "review",
  decision:  "approve" | "edit" | "reject",
  text?:     string,        # decision=edit 时的修正内容
  targets?:  string[]       # 作用对象（Fact/Intent id）
}
```
两者均落为 `HINT` / `HUMAN_INPUT` 事件，因此可审计、可重放。

### 4.5 领域类型

`Project` / `Run` / `Fact` / `Intent` / `Hint` / `Edge` / `Evidence` /
`Deviation` / `Event` / `Report` 的定义一律以 `product-overview.md` 第 4 节与
`blackboard-protocol.md` 为准，此处不重复。

## 5. 契约原型与样例

此前的 mock 数据曾提供样例：项目 `obscura-kitesurf` / `citation-watch`，run
`run_009`（running）、`run_008`（completed）、`run_007`（paused）；以及一条完整
DAG（`desc → f1 核心结论 → c1 引用 → s1 原始来源 → p1 比对 → d1/d2 偏差`）。
该产物已随 `frontend/` 清理移除，样例仅作契约与命名参考。

约定：M4 落地 server 后，**同一批端点与字段**应由真实 API 提供；契约若变更，
先改本文件，再同步前后端。
