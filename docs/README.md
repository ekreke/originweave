# 文档导航

本目录是 originweave 的**唯一事实来源（single source of truth）**。开发流程
（`dev-workflow`）先读 `milestones.md` 确定活跃版本，再读 `docs/<version>/SPEC.md`
确定下一个子任务，实现细节回到 `docs/overview/`。

## 目录结构

```text
milestones.md                     # 版本与里程碑索引（仓库根目录）
proto/                            # Connect/buf proto 契约（字段源：overview/）
frontend/                         # React + Vite + TS 前端（M1b 脚手架、M1c-2b 接线）
docs/
├── README.md                     # 本文件：导航、术语表、更新规则
├── overview/                     # 跨版本稳定的设计与契约
│   ├── product-overview.md       # 产品定义、领域模型、CLI 面、非目标
│   ├── blackboard-protocol.md    # 黑板元素、事件协议、OODA 循环、HITL
│   ├── agent-design.md           # capability / 运行时、预算、容器模型、架构红线
│   └── dashboard.md              # 只读 UI 结构 + 冻结的 proto 契约
├── 1.0/
│   ├── SPEC.md                   # 活跃版本的里程碑 checklist（进度真相）
│   └── TODO.md                   # 滚动待办与已知阻塞
└── design/                       # UI 风格稿（非契约，仅参考）
    └── swiss-blueprint.html      # 选定风格：Swiss / Blueprint（见 overview/dashboard.md）
```

## 术语表

| 术语 | 含义 |
|---|---|
| **资料 A** | 待核验的输入文档（网页 URL 或纯文本）。溯源与偏差判定的对象。 |
| **黑板（Blackboard）** | 共享的 append-only 全局状态（`Board`），承载 origin/goal/facts/intents/hints/entities/relations，是唯一事实来源。 |
| **Origin** | 黑板起点，特殊 Fact，即资料 A 的锚点。 |
| **Goal** | 黑板终点，特殊 Fact，即溯源停止条件 / 偏差判定标准。 |
| **Fact** | 已确认的发现（节点）。`kind` ∈ origin/goal/fact/citation/source/boundary/compare/deviation；`role` ∈ main-claim/sub-claim/none。 |
| **抽象论点** | 资料 A 的核心主张（`Fact.role=main-claim`），须拆解为子断言（`sub-claim`）后逐条验证。 |
| **Intent** | 待探索的方向（黑板上的问号）。`type` ∈ decompose/explore/verify/extract/relate；`status` ∈ open/claimed/done/dropped/awaiting_human。 |
| **Hint** | 经验提示（便利贴），`author` ∈ human/agent；不参与 DAG 连通性。 |
| **OODA** | Agent 工作循环：Observe → Orient → Decide → Act → Write Back。 |
| **Bootstrap / Reason / Explore / Validate** | 任务指令，每次只给 Worker 其一；`Validate` 是对候选 Intent 的独立判重 pass。 |
| **Stigmergy** | 间接协调：Worker 不互相通信，只通过往黑板写 Fact 改变环境来协调。 |
| **Dispatcher** | 调度与容器生命周期管理，协议的唯一写入者；Worker 不直接调用协议接口。 |
| **Worker** | 任务执行体：接收「黑板图 + 一条任务指令」，返回严格 JSON。`[worker].provider` ∈ local/pi；**不写黑板**。 |
| **Session（会话）** | 一次 Worker 调用的隔离历史（上下文不跨调用共享），含原始输入/输出与步骤链；落 `sessions/<id>.json`，由 `SESSION`/`WORKER_STEP` 事件索引。 |
| **HITL** | Human-in-the-loop。主动写 Hint，或在关键 Gate 被动确认（run → `awaiting_human`）。 |
| **Gate** | HITL 阻塞点：A 论点确认 / B 歧义裁决 / C 最终审阅。 |
| **provenance DAG** | 溯源有向无环图。节点为 Fact/Intent，边表示推导/探索关系。 |
| **Entity** | 实体-关系图的节点（人/组织/产品/地点等），`type` ∈ person/organization/product/location/event/other；同名按规范化名称归并（`aliases`）。 |
| **Relation** | 实体-关系图的边（有向）。`type` 取自关系本体；`inferred=true` 表示无来源推断（虚线）。 |
| **关系本体** | Relation 的预定义类型集合（`subsidiary-of`/`invests-in`/…/`other`），只建正向，反向标签由渲染层派生。 |
| **EntityGraph** | 与 provenance DAG 并列的第二张图（Entity + Relation），共享同一 run 与事件溯源。 |
| **evidence** | 节点上的证据：`quote`（逐字引用）+ `sourceTitle` + `url` + `locator`。可回链的依据。 |
| **deviation** | A 相对源头的偏差项（篡改、改写、省略、归因错误、时间错置等），带 `severity` 与 `confidence`。 |
| **run** | 一次端到端核验的执行实例，产出 DAG + 偏差记分卡 + report；`analysis` 含 relation 时另含实体-关系图。 |
| **run dir** | 一次 run 的持久化目录，含 append-only 事件日志与快照，可 `replay` 重放。 |
| **capability** | 外部能力抽象（检索 `search`、prompt `prompt`、模型 `model`、Worker 执行体 `worker`），provider 可替换；**真实调用**，无离线缓存。 |
| **verdict** | report 的整体判定（如"部分偏差"）。 |

## 更新规则

1. **进度只写回 SPEC**：milestone 小节的 checkbox 是进度的唯一载体，由 `checkpoint`
   阶段更新；更新前必须确认仓库状态确实支持该勾选。
2. **契约优先**：领域模型、黑板协议、proto 契约、CLI 面、run dir 布局属于 `overview/` 与
   `proto/`，变更需同步修改对应文档，不允许只改代码。
3. **架构红线**（任何改动都不得突破）：
   - 前端不拥有执行编排（frontend does not own execution orchestration）。
   - server 拥有调度、持久化与运行时生命周期。
   - 实际任务执行发生在**每次 run 一个临时容器**（container-per-run）中。
   - provider/model/runtime 解耦（替换 provider 不改编排代码）。
   - 黑板是唯一事实来源，所有状态变更经事件写回，不得旁路。
4. **文档语言**：中文，代码标识符与字段名保留英文。
