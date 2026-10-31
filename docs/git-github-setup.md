# GitHub App 远端交付证据

G2 使用独立 GitHub App 读取已授权仓库。现有 GitHub 账号登录继续负责登录；登录 OAuth 的 client ID、secret 不能代替此 App 配置。未配置 App 时，本地 Git 功能仍可使用；部分配置会拒绝启动，避免看似接入但没有校验。

## App 与运行配置

在 GitHub 注册 App，给 Repository permissions 中的 Contents、Pull requests、Checks、Commit statuses **Read-only** 权限；Metadata 为必需的只读权限。只安装到操作者选择的仓库。显式订阅 Push、Pull request、Check run、Check suite、Status、Release 六类事件；Installation 与 Installation repositories 是自动投递的安装生命周期事件，不应写入 Manifest 的 `default_events`，GitHub 注册页面会拒绝这两个显式订阅。Release webhook 只触发重新读取，不使用事件正文作为交付证据。设置 webhook secret，Webhook URL 为 `https://你的服务域名/api/git/github/webhook`，用户授权 Callback URL 为 `https://你的服务域名/api/git/github/callback`。这是用户授权回调，不是安装完成后的 setup URL。

服务配置如下。真实值和私钥文件放在部署机配置或 secret mount，不放进版本库、命令行参数或网页。

| 环境变量 | 内容 |
| --- | --- |
| `COOPAGENTS_GITHUB_APP_ID` | 数字 App ID |
| `COOPAGENTS_GITHUB_APP_CLIENT_ID` | 此 GitHub App 的 client ID，区别于数字 App ID 和登录 OAuth client ID |
| `COOPAGENTS_GITHUB_APP_CLIENT_SECRET` | 此 App 的用户授权 secret |
| `COOPAGENTS_GITHUB_APP_PRIVATE_KEY` | App 的 RSA PEM 私钥，至少 2048 位 |
| `COOPAGENTS_GITHUB_WEBHOOK_SECRET` | 与 GitHub webhook 配置相同的 secret |
| `COOPAGENTS_GITHUB_APP_CALLBACK_URL` | HTTPS `/api/git/github/callback` 完整 URL；省略时从 public origin 推导 |

client secret、private key、webhook secret 均支持同名追加 `_FILE` 的文件来源，例如 `COOPAGENTS_GITHUB_APP_PRIVATE_KEY_FILE`。直接值与文件不能同时提供；每个文件最多 65536 字节。配置错误只返回通用错误，不回显文件内容。`.[service]` 明确安装 PyJWT 的 crypto 支持，固定发行依赖包含 cryptography 和 httpx2。

Compose 部署时按 `.env.example` 的注释设置 App ID、client ID 和三个本机 secret 文件路径，再运行 `docker compose --env-file .env -f compose.yaml -f compose.github.yaml up -d --build`。该扩展只挂载指定 secret，不把密钥复制到镜像。基础 `compose.yaml` 不配置 App 时仍正常运行；callback 从 `COOPAGENTS_PUBLIC_URL` 推导。

## 网页授权与关联

项目管理员先绑定 `github.com/owner/repo`。网页以当前项目 web bearer 调用 `POST /api/git/github/authorize`，请求体 `{}`，可选 `installation_id` 为正整数；响应返回 `state` 与 GitHub `authorization_url`。浏览器前往该 URL 授权，GitHub 回调后返回网页，由同一发起者调用 `POST /api/git/github/finish`，请求体 `{"state":"授权响应里的 state"}`。

state 最长 10 分钟且只能完成一次；回调验证用户确实能读取该安装内的绑定仓库，同时通过 App JWT 验证 installation 属于此 App。回调仅保存候选 installation/repository ID，不直接连接项目。finish 再检查当前项目管理员身份、发起者、GitHub 用户仓库权限和安装权限；被降权、会话撤销或权限失效时拒绝完成。用户 GitHub token 仅在进程内保留到 finish 或 state 过期，不写数据库。服务在回调与 finish 之间重启时需重新授权。部署应让这两个请求到达同一进程；本轮未实现跨进程用户 token 共享。

