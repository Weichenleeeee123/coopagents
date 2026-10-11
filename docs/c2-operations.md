# C2 候选版配置与运维

0.4.0rc1 是代码与测试候选版。用户尚无本阶段的 Stripe 账号，当前没有真实 Price、付款、外部 webhook 或 OAuth 回调证据；C3 官方运营验收保持暂停。全部源码维持 MIT；完整自托管不需官方账号、Stripe、联网许可或付费密钥。候选版事实见 [C2 报告](commercial-c2-report.md)，API 和 CLI 细节见 [HTTP 契约](c2-http.md)，提供方依据见 [Stripe 核验](c2-stripe-reference.md)。

## 模式与配置目录

| 模式 | 账号登录 | 订阅与容量 |
| --- | --- | --- |
| 默认 `self-hosted` | 本地账号、bootstrap 初始化和邀请 | Unlimited、实际用量；忽略 billing 配置，不读取 Stripe 文件或访问提供方 |
| `cloud`，所有 billing 变量均不存在 | 配置后的 GitHub 账号 OAuth | Unlimited；未启用订阅，无 Checkout/Portal、webhook 或支付 worker |
| `cloud`，完整 billing 配置 | 独立 GitHub 账号 OAuth | Free / Team 明确限额，固定 Team 月付 Stripe Price；服务端规范核验付款 |

任何 billing 变量存在就必须完整配置，不能通过空值或半套 test/live 配置“禁用”。要运行无订阅 cloud，保留账号 OAuth，确保全部 billing 环境变量不存在。`.env.example` 的 billing 示例全部注释，默认 Compose 不要求 GitHub 或 Stripe secret 文件。

`compose.github.yaml` 是独立只读 GitHub App，用于仓库绑定、PR/check 和 GitHub webhook；它的 App client secret、RSA key、signing secret 与账号 OAuth 无关。可单独加载，也可与 billing 覆盖文件并用；不能把 App 凭据填作账号 OAuth 凭据。

## 启用前准备与启动

先完成 [默认部署](deployment.md)：DNS、HTTPS origin、bootstrap 文件和持久卷。可选受版本控制的 `deploy/compose.cloud-billing.yaml` 强制 `cloud`，保留基础 Compose 的 bootstrap 挂载；cloud 不开放账号 bootstrap，该挂载不用于 cloud 账号初始化。仍须保留实际存在且可读取的 bootstrap 文件，以满足基础 Compose 挂载。

在提供方注册**账号 GitHub OAuth App**，精确回调为 `https://你的域名/account/oauth/github/callback`。在服务器受保护文件保存 OAuth client secret。Stripe merchant/account 注册、资格与实际销售价格由运营方完成；本候选版不预设金额。不要用测试 fixture 作为销售价格或有效密钥。

| 未提交 `.env` 配置 | 覆盖文件传给服务的配置 |
| --- | --- |
| `CREWMESH_GITHUB_CLIENT_ID` | 同名账号 OAuth client ID |
| `CREWMESH_GITHUB_CLIENT_SECRET_PATH` | 挂载后 `CREWMESH_GITHUB_CLIENT_SECRET_FILE` |
| `CREWMESH_BILLING_MODE` | 明确 `test` 或 `live` |
| `CREWMESH_STRIPE_SECRET_KEY_PATH` | 挂载后 `CREWMESH_STRIPE_SECRET_KEY_FILE` |
| `CREWMESH_STRIPE_WEBHOOK_SECRET_PATH` | 挂载后 `CREWMESH_STRIPE_WEBHOOK_SECRET_FILE` |
| `CREWMESH_TEAM_MONTHLY_PRICE_ID` | 匹配模式的实际 `price_` ID |
| `CREWMESH_FREE_MEMBERS` / `CREWMESH_FREE_PROJECTS` | Free 活跃账号成员 / 绑定项目上限 |
| `CREWMESH_TEAM_MEMBERS` / `CREWMESH_TEAM_PROJECTS` | Team 活跃账号成员 / 绑定项目上限 |

四项容量必须为 `1..1000000000` 正整数，Team 每项至少覆盖对应 Free 项，无默认数值。服务支持每项 secret 的直接环境变量或 `_FILE` 二选一；覆盖文件只使用 `_FILE`，不能同时添加直接值。Stripe key 前缀须对应 `sk_test_` / `sk_live_`；endpoint signing secret 为 `whsec_`，须来自对应模式、对应 endpoint。每个 secret 文件最多 4096 ASCII bytes，可带末尾换行。任何 secret 都不能进入 YAML 值、命令参数、URL、聊天、Git 或公开日志。

Linux 限制密钥目录访问，例如目录 `700`，目录内文件可用 `644` 使 UID 10001 经 Compose 只读挂载后读取；也可使用正确所有权/ACL 和更严格文件权限。必须实际确认 UID 10001 可读，不能仅设 `600` 给宿主用户然后假定容器可读。Compose 本地 secrets 不会自动改变宿主所有者。Windows 同样限制父目录 ACL 并检查容器读取。保留所有密钥和证据，不执行文件或卷清理。

