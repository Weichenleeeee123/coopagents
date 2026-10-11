# 前端完善实施计划

日期：2026-10-11。用户已确认设计并要求直接完成，采用当前会话内逐项执行。

**目标：** 完成 `frontend-design-proposal.md` 的 A 方向，使登录、账号中心、项目工作台及移动端具有统一视觉和清楚的操作层级。

**结构：** 保留四个现有脚本及 DOM ID。`accounts.js` 管理账号中心视图与加载反馈，`app.js` 管理项目导航、筛选、卡片和详情，`git.js` 分组仓库接入，`billing.js` 保留付款生命周期。CSS 按组件重整为单一规则体系。

**技术栈：** 原生 HTML/CSS/JavaScript、Python Starlette、Node 回归脚本、真实浏览器。

## 1 · 设计记录

- [x] 阅读仓库约定、现有页面和行为回归。
- [x] 将设计状态更新为已确认；提交本计划。

## 2 · 视觉与页面框架

文件：`src/static/index.html`、`src/static/styles.css`。

- [x] 保留所有表单 ID、字段和权限容器；账号中心增加项目、成员、团队设置、账单的命名 section 与导航按钮。
- [x] 项目侧栏增加原生 details 选择器，使移动端团队／项目切换可展开；五个导航入口为单行滚动。
- [x] 整理 CSS token、控件、导航、表面、卡片、详情和响应式；用原生 dialog 实现右侧详情，凭据 dialog 保持居中。
- [x] 新建任务仅通过主按钮展开，保留 details 中的取消入口；增加全局无匹配反馈和清除筛选按钮。
- [x] 四个原有 Node 回归及 JS 语法检查通过后提交框架阶段。

## 3 · 界面行为

文件：`src/static/accounts.js`、`src/static/app.js`、`src/static/git.js`、`tests/account_ui_regression.js`。

- [x] 先扩展账号回归 harness 以提供真实导航按钮属性，验证选择成员视图、团队切换回项目、管理操作刷新保留当前视图、账单 fragment 直达账单。运行并观察新增断言失败。
- [x] 账号中心用 `setHubView(view)` 切换四个 section、aria-current 和标题。团队变化重置项目视图，同团队刷新保留视图；无团队时仍允许建立或加入团队。
- [x] 在 loading 状态用独立 status 文案与 aria-busy 提示；出错后停止 loading，不将请求失败表现为空项目。
- [x] 项目搜索无结果显示清除筛选；同步状态保留原有断线和失效行为；新建表单可取消；状态 badge 使用明确语义样式。
- [x] Git 接入按绑定、本地配置、远端同步分块；所有数据仍用 textContent。
- [x] 运行 `node tests/account_ui_regression.js src/static/accounts.js`、其余三个网页回归及 `.venv/Scripts/python.exe -m unittest discover -s tests -p test_web.py -v`，新增断言及旧生命周期断言全部通过后提交。

## 4 · 浏览器验收与记录

文件：`docs/frontend-validation.md`、`docs/README.md`；本机证据位于独立 `.local/frontend-qa-*`。

- [x] 使用独立随机端口服务和保留数据库，通过真实 API 创建虚构团队、项目和工作记录。
- [x] 检查登录、账号中心四个视图、团队切换、进入项目、看板搜索和清除、任务创建与详情、Escape／焦点恢复、团队现场、请求、约定、仓库接入、凭据关闭清除、账单 fragment。
- [x] 检查 1440、1280、768、390、320px 下文档无横向溢出；看板容器允许滚动；长内容换行；低动态效果与焦点可见。
- [x] 查看桌面和移动截图、脚本错误与失败请求，修复实际问题后重跑相关检查。
- [x] 记录真实本机结果、截图位置和外部能力的验收边界，按阶段提交，确认工作区干净。

全程不删除文件；凭据、数据库、浏览器配置及原始数据不提交 Git。
