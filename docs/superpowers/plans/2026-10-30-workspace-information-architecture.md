# 正式项目工作台信息架构实施计划

> 按任务逐项执行并在各阶段提交。沿用已确认的轻量黑白视觉与项目工作台结构原型。

**Goal:** 将六项项目工作入口迁入正式前端，落实精致项目切换器、默认 Git 看板和精简成员页。

**Architecture:** 保留共同的 `app.js`/`space_board.js` 权限与会话边界，直接把现有页面容器重组为目标页面，并新增小型 Git graph DOM 组件。交付图只连接服务已返回的分支、Commit、PR、Release 对象；父子关系只连接有完整 SHA/关联证据的 Commit，绝不从分支名或时间顺序推断真实 commit ancestry。

**Tech Stack:** 原生 HTML、CSS、JavaScript、Node 回归、真实本机 HTTP 服务、Playwright CLI。

## 文件

- 修改 `src/static/index.html`、`src/static/app.js`、`src/static/accounts.js`、`src/static/styles.css`：导航、页面入口、历史返回、切换器、摘要与列表/只读展示。
- 修改 `src/static/space_board.js` 与 `src/static/board.html`：只读入口复用同一页面结构，保持票据与权限边界。
- 新增 `src/static/delivery_graph.js`：以已有可观察关联绘制 Git 分支轨道；点击节点打开同一交付详情抽屉，关联任务双向跳转。
- 新增 `tests/workspace_navigation_regression.js` 与 `tests/delivery_graph_ui_regression.js`：默认任务视图、history/回退、DOM 节点/边/选择/过滤/隐藏私有状态。
- 修改 `.github/workflows/ci.yml`、`CONTRIBUTING.md`：纳入回归命令。
- 新增 `docs/workspace-information-architecture-validation.md`：按查找任务记录真实验收。

## 阶段

1. 六项导航、项目路由和切换器；项目切换/返回/刷新保持所选页或明确回到项目概览。
2. 概览仅保留摘要与入口；任务默认看板；协作请求维持现有操作权限；上下文提供约定/文件/查询页签；成员页不显示 Harness 矩阵；项目设置保留仓库、连接及诊断；只读页使用同一层级。
3. Git 图呈现 API 已返回的分支、Commit、PR、Release 与其 task refs。可过滤对象类型和分支；选择节点打开关联详情，从详情回到原节点。图不伪造 compare/DAG ancestry、提交顺序或数据来源。
4. 在正式 CSS/JS 调整后运行相关回归、网页 HTTP 测试与全量网页 Node 命令；Playwright 查找任务包括队友 agent、有效约定、待答请求、任务↔PR、共享文件、活动、项目切换、只读及空项目。

所有页面和资源保留，不改变 API/schema/工具权限，不把临时 Harness 矩阵加入工作台。流程按能力组织，不要求用户按顺序操作。阶段提交后快进合入当前本地 `main`，不推送/发布，预览服务持续运行。