任务负责人 agent 或项目管理员 web 可调用 `POST /api/git/github/link`，请求体可包含 `{"task_id":1,"branch":"feature"}`、`{"task_id":1,"pr_number":7}`、`{"task_id":1,"commit_sha":"完整的小写提交 SHA"}` 或 `{"task_id":1,"release_id":42}`。一次只能提供一种关联。Release ID 必须来自绑定仓库的发现结果；Release 与任务显式多对多关联，不按 tag、日期、提交或正文推断。发现最近最多 20 条 Release；每条最多返回 20 项资产的名称、大小和 digest，不读取 release notes 或任意下载 URL。明确关联的 Release 即使不在最近一页也会按 ID 单独核验。关联状态区分草稿、预发布、已发布和不可用；发布不代表任务验收。Coopagents 不创建、不编辑、不发布 Release。提交必须是完整 40 或 64 位十六进制 SHA，独立于分支/PR 建立关联。一个任务可以关联多个对象与多个不可变提交；新增关联表以增量方式保留既有记录。没有明确关系的 PR 放入待关联列表。分支关联只匹配授权仓库本身的当前分支和完整提交 SHA；fork 的同名分支不能自动匹配，须明确关联 PR number。管理员之外的 web 成员不能建立关联。

成员调用 `POST /api/git/github/refresh`，请求体 `{}`，重新读取当前仓库、分支、PR、明确关联提交，以及各自 SHA 上的 checks/statuses。分支仅有 push、尚未创建 PR 时也会读取检查。路径和 JSON 字段严格校验；不接受凭据、provider URL 或调用方声称的合并结果。

## 队列与同步语义

webhook 对最多 65536 字节的原始请求体使用 HMAC SHA256 和常量时间比较；重复 signature/delivery/event headers 拒绝。SQLite 先持久化 delivery ID、原始负载 hash、event、installation/repository ID，再返回接受结果；不保存 webhook 正文。相同 delivery 与相同负载幂等；相同 ID 不同负载返回冲突。未支持的签名合法事件忽略。

服务 lifespan worker 每 5 秒读取 `process_pending()`，每 5 分钟调用 `reconcile_all()` 补偿遗漏事件；网页手动 refresh 用于立即核对。网络故障按指数延迟重试，常规退避上限 1 小时；限流采用 `Retry-After` 或配额 reset 的截止时间，次级限流至少等 60 秒，单次延迟上限 24 小时。安装冷却期写入 SQLite，重启、其他事件、周期同步和手动 refresh 都不能提前请求。正文说明的次级限流不会误判为权限撤销。旧 webhook 和乱序事件不直接写入 PR 或 HEAD 结果。同步先保留 revision，网络请求在数据库锁外完成；仅 revision 仍相同的响应可以落库。

`process_pending(limit=20, should_stop=None)` 与 `reconcile_all(should_stop=None)` 接受停止回调。worker 关闭时在每个事件和项目之间停止；一个安装事件若只处理了部分项目，其 inbox 状态仍为 queued/retry，重启后继续核对，不提前标记完成。当前已开始的仓库请求受操作与响应读取预算约束。

REST origin 固定为 `https://api.github.com`，API 版本为 `2026-03-10`；用户 code 仅向 `https://github.com/login/oauth/access_token` 交换。禁止所有重定向；每个请求超时最多 15 秒，每个 JSON 响应最多 2000000 字节。每次仓库核对最多 150 个请求，并使用 60 秒操作截止时间，后续请求超时受剩余时间约束，读取响应块时也检查截止时间。授权范围查询可分页，最多 100 页、每页 100 个对象；交付核对不扫描全部历史 PR。安装 token 明确限制到单个稳定 repository ID 和所需只读权限，并校验 provider 返回的 repositories/permissions；缺少范围信息、额外仓库或写权限均拒绝使用。超出界限的同步会失败，不把不完整内容当成完整的验证结果。

未关联 PR 发现只读取最近更新的最多 50 个**开放** PR 摘要；Release 发现读取最近最多 20 条。两者都不继续翻页；`github_discovery` 返回各自的 limit/truncated 信息，满页表示可能还有未扫描对象。明确关联的 PR（包括已关闭或已合并的 PR）及 Release 单独读取当前详情。与已关联 base 分支及当前 SHA 相符的开放 PR 会核对详情；此前已匹配的 PR 也会再次读取以确认关闭/合并，不沿用旧状态。一个项目最多保存 100 个分支、PR、提交和 Release 关联，重复已有关系保持幂等。

