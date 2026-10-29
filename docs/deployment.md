# 自托管部署与运维

发行版支持单实例服务、SQLite 持久卷和 Caddy HTTPS。实际公网部署目标尚未提供；当前 0.4.0rc1 C2 代码与测试候选版验收见 [C2 报告](commercial-c2-report.md)，历史容器与原生验收事实见 [P4 报告](p4-release-report.md)。需要 Docker Engine / Compose、能解析到服务器的域名及可用的 TCP 80/443 端口。不要直接暴露应用的 8787 端口。

## 首次部署

1. 下载发行版或克隆仓库。复制 `.env.example` 为 `.env`，把 `COOPAGENTS_DOMAIN` 改成真实域名（仅域名，不带协议或路径）。配置 DNS A / AAAA，确认对应服务器可达。仅配置实际可用的 IPv6 地址。
2. 生成首次账号初始化 / 旧版建房密钥，保存在未提交的 `.local/`。以下 Python 命令在 Windows / Linux 均可执行，使用独占创建，已有文件会拒绝覆盖：

```bash
python -c "import pathlib,secrets; p=pathlib.Path('.local'); p.mkdir(exist_ok=True); f=(p/'bootstrap-secret.txt').open('x'); f.write(secrets.token_urlsafe(32)); f.close()"
```

Linux 上限制 `.local/` 目录权限为 `700`；密钥文件需允许容器 UID 10001 读取，例如在受保护目录内使用 `644`。Compose 本地文件 secrets 实际采用只读挂载，不会自动替你更改宿主文件所有者。不要把密钥放进命令参数、聊天、Git 或 URL。

3. 启动并检查：

```bash
docker compose --env-file .env config --quiet
docker compose --env-file .env up -d --build
docker compose ps
```

Caddy 自动申请并续期证书。首次签发依赖真实 DNS 和公网端口，可查看 `docker compose logs --tail=100 proxy app` 排查；默认未启用访问日志，仍应妥善保护运维日志。

4. 打开 `https://你的域名/`，首次初始化账号时输入密钥、用户名与 12–256 字符密码。首次账号创建后入口关闭。登录后创建团队，再创建项目；新项目初始仅授权创建者。管理员创建团队邀请并明确角色及项目范围，邀请 24 小时内有效且单次使用。新成员通过邀请注册，已有账号登录后接受邀请。MCP 地址是 `https://你的域名/mcp`，每位 agent 使用自己的项目令牌。
5. 验收 `/health`、`/ready`、团队加入、两个成员的任务抢占、MCP 问答、重启后的消息以及外部网络连接。容器本地验收不能代替此步骤。

## 配置与边界

| 配置 | 用途 |
| --- | --- |
| `COOPAGENTS_MODE` | 默认 `self-hosted`，本地认证不需要官方网络；`cloud` 仅在明确配置 GitHub OAuth 时启用 |
| `COOPAGENTS_HOST` / `COOPAGENTS_PORT` | 默认 `127.0.0.1:8787`；非回环地址必须同时配置公网模式 |
| `COOPAGENTS_PUBLIC_URL` | 严格 HTTPS origin，例如 `https://coopagents.example.com`；不接受路径、查询或用户信息 |
| `COOPAGENTS_BOOTSTRAP_SECRET_FILE` | 公网建房密钥文件；也可配置 `COOPAGENTS_BOOTSTRAP_SECRET`，二者不能同时设置 |
| `COOPAGENTS_TRUSTED_PROXIES` | 明确的代理 IP / CIDR；默认不信任代理，禁止 `*` 或全网范围 |
| `COOPAGENTS_DATABASE` | 数据库路径；Compose 默认 `/data/coopagents.sqlite3` |

Compose 中仅代理发布端口，应用无宿主端口映射。内部固定网段为 `172.30.87.0/24`，只信任代理 `.2`。如与现有网络冲突，必须同时修改网段、两个静态地址及受信代理配置。不要将受信范围扩大为全网。

公网模式仍适用于小团队单实例自托管。本地账号支持管理员重置、本人修改密码及离线恢复；没有电子邮件恢复或闲置 agent 唤醒。团队角色与项目权限独立，加入团队不会自动获得所有项目。需在公网入口根据实际流量配置连接限额、请求限流和主机监控；应用的正文大小限制不能代替流量防护。部署前评估主机与卷访问权限，不共享敏感源码、令牌或客户数据作为演示消息。

## 一致备份

SQLite 在线备份命令可在服务运行时执行，不要直接复制活跃数据库主文件来代替一致备份。每次使用新的目标名称：