```bash
docker compose --env-file .env -f compose.yaml -f deploy/compose.cloud-billing.yaml config --quiet
docker compose --env-file .env -f compose.yaml -f deploy/compose.cloud-billing.yaml up -d --build
docker compose --env-file .env -f compose.yaml -f deploy/compose.cloud-billing.yaml ps
```

如启用只读 GitHub App，所有命令再加 `-f compose.github.yaml`，同时准备该文件要求的独立 App 凭据。配置检查缺任一必填变量即失败，不需要 Docker Engine；它只校验 Compose，不能证明文件权限、服务启动、Price 或提供方可用。服务启动仅校验本地语法和完整性；Price 在摘要/Checkout 请求中懒验证。候选版不能因启动成功而标成生产支付通过。

## Price、Checkout 与 Portal

使用真实、active、固定 `per_unit` 正整数 `unit_amount`、monthly interval/count=1、`licensed` Price，无 `transform_quantity`，单个 subscription item / quantity=1。限额和 Price 都由服务配置，浏览器不能传入 Price、Customer、Subscription、数量或返回地址。UI 金额为规范 Price 的实际 base currency/minor units，零额、metered、tiered、数量转换等不支持。Checkout 显式发送 base currency 并关闭 Adaptive Pricing；已有其他币种 session 不被自动收养。

在 Stripe 相应模式配置默认 Customer Portal：只允许更新付款方式和取消订阅，关闭 Price/quantity 切换；首版不支持试用、折扣券、促销码、credits、零总额 invoice、proration 套餐切换或外部 payment record。不要在 Dashboard/Portal 打开这些能力后假定账本能授权 Team。取消可按已付期间末尾执行；即时取消经规范同步后为 Free。适配器仅创建 Portal session，不替运营方修改 Portal Dashboard 配置。

Checkout 成功回跳 `/#billing-return` 仅显示等待确认，不能授权付费。Team 需要规范 current active subscription、配置 Price、quantity=1、当前完整月付 invoice 与可完整归属的实际付款、未过期 paid period 且无 risk hold。`past_due` / `unpaid` / `canceled` / `paused` / `pause_collection` 等经规范同步为 Free；period-end cancellation 在已核验期间结束前保留 Team。全额退还当前 invoice 或当前 charge 存在 unresolved/lost dispute 会 hold；部分退款、历史期退款/争议不冻结新的已付期。付款证据不足不会新授予 Team，失败保留之前核验的快照。

容量统计 active 团队账号成员与绑定团队的项目，创建/接受邀请/恢复成员/绑定项目等在同一写事务检查容量；pending 邀请不占 active 名额。降级保留已有成员、项目、任务和历史数据，超限时阻止新增，仍允许减少使用量及正常协作。历史项目协作者与团队账号成员是不同边界，不会自动计为付费账号；C2 不把旧协作者升级成团队成员。

## 注册 webhook 与持久重试

在匹配 test/live 模式注册 `POST https://你的域名/billing/stripe/webhook`，endpoint API 版本与请求头固定为 `2026-09-30.endive`。保留原始请求 bytes 与唯一 Stripe-Signature；签名 HMAC 校验先于 JSON 解析，不能在代理中重序列化 body。HTTP 限制 64 KiB，Host/可选 Origin、禁止 query 和重复签名头的边界仍有效。仅 enabled cloud 挂载此路径；禁用部署的未知路径进入现有 authenticated MCP 回退，匿名请求先得到 401，持有有效 agent bearer 的请求通过认证后得到 404。两者都不接受 Stripe 事件，不需增加公开回退路由。

目前处理的事件族来自 `BillingService._supported`，签名 object ID 前缀映射见 `stripe_billing.verify_event`：

| 在 endpoint 选择提供方实际提供的事件族 | 规范读取 |
| --- | --- |
| `customer.subscription.*` | subscription 与当前 invoice/payment |
| `invoice.*` | invoice 所属 customer 的当前订阅 |
| `checkout.session.*` | Checkout 与绑定订阅 |
| `charge.refunded` | 当前 charge/refund evidence |
| `refund.*` | refund 关联 charge |
| `charge.dispute.*` | dispute 关联 charge |

配置 Dashboard 时选取这些族中实际提供的 event names，涵盖订阅变更、付款失败/成功、Checkout 完成/过期、退款与争议变更；这里的 `*` 表示源码前缀，不能当作任意单条 event name。有效未知事件持久入队后 ignored。事件 ID 去重，事件时间不决定权限；worker 重查当前 provider objects，不能用迟到事件恢复旧 paid 状态。仅在持久化成功后响应 received；200 不是付款授权证据。

worker 每次领取一个 durable event，lease 为 120 秒；失败 backoff 从 30 秒倍增至最多一小时，restart 保留 attempts、next_attempt 和 lease。出站 customer、Checkout、Portal 的随机 idempotency key 在调用前落库；不确定结果沿用原 key，不能因本地超时或 lease 到期新建 key。Stripe 至少保留 idempotency key 24 小时；未知创建达到 24 小时后只能通过完整有界规范查询恢复，未找到或多重匹配 fail closed。Portal 无规范 session retrieval，不确定旧 Portal 达到 24 小时为 `uncertain_portal`；现有 CLI 不能人为解锁该状态，须保留账本并调查。

