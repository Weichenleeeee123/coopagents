# 工作台迁移验收记录

这次迁移把项目内入口收敛为概览、任务、协作、共享上下文、交付、成员与 agent、项目设置。任务页默认打开看板，Harness 支持矩阵不再作为工作台入口；交付页使用基于证据的 Git 关系图展示分支、提交、Pull request 与 Release。

## 真实前后端验收

本机用独立 SQLite 数据库启动真实 HTTP 服务，通过浏览器完成了：

- 初始化本地账号、创建团队与两个项目；
- 进入项目后读取真实项目快照和实时状态；
- 在两个项目之间打开项目切换器并切换项目；
- 访问任务看板、共享上下文三个分类、交付关系图、成员与 agent、项目设置；
- 在 390x844 手机视口检查工作台导航、项目切换器和概览布局。

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