# 整体前端完善验收

日期：2026-10-11。设计采用用户已确认的 A 方向，沿用石墨色导航与薄荷绿操作。

## 交付内容

- `styles.css` 合并早期及后续覆盖规则，按 token、控件、登录、工作台、账号、看板、协作记录、弹窗、账单、仓库和响应式组织。统一字号、边线、表面、间距及焦点；辅助文字主要提升至 12px。
- 账号中心分为项目、成员、团队设置、Plan & billing 四个视图。创建项目在项目视图展开；邀请、接管项目及改密归入设置；账单保持独立英文区域。
- 项目工作台的团队／项目选择可展开；手机采用单行横向导航，包含全部五个入口。看板仅在自身容器横向滚动。
- 新建任务使用单一主按钮；取消可收起表单，创建成功后收起并将焦点返回按钮。无匹配结果显示清除筛选。
- 任务详情桌面从右侧展开，手机为全屏原生 dialog。保留 Escape 和焦点返回，将去重标识折叠，优先展示任务概况、进展与证据。
- 团队现场、请求、公共约定、凭据和账单统一组件样式。仓库接入分为共同仓库、本地 agent、GitHub 交付同步三个命名区块。
- 页面标题随当前视图更新。账号中心显示加载状态；同团队刷新保留当前视图，切换团队回到项目。

## 浏览器验收中修复的问题

1. 账号中心原先沿用任务页的浏览器标题；登录、账号四个视图与项目导航现分别设置标题。
2. 新增账号视图后，已打开页面仅改变 `#billing-return` 时不会执行启动逻辑，账单内容可能留在隐藏视图。现在监听 hashchange，通过当前账号与团队的生命周期检查打开账单并重新读取权威摘要，保留 Awaiting confirmation。初次打开的两个 fragment 仍优先于已保存项目恢复。
3. 账号刷新等待期间，下拉框可选择新团队，但全局 busy 会忽略切换。团队和项目选择现可开启新的操作并使旧请求失效；旧响应不能恢复之前的选择。新增延迟刷新测试先观察到失败，再通过修复。

## 自动验证

以下入口均已在最终源码运行通过：

```powershell
node --check src/static/app.js
node --check src/static/accounts.js
node --check src/static/git.js
node --check src/static/billing.js
node tests/web_session_regression.js src/static/app.js
node tests/account_ui_regression.js src/static/accounts.js
node tests/billing_ui_regression.js src/static/billing.js src/static/accounts.js
node tests/git_ui_regression.js
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_web.py -v
git diff --check
```

- WebTests：6 项通过，涵盖打包资源、MIME、安全头、资源白名单及 Node 回归。
- Billing：原有 29 个行为组通过，包含晚到付款响应、权限降级、团队／项目切换和 fragment 恢复。
- 账号新增检查：单视图展示、aria-current、同团队刷新保留视图、团队切换重置、管理者控件、初始及运行中的账单 fragment、浏览器标题、加载状态、刷新等待期间切换团队。
- 项目新增检查：清除筛选同时清空关键词和负责人，并返回搜索框焦点；已有状态分列、会话失效、晚到响应和卡片焦点回归继续通过。
- HTMLParser 检查：全部 ID 唯一，无嵌套或未关闭 form。

账号视图、页面标题、hashchange 与快速团队切换的新增断言均在修复前观察到失败。CSS 的外观变化通过真实浏览器截图和布局检查验收。

## 真实本机浏览器结果

使用 Playwright CLI、Chrome、独立随机端口 loopback 服务，所有账户与记录均为虚构。数据由真实 HTTP API 创建，无页面 API 响应模拟。原始证据、保留数据库和 browser profile 均位于 `.local/frontend-qa-20261011/`，不提交 Git。

服务成功运行的数据文件为 `qa-run3.sqlite3`。早期 seed 使用了不支持的工具名及未分派的请求，分别被实际 API 拒绝；两份失败数据库仍保留，没有删除或沿用失败结果。

已实际操作：

- 所有者和普通成员登录、退出，切换两支团队，进入项目，检查空项目团队。
- 账号四个视图及同团队刷新保留视图；普通成员隐藏项目创建、团队管理和付款操作。
- 新建项目、新建任务、搜索与负责人组合筛选、无匹配结果与清除、取消新建、创建成功后焦点恢复。
- 任务详情、Escape 关闭、焦点返回原卡片；团队现场、请求与约定内容、实际确认请求解决与批准约定。
- 仓库接入三块布局，本地配置展开；agent 模板的 TOKEN 占位符、关闭清空模板。
- 邀请范围初始不勾选，生成一个临时邀请，关闭后 secret DOM 清空；未发送给任何真实成员。
- 自托管显示 Unlimited 和实际用量，无付款按钮；初次及同页面 `#billing-return` 打开账单并显示服务端确认等待。
- 浏览器离线时保留任务与最后记录，重连后恢复同步并隐藏断线提示。
- reduced-motion 禁用入场动画；检查正文、次要文字、主按钮、导航及卡片辅助文字的色彩对比度，最低已检查组合为卡片时间文字 4.66:1，其余主要组合大于 5:1。

布局宽度检查：

| 页面 | 实测宽度 | 结果 |
| --- | --- | --- |
| 登录、任务看板 | 1440、1280、768、390、320px | document/body 宽度不超视口 |
| 账号四个视图 | 1440px 截图；1280、768、390、320px 尺寸检查 | 无文档横向溢出 |
| 团队现场、请求、约定、仓库 | 1440、390、320px | 无文档横向溢出 |
| 任务详情 | 桌面右侧面板；390、320px 全屏面板 | 无文档横向溢出，原生关闭与焦点正常 |

看板内部滚动是预期行为。最大长度样例包括长任务标题和路径；这些数据仍可在详情读取，不扩大文档宽度。

已人工查看登录、账号项目／成员／设置／账单、仓库、桌面看板与详情、手机看板与详情截图。最终重点截图为 `final-board-desktop.png`、`final-board-mobile.png`、`final-detail-desktop.png`、`hub-projects-mobile.png` 和 `login-mobile.png`。详细断言输出保留在 `flow-result.log`、`extra-result.log`、`actions-result.log`。

浏览器没有观察到未捕获脚本异常。首次未登录的 `/account/session` 401，以及人为离线检查中的 `/api/snapshot` 连接失败，是预期错误；Chrome 还提供了现有密码表单的 autocomplete 建议。

## 验收边界

本轮是本机前端和自托管 UI 验收。真实 GitHub App、Stripe、OAuth、公网及跨电脑验收沿用原有文档边界。没有修改后端授权、任务状态机、付款核验、数据库定义和 API 契约。

没有删除任何文件。维护文档与源码按阶段提交；凭据、浏览器配置、原始记录和数据库留在本机。