默认 provider 单请求 5 秒、一次 operation 45 秒 / 64 请求、list 最多 4 页；customer/Checkout recovery 最多 400 条，超过边界或页不完整 fail closed。SQLite busy timeout、排队和本地逻辑增加整个操作时间。应用关闭等待自己持有的 BillingService/database/executor jobs；操作系统 DNS/TLS 中的 bounded daemon helper 可能在超时后结束，不能宣称全部底层网络已被取消。DNS 迟到时 deadline 检查阻止再发 POST；已经发出的请求仍可能在远端完成，因此必须保留稳定 key，重启后规范恢复。

## 本地维护与失败定位

先检查安全错误码、最近同步时间、到期 pending jobs 和存储/网络状态，避免打印原始 provider bodies、cookie、密钥或全部环境。owner 的 Sync 与当前 worker 同样按规范数据核验，不接受手填 paid 状态。没有人工 grant/set-paid、任意 customer binding、删除 ledger 或 reset keys 的管理入口。

维护 CLI 只连接已有 C2 数据库，验证已有 schema/catalog/provider mode；验证阶段不写 SQL，每次连接使用 SQLite `mode=rw`，错误路径或文件随后消失不会新建数据库。不开初始化/迁移/reset。使用完整部署参数和独立保留容器名称执行：

```bash
docker compose --env-file .env -f compose.yaml -f deploy/compose.cloud-billing.yaml run --no-deps --name crewmesh-billing-retry-20261011-01 app python -m crewmesh.billing_admin --database /data/crewmesh.sqlite3 retry --max-jobs 25
docker compose --env-file .env -f compose.yaml -f deploy/compose.cloud-billing.yaml run --no-deps --name crewmesh-billing-reconcile-20261011-01 app python -m crewmesh.billing_admin --database /data/crewmesh.sqlite3 reconcile --max-teams 100
```

每次选新名称，保留维护容器。上限必须为 `1..1000`。retry 只处理到期工作，失败停止本轮，不忙循环未来 backoff；reconcile 按 team ID keyset、全局上限遍历已有 customer bindings，只做规范读取并可 expire 本地保存、已验证 open 的竞争 Checkout，不创建 customer/Checkout/Portal。原始事件与 outbound key 保留。

CLI 只输出 attempted/succeeded/failed 计数：0 成功（包括无到期工作），1 处理失败或意外错误，2 配置、数据库、schema/catalog、参数或上限无效。并发 worker 抢先领取 lease 可导致本次尝试无进展，未来重试。详见 [HTTP/维护 CLI 契约](c2-http.md)。

## 备份、恢复与 catalog 变更

[一致备份](deployment.md#一致备份)必须包含整个数据库：账号、workspace、catalog、customer bindings、subscription、webhook jobs、lease、audit 以及全部 outbound/Checkout idempotency keys。不能只备份业务表，不能靠删除账本、重新生成 key 或改时间恢复付款。生产备份与密钥保存在受保护独立介质，原数据库、失败部分文件、容器和卷全部保留。

恢复到新路径，先保留并停止原 app，再用相同 mode、origin、catalog 和提供方凭据启动恢复实例；不要让两个恢复实例并行写入同一账本。恢复后轮换可能重新有效的账号/agent 凭据，核对授权与任务，运行 bounded canonical reconcile，并按到期 backoff retry。恢复不会撤销备份之后已在 Stripe 完成的请求；旧 key/绑定提供恢复依据。真实 backup/restore 与远端状态对照属于待做的 C3 外部验收。

catalog 内容会持久存储并参与 fingerprint。不要静默换 test/live 或将新 Price ID 当作原订阅；服务的 mode/binding 校验及 CLI 已存在同 catalog 校验会拒绝不兼容状态。容量/Price 改动前备份并规划迁移、订阅一致性及恢复，首版不提供 Dashboard 套餐切换迁移命令。

## 验收边界与暂停点

代码验收覆盖权限、Cookie/CSRF、签名 bytes、重复/乱序事件、backoff/lease、旧 key 恢复、退款/争议、事务容量竞态与 Git/Billing 共存。`scripts/deployment_smoke.py` 使用真实 Docker/Caddy 私有 CA 的默认自托管 TLS，覆盖无限容量、实际用量、拒绝付款、未挂载 webhook、Billing/Git 资产、restart 和新路径 backup/restore；Engine 不可用必须记录失败，历史通过不能代替当前候选版运行。

真实验收须有运营方提供的 Stripe test account/Price、相同版本 webhook endpoint、GitHub OAuth callback 与公网域名：检查实际 Checkout/Portal、签名外部投递、重复/延迟/重试、付款失败、取消、当前退款/争议、容量边界及恢复后的账本一致性；test 验收通过后再按明确运营决定配置独立 live 对应值。本阶段没有这些账号，不制造付款数据，不启动实际 Stripe 或官方部署。C3 暂停；原生 Codex MCP、双机/公网和真实 GitHub App 的既有缺口仍见对应报告。
