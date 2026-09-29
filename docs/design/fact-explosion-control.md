# Fact 爆炸控制（Focus of Attention）

> 状态：**提案（非契约）**。本文记录问题的定位与解决方案，供评审；采纳实施后，引擎行为改动
> 需同步 `docs/overview/blackboard-protocol.md`（§2.2 decompose 语义、§4.2 派发）与
> `docs/overview/agent-design.md`（预算/配置），并回填 `docs/1.0/SPEC.md` 的 M9 checklist。

## 1. 问题陈述

给一段资料 A（例如「孔子周游列国十四年」），run 会**无限扩展**：一个抽象论点被拆成子断言，
子断言又被继续拆解或逐项探索，fact 数量在一轮内即可倍增，且看不到收敛边界。

一次真实 run 的观察（Console 的 GRAPH 视图）：

- `f5`（sub-claim）「孔子后来离开鲁国，周游列国十四年。」 → `i6`（decompose，`from=f5`）
- `i6` 一轮产出 `f46`–`f52` 共 7 条子断言，其中「所历国家的先后与年代，十四年之数是否与史源一致」
  本身是一个**枚举型**断言（卫、陈、曹、宋、郑、蔡、楚……），可继续逐国展开
- 每个新 fact 又触发新一轮 Reason（Stigmergy 正反馈），而 `max_rounds` 只限制**轮数**，不限制
  **每轮产出**，因此单轮即可新增十余个节点

后果：

1. **成本放大**：worker 调用与 token 随 fact 数线性（乃至组合）增长，`max_steps` 被大量低价值
   调用提前耗尽，核验在真正重要的断言上被截断。
2. **DAG 不可读**：图上节点爆炸，人工无法追踪「哪条溯源链是关键」。
3. **记分卡被噪音淹没**：为枚举项逐条产生的 deviation 稀释了真正的偏差信号。
4. **预算防线部分失效**：`[worker].budget.max_cost` 依赖 usage；`pi` worker 当前不上报 usage
   （见 `agent-design.md`），cost 恒为 0，实际只有 `max_steps` / `max_wall` 兜底。

## 2. 机制定位

| # | 机制 | 代码位置 | 后果 |
|---|---|---|---|
| 1 | **decompose 无深度限制**：prompt 只引导 `main-claim → decompose`，引擎不校验 `decompose` 的 `from_` 所指 fact 的 `role`，`sub-claim` 可再次 decompose | `engine.py` `_reason` 校验块、`_check_explored_facts` | 分解树可无限加深 |
| 2 | **无 fanout 上限**：单个 decompose 可产出任意多条 sub-claim | `prompts/explore.txt`（decompose 分支）无数量约束 | 一层拆出 7+ 条 |
| 3 | **每轮全量派发**：一轮把快照上所有 `open` 且 `type∈{explore,decompose,verify}` 的 Intent 一次性并发派发 | `blackboard-protocol.md` §4.2（派发 I4）、`engine.py` `_dispatch` | 单轮 10+ 路并发，一次爆炸 |
| 4 | **枚举型内容不聚合**：「所历 14 国」被逐国成 fact，每 fact 再 explore 出 citation/source 成对 | prompt 层；`_check_explored_facts` 未引导合并 | 节点数 ≈ 枚举项数 × 2 倍增 |
| 5 | **Stigmergy 正反馈 × `max_rounds` 仅限轮数**：每个新 fact 触发新一轮 Reason | `engine.py` `_continue` | 组合增长 |
| 6 | **预算防线不全**：`max_cost` 因 usage 缺失而失效 | `pricing.py` / usage 链路 | 只剩 `max_steps`/`max_wall` |

## 3. 理论背景：黑板架构的经典解法

Fact 爆炸不是本项目独有，而是**黑板架构的经典失效模式**，文献里已有成熟控制手段。