每个 SHA 的检查与 status 各只读最新最多 100 项，返回 `checks_truncated`、`statuses_truncated`。任何截断结果都不能证明整个检查集合通过；未扫描检查的 PR 使用 `checks_verified=false`。每次保存的交付/待关联证据 JSON 总量最多 450000 字节，整个 GitHub 快照最多 500000 字节；超过预算时拒绝新同步，保留上次结果及原同步时间，不把部分批次标成新的完整验证。

快照 `deliveries` 保存 `task_id`、`repository_id`、`branch`、`pr_number`、`release_id`、`tag_name`、`commit_sha`（提交关联时）、`head_sha`、`state`、`checks`、`statuses`、`url`、`source`、`sync_at`、`stale`。PR 状态为 `pushed`、`open`、`closed_unmerged`、`merged` 或 `unavailable`；Release 状态为 `draft`、`prerelease`、`published` 或 `unavailable`；来源为 `github_verified`。对象 URL 由已验证仓库名称和对象标识构造，不接收 provider 返回的任意 URL。checks/statuses 只保留对应完整 SHA 的结果；fork commit 的检查在 base 仓库不可访问时显示未知，不向 fork 仓库发送安装 token。缺失 PR、已删分支、不可访问的明确提交或 Release 仅标记对应关联 `unavailable`，不能据此声称对象存在，也不会撤销其他有效证据。

项目活动是从授权 snapshot 现场生成的最多 100 条结构化投影，包括任务、认领/交接、显式进度、会话登记、协作请求状态、约定决策、本地 Git 检查点和已核验 GitHub 交付。每条只保留固定字段与安全引用，不建立第二份活动数据库。完整 agent 会话、prompt、回复、hidden reasoning、tool 输入/输出、request/reply 正文和 raw webhook body 不会读取或显示；只有 agent 明确提交的进度摘要会出现在活动流。

15 分钟未成功同步时标为 stale。安装被删除、暂停、仓库被移出授权范围或稳定仓库身份校验失败时 connection 标为 revoked，当前交付证据与待关联列表不再返回。重新授权后连接 `sync_at` 为空，旧授权期的证据保持隐藏，直到新连接成功核对一次；不会把之前的 SHA 或检查成功状态重新显示为新鲜证据。历史队列摘要保留用于追溯；没有删除文件、数据库记录或原始实验目录。关联 PR 合并只提供交付证据，不修改任务人工验收结果。

## 验证边界

`test_github_app.py` 使用离线 HTTP transport 检查真实 REST adapter；`test_github_sync.py` 使用明确标识的离线 provider 检查真实 SQLite 领域状态；`test_git_routes.py` 使用 ASGI HTTP 请求检查路由。覆盖签名伪造、重复 delivery hash 冲突、签名正确但形状错误的 JSON、重启重试、正文次级限流、错项目、管理员降权、授权状态重放/到期、fork 分支、旧 HEAD 检查、分支当前提交检查、多个不可变提交关联、对象缺失与仓库撤销的区别、PR number 与令牌授权范围不匹配、关闭未合并、权限撤销、重新授权隐藏旧证据、并发响应顺序，以及扫描/检查/请求/时间/关联数量/快照大小预算。

**尚未完成真实 GitHub App 部署验收。** 当前环境没有 App 凭据，离线协议与状态机测试不能证明真实 App 安装、组织权限批准、公网回调、GitHub 事件投递或线上配额行为已验证。部署验收需要使用操作者的 App 与独立测试仓库，分别记录授权、push、PR、检查、force push、安装移除及恢复后的实际事件，不把模拟数据当成线上证据。

官方依据：[App 用户授权及访问交集](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-with-a-github-app-on-behalf-of-a-user)、[App 安装 REST API](https://docs.github.com/en/rest/apps/installations?apiVersion=2026-03-10)、[RS256 JWT](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app)、[当前 Git reference 的检查](https://docs.github.com/en/rest/checks/runs?apiVersion=2026-03-10)、[webhook 最佳实践](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks)。
