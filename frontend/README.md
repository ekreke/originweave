# originweave frontend

只读审阅台（React + Vite + TypeScript）。经 **Connect** 直连 server 的 proto 契约
（`../proto/`），**不使用 mock 数据**。

当前为 **M1b 脚手架**：布局、路由、页签与生成代码接入已就绪，但**尚无真实数据**
（空态）。数据接线、DAG 渲染与 HITL Gate 在 **M1c**。

## 命令

```bash
pnpm install          # 安装依赖
pnpm gen              # buf generate -> src/gen（需 buf；产物不入库）
pnpm dev              # Vite dev server
pnpm build            # tsc -b && vite build
pnpm typecheck        # tsc -b --noEmit
pnpm lint             # ESLint
pnpm format           # Prettier
pnpm test             # Vitest（jsdom）
```

根目录亦可：`make frontend-install|frontend-gen|frontend-dev|frontend-build|frontend-lint|frontend-typecheck|frontend-test`。

## 结构

```text
src/
├── api/        # Connect transport + typed client（暂未调用）
├── graph/      # React Flow 空画布
├── layout/     # 顶栏 + 三栏（RunList / Inspector）
├── routes/     # / · /projects/:id · /runs/new · /runs/:runId · /settings
├── styles/     # Swiss/Blueprint tokens（浅/深）
├── tabs/       # GRAPH · FACTS · INTENTS · EVENTS
├── theme/      # 主题上下文
└── gen/        # buf 生成（不入库）
```

设计参考：`../docs/design/swiss-blueprint.html`（仅视觉 tokens / 布局；渲染器为 React Flow）。
契约：`../proto/originweave/v1/originweave.proto` 与 `../docs/overview/dashboard.md`。