- **Hearsay-II「Focus of Attention」**（Lesser & Erman, IJCAI 1977）。语音理解的声学层错误向上
  传播，在共享黑板上产生**组合爆炸**的解释。解法有二：对黑板上的 hypothesis 设**阈值上限**
  （thresholds on hypotheses），以及 **attentional control**——以 stimulus/response frame 生成
  Knowledge Source 的候选激活，再按 desirability 评分**竞争**，每步只执行 top-K，而不是全部激活。
- **黑板系统综述**（emergentmind, *Blackboard System Architecture* §5）。明确指出
  **state-explosion** 是主要 trade-off，缓解方向是**抽象/聚合（containers & links）**、
  generic rules 与 problem-space **partitioning**。
- **BB1**（Hayes-Roth, Stanford CS-TR-84-1034）。引入 **control blackboard**：把「下一步做什么」
  本身建模为黑板上的元级知识，让调度策略显式、可解释、可学习。
- **R&D Analyst**（Regan et al., 2013）。在控制中加入 **focus-node stack**，允许**用户手选**
  焦点节点，覆盖或补充自动调度。

映射到本项目：

| 经典机制 | 本项目对应物 |
|---|---|
| hypothesis thresholds | 每轮宽度上限（A2）、单 claim fanout 上限（A3） |
| attentional control / desirability top-K | `_dispatch` 按 id 序截断（A2）；后续评分调度（D3） |
| containers / abstraction | 枚举型聚合为单 fact 多 evidence（B1/B2） |
| problem-space partitioning | decompose 固定两层，子断言只探索不再分解（A1） |
| control blackboard | 引擎侧确定性调度策略（本文 A 层） |
| user focus steering | HITL Gate A 扩展为人工勾选重点 claim（D2） |

## 4. 解决方案（分层防御）

设计原则：**不突破架构红线**——引擎仍是黑板唯一写入者，所有裁剪经事件留痕，reducer 保持纯
fold；所有控制策略**确定性**（按 id 序截断，不依赖并发完成顺序或集合迭代序），保证 `replay`
同事件得同 Board。

### A. 结构性刹车（引擎强制）

- **A1 · decompose 仅限 `main-claim`**：`_reason` 在写回候选 Intent 前，查黑板得到 `from_`
  所指 fact 的 `role`；`role != "main-claim"` 的 `decompose` 候选写为 `status=dropped`（复用
  Validate 的留痕模式，附 `question` 注记），而非令 run `FAILED`。分解树固定两层：
  `main-claim → sub-claim`，子断言只能被 `explore`/`verify`，不再分解。
- **A2 · 每轮宽度上限（dispatch width cap）**：`_dispatch` 取当轮 `open` Intent 时，按 **id 序**
  只派发前 K 个（K = `[run].dispatch_width`，默认 6）；其余保持 `open`，下一轮继续（**节流而非
  丢弃**，黑板状态完整）。对应 Hearsay-II 的 top-K focus。
- **A3 · 单 claim fanout 上限**：一个 `decompose` 产出的 sub-claim 数超过 `[run].max_fanout`
  （默认 8）时，按序保留前 N 条，超出的写入 `INTENT` 事件注记后丢弃（或不写回），保持确定性。

### B. 粒度引导（prompt 层）

- **B1 · decompose 粒度约束**（`prompts/explore.txt` decompose 分支）：子断言 ≤ 5 条、必须**可
  独立核验**；**枚举型集合（国家列表、年份序列、学说流派等）不得展开为多条，必须聚合为一条
  原子断言**（例：「所历国家先后为卫陈曹宋郑蔡楚，于卫陈停留最久」）。
- **B2 · 同源证据合并**（`prompts/explore.txt` explore 分支）：来自同一来源的同类证据应合并进
  一条 fact 的 `evidence[]`（该字段天然多值），不拆成多个 fact。

### C. 配置与预算