```bash
docker compose exec app python -m coopagents.backup backup /data/coopagents.sqlite3 /data/backups/coopagents-20261010-01.sqlite3
docker compose cp app:/data/backups/coopagents-20261010-01.sqlite3 .local/coopagents-20261010-01.sqlite3
```

项目资产内容存于 `/data/coopagents.sqlite3.assets/`，SQLite 单文件备份不包含这些内容。含项目资产时必须成对备份数据库和资产目录，并将两份产物一起复制到受保护的独立介质：

```bash
docker compose exec app python -m coopagents.backup backup /data/coopagents.sqlite3 /data/backups/coopagents-20261010-01.sqlite3 --assets-source /data/coopagents.sqlite3.assets --assets-destination /data/backups/coopagents-20261010-01.sqlite3.assets
docker compose cp app:/data/backups/coopagents-20261010-01.sqlite3 .local/coopagents-20261010-01.sqlite3
docker compose cp app:/data/backups/coopagents-20261010-01.sqlite3.assets .local/coopagents-20261010-01.sqlite3.assets
```

备份包含账号、成员、凭据哈希、所有团队消息及完整 billing ledger（catalog、bindings、事件、lease、audit、出站与 Checkout idempotency keys），应像生产数据一样保护并额外保存到独立介质。命令校验数据库完整性，拒绝覆盖已有目标。失败时任何部分文件保留，使用新的目标重试；本项目不自动删除文件。

## 恢复、升级与回退

恢复会写入新文件，不覆盖原数据库。若备份含项目资产，使用成对恢复命令：

```bash
docker compose exec app python -m coopagents.backup restore /data/backups/coopagents-20261010-01.sqlite3 /data/restored-20261010-01.sqlite3 --assets-source /data/backups/coopagents-20261010-01.sqlite3.assets --assets-destination /data/restored-20261010-01.sqlite3.assets
docker compose stop app
```

没有项目资产的旧部署继续使用仅传数据库路径的单文件恢复命令。

在 `.env` 设置 `COOPAGENTS_DATABASE=/data/restored-20261010-01.sqlite3`，再执行 `docker compose up -d app`。通过网页检查房间、任务、消息和 MCP 认证，保留旧文件以便回退。启用 billing 时保留原 mode/catalog 与所有出站 key，按 [C2 运维](c2-operations.md) 进行 bounded canonical reconcile 与到期 retry；不得删除账本或重置 key。恢复历史备份也会恢复当时的令牌状态，可能让备份后已撤销的令牌重新有效；恢复后立即轮换相关成员的 agent 令牌，重新签发邀请并确认网页凭据的有效性。

升级前做一致备份并记录镜像版本 / digest。领取新版源码或发行包，更新 `COOPAGENTS_VERSION`，运行 `docker compose up -d --build`，检查就绪状态和业务数据。本版数据库升级为附加字段；未来版本能否降级需阅读变更说明。回退代码时仍保留原卷，必要时从升级前备份恢复到新路径。

停止使用 `docker compose stop`，会保留容器和卷。不要使用删除容器、卷或文件的清理命令。证书数据保存在独立卷，应随服务迁移保护。

## C1 账号、迁移和代理

账号 Cookie 为 HttpOnly / SameSite=Lax，公网 HTTPS 下为 Secure，有效七天。所有账号写请求校验精确 Origin，已登录写请求还需要会话绑定的 `X-Coopagents-CSRF`。反向代理必须保留 Host，并只从指定代理接受转发协议；应用的 `COOPAGENTS_PUBLIC_URL` 必须与浏览器实际 origin 相同。账号 Cookie 不能当作项目或 MCP bearer 令牌。

团队 owner 可管理所有团队角色；admin 只可管理普通成员，不能修改 owner/admin 身份。最后一个 owner 不能被移除或降级。团队成员仅可使用明确授予的项目，创建项目不会自动授权其他成员。移除成员撤销其项目凭据和其未使用邀请；降级使此前管理员邀请失效。密码重置撤销该账号全部会话，其派生的项目网页凭据立即不可用；独立 agent 凭据需另行轮换。

升级前一致备份。数据库迁移只新增字段/表，保留历史项目、消息、任务和凭据。在团队入口选择认领旧项目，输入该项目有效的 owner 网页凭据；普通协作者、agent 令牌或新账号同名不能认领。认领只绑定有 owner 证明的账号，旧协作者凭据仍可访问原项目；他们不会自动获得团队账号权限。已认领项目通过团队权限管理邀请，原项目邀请失效。

## 离线本地密码恢复

先做一致备份并停止 app，保留数据库和旧备份。具有本机数据库文件读写权限的运维人员可执行：

