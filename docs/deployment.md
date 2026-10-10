# 自托管部署与运维

发行版支持单实例服务、SQLite 持久卷和 Caddy HTTPS。实际公网部署目标尚未提供；本地容器与原生验收事实见 [P4 报告](p4-release-report.md)。需要 Docker Engine / Compose、能解析到服务器的域名及可用的 TCP 80/443 端口。不要直接暴露应用的 8787 端口。

## 首次部署

1. 下载发行版或克隆仓库。复制 `.env.example` 为 `.env`，把 `CREWMESH_DOMAIN` 改成真实域名（仅域名，不带协议或路径）。配置 DNS A / AAAA，确认对应服务器可达。仅配置实际可用的 IPv6 地址。
2. 生成管理员建房密钥，保存在未提交的 `.local/`。以下 Python 命令在 Windows / Linux 均可执行，使用独占创建，已有文件会拒绝覆盖：

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

4. 打开 `https://你的域名/`，在创建团队时输入管理员建房密钥。保存个人网页凭据及 agent 令牌；普通队友用单次邀请加入，不需要管理员密钥。MCP 地址是 `https://你的域名/mcp`，每位 agent 使用自己的令牌。
5. 验收 `/health`、`/ready`、团队加入、两个成员的任务抢占、MCP 问答、重启后的消息以及外部网络连接。容器本地验收不能代替此步骤。

## 配置与边界

| 配置 | 用途 |
| --- | --- |
| `CREWMESH_HOST` / `CREWMESH_PORT` | 默认 `127.0.0.1:8787`；非回环地址必须同时配置公网模式 |
| `CREWMESH_PUBLIC_URL` | 严格 HTTPS origin，例如 `https://crewmesh.example.com`；不接受路径、查询或用户信息 |
| `CREWMESH_BOOTSTRAP_SECRET_FILE` | 公网建房密钥文件；也可配置 `CREWMESH_BOOTSTRAP_SECRET`，二者不能同时设置 |
| `CREWMESH_TRUSTED_PROXIES` | 明确的代理 IP / CIDR；默认不信任代理，禁止 `*` 或全网范围 |
| `CREWMESH_DATABASE` | 数据库路径；Compose 默认 `/data/crewmesh.sqlite3` |

Compose 中仅代理发布端口，应用无宿主端口映射。内部固定网段为 `172.30.87.0/24`，只信任代理 `.2`。如与现有网络冲突，必须同时修改网段、两个静态地址及受信代理配置。不要将受信范围扩大为全网。

公网模式仍适用于小团队单实例自托管。无账号密码重置、电子邮件或闲置 agent 唤醒；凭据持有者能查看本团队上下文，明文持有者凭据丢失需重新加入。需在公网入口根据实际流量配置连接限额、请求限流和主机监控；应用的正文大小限制不能代替流量防护。部署前评估主机与卷访问权限，不共享敏感源码、令牌或客户数据作为演示消息。

## 一致备份

SQLite 在线备份命令可在服务运行时执行，不要直接复制活跃数据库主文件来代替一致备份。每次使用新的目标名称：

```bash
docker compose exec app python -m crewmesh.backup backup /data/crewmesh.sqlite3 /data/backups/crewmesh-20261010-01.sqlite3
docker compose cp app:/data/backups/crewmesh-20261010-01.sqlite3 .local/crewmesh-20261010-01.sqlite3
```

备份包含成员、凭据哈希及所有团队消息，应像生产数据一样保护并额外保存到独立介质。命令校验数据库完整性，拒绝覆盖已有目标。失败时任何部分文件保留，使用新的目标重试；本项目不自动删除文件。

## 恢复、升级与回退

恢复会写入新文件，不覆盖原数据库：

```bash
docker compose exec app python -m crewmesh.backup restore /data/backups/crewmesh-20261010-01.sqlite3 /data/restored-20261010-01.sqlite3
docker compose stop app
```

在 `.env` 设置 `CREWMESH_DATABASE=/data/restored-20261010-01.sqlite3`，再执行 `docker compose up -d app`。通过网页检查房间、任务、消息和 MCP 认证，保留旧文件以便回退。恢复历史备份也会恢复当时的令牌状态，可能让备份后已撤销的令牌重新有效；恢复后立即轮换相关成员的 agent 令牌，重新签发邀请并确认网页凭据的有效性。

升级前做一致备份并记录镜像版本 / digest。领取新版源码或发行包，更新 `CREWMESH_VERSION`，运行 `docker compose up -d --build`，检查就绪状态和业务数据。本版数据库升级为附加字段；未来版本能否降级需阅读变更说明。回退代码时仍保留原卷，必要时从升级前备份恢复到新路径。

停止使用 `docker compose stop`，会保留容器和卷。不要使用删除容器、卷或文件的清理命令。证书数据保存在独立卷，应随服务迁移保护。
