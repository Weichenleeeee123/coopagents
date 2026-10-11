# C2 billing HTTP 与本地维护

本阶段把已有账本、Stripe adapter 与账号权限接入正式 HTTP。支付凭据尚未提供；验证使用真实 SQLite、随机端口 HTTP 和测试范围内的 Stripe transport fixture，不代表真实 Stripe 或生产 TLS 验收。C3 部署仍待后续阶段。

## 配置

`create_app(..., billing_config=None)` 不读取环境变量。self-hosted 和未配置 billing 的 cloud 显示 `unlimited`，限额为 `null`，不构造 Stripe client、不启动支付 worker、不挂载 webhook。self-hosted 即使传入 enabled typed config 也保持此行为。

`python -m crewmesh.server` 在 cloud 模式加载完整配置：

| 环境变量 | 含义 |
| --- | --- |
| `CREWMESH_MODE` | `cloud` |
| `CREWMESH_PUBLIC_URL` | 无路径、查询或片段的规范 HTTPS origin |
| `CREWMESH_BILLING_MODE` | 明确的 `test` 或 `live` |
| `CREWMESH_TEAM_MONTHLY_PRICE_ID` | 固定 Stripe monthly Price ID |
| `CREWMESH_FREE_MEMBERS` / `CREWMESH_FREE_PROJECTS` | Free 正整数限额 |
| `CREWMESH_TEAM_MEMBERS` / `CREWMESH_TEAM_PROJECTS` | Team 正整数限额，覆盖 Free 限额 |
| `CREWMESH_STRIPE_SECRET_KEY_FILE` | 受保护 secret key 文件，mode 必须匹配 |
| `CREWMESH_STRIPE_WEBHOOK_SECRET_FILE` | 受保护 signing secret 文件 |

Secret 也支持对应的无 `_FILE` 环境变量；每项只允许一种来源。凭据不进入命令参数、Git 或日志。cloud 部分配置缺项即启动失败；self-hosted 不读取 billing secret 文件。启动没有 Price 网络请求，Price 在请求期间验证。

## HTTP 契约

| 方法与路径 | 行为 |
| --- | --- |
| `GET /account/teams/{team_id}/billing` | active 成员读取 plan、usage、limits、状态和规范 Price；仅 owner 得到内部 billing 字段。 |
| `POST /account/teams/{team_id}/billing/checkout` | owner，严格空 JSON `{}`；创建或恢复 Checkout，已有订阅时返回 Portal。 |
| `POST /account/teams/{team_id}/billing/portal` | owner，严格空 JSON `{}`；返回验证过的 Stripe Portal URL。 |
| `POST /account/teams/{team_id}/billing/sync` | owner，严格空 JSON `{}`；规范同步并返回账本摘要。 |
| `POST /billing/stripe/webhook` | 仅 configured cloud 存在；验证原始签名，持久化最小事件后 `200 {"received":true}`。 |

账号接口要求唯一 `crewmesh_account` cookie；Bearer 不能替代账号。POST 还要求唯一且精确匹配的 Origin 与 X-Crewmesh-CSRF，Content-Type 为 application/json。未知字段、客户端 Price/Customer/Subscription ID 和返回地址不接受。权限拒绝为 401，不清除仍有效的 cookie；disabled owner POST 为 409，非 owner/其他团队仍先拒绝权限。provider 失败为安全的 `503 BillingUnavailable`，容量满为 `503 Busy`。没有付款修改调试接口。

仅精确 enabled webhook POST 路径跳过全局 JSON 预解析，先验证签名再解析。Host、存在的 Origin、禁止 query 和实际 body 64 KiB 限制仍生效，重复 Stripe-Signature 被拒绝。webhook 不需要 cookie、Origin 或 CSRF；若带 Origin 仍需被边界接受。有效未知事件及未绑定团队的规范 customer 持久入队后 ignored；重复事件不重复应用付费状态。

## Worker 与退出

每个 app lifespan 一个 worker。账号 provider 操作独立两线程、两份容量；webhook ingestion 独立两线程、两份容量；worker 独立一线程。超额 HTTP 请求直接 Busy。worker 恢复 pending 事件、遵守 backoff 和未过期 lease、重新领取已过期 lease。处理成功后让出事件循环，空闲等待 250 ms。

