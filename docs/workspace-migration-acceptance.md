# 工作台迁移验收记录

## 正式工作台视觉复核（2026-10-31）

本轮完成的正式前端不再沿用深色侧栏原实现，已按[确认的项目工作台原型](prototypes/project-workspace/index.html)迁移为浅灰图标侧栏、白色内容区、项目切换弹窗、当前页面导航/面包屑及右侧详情抽屉。任务默认看板，保留真实列表切换。项目内六项主要能力与底部项目设置分别呈现；Harness 支持矩阵仍在文档。

浏览器使用本机当前源码启动的自托管服务与保留的合成数据数据库，完成桌面 1600×1000 与手机 390×844 的 29 项交互检查：列表及搜索、看板、键盘 Escape 关闭与焦点恢复、抽屉右侧定位、交付分支/类型/搜索过滤与清除恢复、SVG 边端点对齐、上下文真实查询、项目设置诊断和七个页面的手机宽度/导航收起。另通过真实 API 创建任务、刷新后确认记录存在、切换到其他项目后确认项目内容隔离，再切回原项目。没有使用模拟网络响应或脚本修改 DOM 数据。

完成中发现的抽屉异步关闭竞态、只读票据更换后旧项目内容残留、PR/分支缺少同分支证据仍连线等问题均增加定向回归。详情操作失败在抽屉内显示；只读页面仍不提供管理操作。只读资源图标加入显式静态资源白名单。

界面截图只证明自托管工作台和合成示例数据可用，不证明真实双机连接、实际 GitHub 远端对象、agent 模型消费或任何 Harness 自动唤醒。逐页截图与来源边界见[品牌资产](brand-assets.md)。

这次迁移把项目内入口收敛为概览、任务、协作、共享上下文、交付、成员与 agent、项目设置。任务页默认打开看板，Harness 支持矩阵不再作为工作台入口；交付页使用基于证据的 Git 关系图展示分支、提交、Pull request 与 Release。

## 真实前后端验收

本机用独立 SQLite 数据库启动真实 HTTP 服务，通过浏览器完成了：

- 初始化本地账号、创建团队与两个项目；
- 进入项目后读取真实项目快照和实时状态；
- 在两个项目之间打开项目切换器并切换项目；
- 访问任务看板、共享上下文三个分类、交付关系图、成员与 agent、项目设置；
- 在 390x844 手机视口检查工作台导航、项目切换器和概览布局。
- 使用包含分支、commit、PR 和 Release 的交付图数据检查节点轨道与证据连线；在 390px 和 1280px 视口确认页面无横向溢出，缩放后连线按节点新位置重算。

验收数据和截图保存在本机 .local/test-evidence/ 与 .playwright-cli/，不提交到 Git。服务使用的 bootstrap 密钥只保存在本机证据目录。

## 回归命令

```powershell
node tests/web_session_regression.js src/static/app.js
node tests/account_ui_regression.js src/static/accounts.js
node tests/workspace_navigation_regression.js
node tests/delivery_graph_ui_regression.js
node tests/shared_context_ui_regression.js
node tests/capability_discovery_ui_regression.js
node tests/project_activity_ui_regression.js
node tests/space_board_session_regression.js
node tests/task_lifecycle_ui_regression.js
node tests/board_ui_regression.js
node tests/delivery_ui_regression.js
```

后端针对账号、网页安全头、共享上下文、能力发现、交付追踪、任务生命周期和工作区权限的 51 项 unittest 已通过。完整测试入口仍是 python -m unittest discover -s tests -v。

## 当前边界

交付图只绘制明确关联、本地 Git 观测和已验证 GitHub 事实；没有证据的提交祖先关系不会被推断。真实 GitHub 远端对象需要在项目设置中绑定仓库并由 agent 或 GitHub 同步写入观测后才会出现在图中。
