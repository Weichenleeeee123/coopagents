# C2 账号中心的 Plan & billing

Task 4 最初在团队账号中心的项目列表后增加英文 Plan & billing 区域。2026-10-11 的整体前端完善将其移到独立 Plan & billing 视图，统一石墨色导航、浅色工作台和薄荷绿强调色；初始及运行中的账单 fragment 都会打开该视图，运行中重新读取权威摘要。该阶段不改动全站语言，不接入真实 Stripe 账号，也不声称完成生产付款或 C3 真实部署验收。最新界面证据见 [前端验收](frontend-validation.md)。

## 展示与授权

`GET /account/teams/{team_id}/billing` 是计划、实际用量、成员/项目上限、订阅状态、已付费期限和最近同步时间的来源。只有服务端确认的 `paid` 与计划结果用于展示 Team；URL fragment、浏览器 storage 和 Checkout 返回 URL 都不能设置付费权限。

自托管显示 Unlimited 和实际用量，隐藏付款操作。未启用订阅的云部署显示“Subscriptions are not enabled”，并按服务返回的无限容量展示，不伪装成已付费 Team。有效月付 Price 来自服务端验证结果；缺失或无效 Price 显示 Price unavailable 并隐藏 Checkout。已绑定客户的所有者仍可打开 Portal 和重试 Sync。只读成员可以查看价格与用量，没有 Checkout、Portal 或 Sync 操作，即使响应里的管理字段被错误设置，客户端也要求当前团队角色为 owner。

用量是活跃账号团队成员和绑定团队的项目。历史项目协作者不会自动算作团队成员；此阶段不扩大这一计费边界。界面不展示客户 ID、订阅 ID、CSRF 或原始 provider 错误，只显示允许的安全英文错误和所有者可见的 test/live 提示。

## 生命周期与付款跳转

`accounts.js` 在所有账号失效、退出、团队切换和项目选择路径中先调用可选 `CrewmeshBilling.clear()`。团队加载独立启动 `load({teamId, role, request, isCurrent})`，不会等待 Billing 完成才加载项目或成员。Billing 复用账号 Cookie、CSRF、401 会话复查和 AbortController；其请求允许 60 秒，其他账号请求仍为 10 秒。

模块在自己的 mount generation 与账号 epoch 同时有效时才渲染、显示错误、开始动作或跳转。等待 provider 时只禁用 Billing 按钮，账号退出及团队切换仍可用。旧 fetch、旧 JSON body 和旧付款 URL 无法恢复新账号的界面或触发跳转。

Checkout 与 Portal POST 均发送严格空对象。Sync POST 后重新 GET 带 verified Price 的完整摘要，不使用缺少 Price 的 Sync 返回对象代替展示数据。只有对应 kind 的 `https://checkout.stripe.com` 或 `https://billing.stripe.com`（含显式默认 443）可作为目的地；原始 URL 先拒绝空白、控制字符、反斜杠、非精确主机、凭据、非默认端口及过长值，再通过 URL parser 检查。Checkout 保留 Stripe 的 opaque fragment，Portal 拒绝 fragment。Checkout 可按服务端决定返回已有订阅的 Portal。

`/#billing` 显示 Billing 区域；`/#billing-return` 显示 Awaiting confirmation，并进行当前账号授权的 GET。两个 fragment 的启动路径优先保留已授权的团队账号中心，即使标签页保存了当前项目也不会自动进入项目并清空 Billing；普通启动仍恢复获授权的已保存项目。付款仍由服务端确认，用户可以手动 Sync。界面无前端 paid setter，也不保存 Billing 凭据或付费状态。

## 金额与可访问性

金额为 Stripe charge 的 minor units。BIF、CLP、DJF、GNF、JPY、KMF、KRW、MGA、PYG、RWF、VND、VUV、XAF、XOF、XPF 不除以 100；ISK 和 UGX 的 API charge 表示仍除以 100。HUF、TWD 按 charge 两位小数处理，不采用 payout 规则或 Intl 的默认 currency digits 推断。仅正 safe integer、三位小写币种及月付 interval 才可格式化。参考规则见 [C2 Stripe 核验](c2-stripe-reference.md)。

区域使用英文 `lang="en"`、h2、命名 landmark、aria-busy、status live region、alert、原生按钮和可见键盘焦点。数据使用 textContent；无外部字体或新增网络资源。用量和操作在窄屏纵向排列并允许换行。