```bash
docker compose stop app
docker compose run --no-deps --name coopagents-recovery-20261011-01 app python -m coopagents.account_recovery --database /data/coopagents.sqlite3 --username owner
docker compose up -d app
```

每次使用新的容器名称，保留恢复容器。CLI 隐藏输入两次新密码，没有密码命令参数；只更新已存在数据库中的规范化本地用户名，不新建账号或数据库，不通过网络或 HTTP 管理员后门。GitHub-only 身份没有本地密码，不能用此命令恢复。账号密码与全部账号会话失效在同一事务提交，任何失败回滚。恢复后重新登录并核验团队和项目，按需要轮换 agent 令牌。

文件访问权限本身是最高权限：能修改 SQLite 的人也能改账号和授权。限制卷与备份访问，备份包括密码摘要、会话状态和 OAuth 绑定，不能公开。恢复历史备份可能重新激活旧会话；恢复后进行账号密码重置与相关 agent 令牌轮换。

## 可选 cloud GitHub OAuth

默认 Compose 只挂载 bootstrap secret，不要求不存在的 GitHub 密钥文件。直接运行 cloud 服务不需要 bootstrap secret；Compose 覆盖方式保留基础文件的挂载，但 cloud 不开放账号初始化。官方部署目标尚未确定。配置 cloud 时注册真实 GitHub OAuth App，回调必须精确为 `https://你的域名/account/oauth/github/callback`；账号按 GitHub 数字 ID 绑定，不按邮箱或用户名合并。

直接启动服务时设置 `COOPAGENTS_MODE=cloud`、`COOPAGENTS_PUBLIC_URL`、`COOPAGENTS_GITHUB_CLIENT_ID`，以及 `COOPAGENTS_GITHUB_CLIENT_SECRET_FILE` 指向服务器上受保护文件（或互斥的 `COOPAGENTS_GITHUB_CLIENT_SECRET`）。Compose 可使用保存在忽略目录的覆盖文件，显式将受保护的 GitHub secret 挂载给 app 并设置文件路径；仅在启用 cloud 时加载该覆盖文件。不要把 secret 值写入受版本控制的 YAML、URL 或日志。示例覆盖文件：

```yaml
services:
  app:
    environment:
      COOPAGENTS_MODE: cloud
      COOPAGENTS_GITHUB_CLIENT_ID: ${COOPAGENTS_GITHUB_CLIENT_ID:?Configure GitHub client ID}
      COOPAGENTS_GITHUB_CLIENT_SECRET_FILE: /run/secrets/github
    secrets:
      - github
secrets:
  github:
    file: ${COOPAGENTS_GITHUB_SECRET_FILE:?Configure protected server secret path}
```

将覆盖文件保存为 `.local/compose-cloud.yaml`，在未提交的 `.env` 中设置 ID 和 secret 文件路径，然后运行 `docker compose --env-file .env -f compose.yaml -f .local/compose-cloud.yaml config --quiet` 和相同参数的 `up -d --build`。密钥文件需允许 UID 10001 读取；支持有限长度文件，缺失/部分/冲突配置会启动失败。Cloud 关闭本地登录/初始化/密码重置，用户通过 GitHub 登录创建团队或接受团队邀请。只有 OAuth 交换需要访问 GitHub，自托管默认没有这项依赖。代码及隔离测试不等于真实 OAuth 登录已通过；目前没有提供方凭据，真实回调未验收。

## 可选 cloud 月付订阅

默认自托管无需 Stripe/GitHub secret 文件。无 billing 配置的 cloud 仍要求账号 GitHub OAuth，但为 Unlimited，没有 webhook 或支付 worker。需要订阅时使用受版本控制的 `deploy/compose.cloud-billing.yaml`，它强制 cloud 并要求账号 OAuth、匹配 test/live 的 Stripe key 与 endpoint signing secret、实际固定月付 Price ID 和四项明确正整数 cap。基础 bootstrap 挂载保留，cloud 不使用账号初始化入口；与只读 App 的 `compose.github.yaml` 独立。

```bash
docker compose --env-file .env -f compose.yaml -f deploy/compose.cloud-billing.yaml config --quiet
docker compose --env-file .env -f compose.yaml -f deploy/compose.cloud-billing.yaml up -d --build
```

全部密钥留在服务器受保护文件，允许 UID 10001 读取。实际 Price、Portal 限制、API `2026-09-30.endive` webhook 注册、容量/付款核验、durable retries 和恢复步骤见 [C2 运维](c2-operations.md)。当前无真实 Stripe/OAuth/public callback 验收，C3 保持暂停，代码与容器通过不能等同于官方付费服务上线。