provider 阻塞 I/O 全部在线程执行；health、项目读取、普通账号和 MCP 不争用这些线程。worker 意外异常只写固定安全日志，保留 durable lease 并继续。退出设置自身 stop，等待 owned BillingService/database 作业并关闭自身 executor；反复取消也不会提前释放在执行中的容量或遗留退出后的数据库写入。

Adapter 限制请求超时、页数、请求数和 operation 时间。SQLite busy timeout 和线程调度额外耗时，所以默认 provider 45 秒预算不是整个方法或退出的 45 秒硬上限。取消 await 无法杀死阻塞 thread，退出等待所有 owned BillingService/database/executor work。实际 HTTPS transport 使用最多 16 个 daemon helper 限制调用者等待时间；超时后，阻塞在操作系统 DNS/TLS 的 helper 可能仍在后台结束，退出不等待无法设硬上限的 OS DNS。DNS 迟到时，发送请求前的 deadline 检查禁止再发 POST；若请求已经发送，远端仍可能完成。helper 不写数据库，稳定的本地 idempotency key 保留，下一次启动通过同一 key 与规范 provider 查询恢复不确定结果。

## 维护 CLI

CLI 只打开已有、具有 C2 所需表和列、已存在相同 catalog 与 provider mode 的数据库。每个连接都使用 SQLite URI `mode=rw`，错误路径或验证后文件消失不会创建数据库。初始化只读验证并接线已有账本对象，不执行 CREATE、迁移、删除、清空、VACUUM 或 reset。维护权限来自对本地数据库及受保护 cloud 配置的持有。

设置上述受保护环境后执行：

```powershell
& .\.venv\Scripts\python.exe -m crewmesh.billing_admin --database .local/crewmesh.sqlite3 retry --max-jobs 25
& .\.venv\Scripts\python.exe -m crewmesh.billing_admin --database .local/crewmesh.sqlite3 reconcile --max-teams 100
```

上限只能为 `1..1000`。retry 只执行到期 durable jobs，失败后停止本次运行，不忙循环未来 retry；再次运行沿用 backoff。并发 worker 可能抢先领取 lease，维护尝试因此无进展时计为失败。reconcile 按 team ID keyset 分页，受整个运行 max-teams 上限约束，只使用已有 server customer binding，不创建 customer、Checkout 或 Portal。仅当账本保存的竞争 Checkout 通过规范验证且仍 open 时，可将其 expire，避免重复付费。CLI 不接受 provider ID、任意 team ID、付款状态或 secret 参数。

输出只含 attempted、succeeded、failed 计数。退出码：0 本次成功（包括无到期工作），1 处理失败或意外故障，2 配置、数据库、schema/catalog 或上限无效；未知参数也为 2。输出没有 provider IDs、原始 provider 错误、凭据或响应正文。失败证据留在账本，可在未来 retry 或 lease 到期后恢复。

## 验证边界

`tests/test_billing_api.py` 使用真实随机 loopback 端口、显式规范 Host 与 fixture cookie。底层仍为 HTTP，不宣称验证 TLS 或浏览器 Secure cookie 传输。覆盖角色、跨团队、cookie/Origin/CSRF、空 JSON、foreign provider URL、原始签名和重复 header/body/query、持久化先于响应、无关事件忽略、独立容量、restart/backoff/lease、worker 意外故障及等待 owned service work 退出。额外使用真实 https_transport（仅 patch 物理 HTTPSConnection）验证超时后 bounded daemon 可残留、late DNS 不发 POST、不再写数据库，且下一次启动复用已持久化的 customer key。

`tests/test_billing_admin.py` 覆盖错误路径不建库、无关库不修改、schema/catalog 拒绝、验证后文件消失、bounded retry、keyset 全局上限、已有 binding 规范同步、竞争 Checkout expiry 和安全输出。唯一 SQLite 全保留在 `.local/c2-http-tests/`、`.local/c2-admin-tests/`，不提交 Git。