## 本机验证证据（2026-10-11）

- `node --check`：app.js、accounts.js、billing.js 均通过。
- 原有 account_ui_regression.js 和 web_session_regression.js 均通过。
- billing_ui_regression.js：29 个行为组通过，覆盖实际用量、角色、禁用部署、7 种 charge 金额表示、无效 Price、fetch/JSON/错误/跳转的失效保护、独立失败、合法会话中的拒绝、Sync 重新 GET、fragment、危险目的地和已有订阅 Portal。Portal 对原始 URL 中任何 literal `#`（包括空 fragment）都拒绝；直接 Portal 与 Checkout 返回 Portal 的两个路径均观察到修复前失败。所有者被降级后，Checkout 的 401 拒绝不会导航或退出有效会话，刷新团队后移除付款操作。真实 accounts+billing 模块在带有已保存项目的两个 Billing fragment 下均观察到修复前自动进入项目、清空 Billing 的失败；修复后授权 GET、Free 状态及返回确认提示保留，同时普通项目恢复行为通过。
- test_web.py：6 项通过；包含 Billing 的资源 MIME、packaged bytes、CSP 与 nosniff、固定白名单和三个浏览器回归入口。pyproject.toml 现有 `static/*.js` 会打包 Billing 模块。
- `test_account*.py`：26 项通过，覆盖账号 HTTP、Cookie/CSRF、恢复、凭据和会话撤销。

Playwright CLI 使用保留的独立 profile，真实随机端口 loopback 服务、数据库和日志都位于 `.local/c2-ui-qa-20261011-792a/`。实际服务完成首账号 bootstrap、账号登录、所有者团队切换、成员登录：Primary 为 2 位成员/1 个项目，Secondary 为 1 位成员/0 个项目；自托管均显示无限容量且没有付款按钮。`browser-actual-state.log` 记录真实成员状态。

配置云 UI 使用仅存在于本机 QA 的 Playwright response routes。USD 1.50 是合成测试 fixture，绝非实际销售价格或 Stripe 验证结果。合成界面覆盖所有者操作、只读成员防护、未启用订阅云状态；延迟合成 Checkout 在团队切换/退出之后返回，不触发导航。`browser-cloud-disabled.log` 记录禁用云状态。390px 和 320px document width 分别为 390/320，无横向溢出。浏览器 Console 唯一 error 是首次未登录 `/account/session` 的预期 401，无脚本异常。

人工查看过的截图：

- `selfhost-desktop.png`：真实自托管所有者，1280×1000。
- `selfhost-member-mobile-actual.png`：真实自托管成员，390px。
- `cloud-fixture-desktop.png` / `cloud-fixture-mobile.png`：合成配置云 UI，1280px / 390px。

早先 `selfhost-member-mobile.png` 的名称不准确，内容仍是合成云 fixture；它保留作为原始证据，真实自托管移动截图以 `-actual` 结尾。服务仅通过自己的 stop.flag 优雅停止；数据库、profile、截图、日志及原始证据全部保留，不删除文件。

## 与 Git 接入并行阶段的源码合并

Task 4 与远端 `ce2efa1` 的 Git 接入成果合并时，四处冲突按功能并存解决：CI 同时检查 Billing/Git 脚本及各自回归；固定静态白名单同时提供 billing.js/git.js；页面脚本顺序为 git → app → billing → accounts；CSS 保留两套按区域限定的样式。账号中心 Billing、项目仓库接入、GitHub worker 与 Billing worker 均保留，自动合并的共享 lifespan 无额外改动。test_web 的资源覆盖增加 Git 资产，MIME/CSP/packaged bytes 仍逐项验证。

合并后本机检查：4 个 JS syntax、Git UI / 原有 session / account UI / Billing 29 个行为组回归均通过；`test_git*.py` 73 项（含 Git+Billing 双 worker 与授权 API 集成）、test_web 6 项、MCP 3 项、repositories 7 项均通过。证据保留于 `.local/c2-ui-merge-{git,web,mcp,repositories}-20261011-792a.log`。现有环境已安装声明的 PyJWT 2.15.1 和 cryptography 50.0.2，无新增安装步骤。此源码合并不增加真实 GitHub/Stripe 外部账号或部署验收声明。