- **C1 · 配置暴露**：`[run]` 增 `max_rounds` / `dispatch_width` / `max_fanout`（未知键沿用
  `ConfigError` 防拼错约定；时长/整数校验同现有风格）。
- **C2 · 默认收紧 + 预算说明**：`max_steps` 默认值收紧；文档明确 `max_cost` 在 `pi` worker 下
  暂不可用（usage 缺失），实际防线为 `max_steps` / `max_wall`。

### D. 演进方向（不在首片）

- **D1 · 阈值不派发**：对 `confidence` 低于阈值的 sub-claim 不派发（保持 `open`，图上灰显），
  对应 Hearsay-II 的 hypothesis threshold。
- **D2 · HITL focus steering**：Gate A 从「确认核心论点」扩展为「人工勾选本轮重点 claim」，其余
  标记 `dropped`；对应 R&D Analyst 的 focus-node stack。
- **D3 · 评分调度**：Reason 为候选 Intent 附 priority，`_dispatch` 按评分取 top-K（需 Intent
  契约加字段），对应 BB1 的 control blackboard。

## 5. 确定性与契约影响

- 全部 A 层机制确定性：截断按 Intent **id 序**，裁剪结果经 `INTENT` / `HUMAN_INPUT` 等事件写入，
  reducer 不新增派生逻辑 → 同事件日志仍折叠出同一 `Board`，`replay` 行为不变。
- 事件 payload **结构不变**（`INTENT` 已支持 `status=dropped` 与 `duplicateOf`；A1/A3 复用
  `dropped` 语义或 `question` 注记）。逐条裁剪的动机应放进 `question`/`message` 以便审计。
- 实施时的**契约文字**变更：`blackboard-protocol.md` §2.2（decompose 仅 main-claim、fanout 上限）、
  §4.2（每轮宽度上限）；`agent-design.md`（`[run]` 新键与默认值）。

## 6. 落地切片（对应 SPEC M9）

| 分片 | 内容 | 文件 |
|---|---|---|
| M9a | A1 decompose 两层校验 + dropped 留痕 | `engine.py`、`tests/test_engine*.py` |
| M9b | A2 dispatch width cap + A3 fanout cap | `engine.py`、`config.py` |
| M9c | C1 `[run]` 配置暴露 + C2 默认收紧 | `config.py`、`originweave.toml` 样例、`tests/test_config.py` |
| M9d | B1/B2 prompt 粒度聚合 | `prompts/explore.txt` |
| M9e | 契约与文档同步 | `blackboard-protocol.md`、`agent-design.md`、`SPEC.md` |

验收：以枚举型资料 A（如「孔子周游列国」）起一次 run，**fact 总数有界**（不超过
`main-claim 数 × (1 + max_fanout)` 量级）；DAG 树上每个 main-claim 至多一层子断言；run 仍能正常走
到 `COMPLETE`（枚举内容聚合后不被误判为「未核验」）；同输入两次运行结构一致（确定性）。

## 7. 参考来源

- Lesser & Erman, *A Retrospective View of the Hearsay-II Architecture*, IJCAI 1977 —
  <https://www.ijcai.org/Proceedings/77-1/Papers/004.pdf>
- *Focus of attention in the Hearsay-II speech understanding system* (ACM DL) —
  <https://dl.acm.org/doi/10.5555/1624435.1624442>
- *Blackboard System Architecture*（综述，§3 控制策略 / §5 state-explosion），emergentmind —
  <https://www.emergentmind.com/topics/blackboard-system>
- Hayes-Roth, *BB1: An architecture for blackboard systems that control, explain, and learn about
  their own behavior*, Stanford CS-TR-84-1034 —
  <https://i.stanford.edu/pub/cstr/reports/cs/tr/84/1034/CS-TR-84-1034.pdf>
- Regan et al., *R&D Analyst: An Interactive Approach to Normative Decision System Model
  Construction*, 2013 — <https://arxiv.org/abs/1303.5426>
