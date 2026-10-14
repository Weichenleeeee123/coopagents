# 版本记录

## 未发布 — 点对点异地入口

- 本机空间默认 `--network p2p`：成员按主机公钥经 iroh 直连，失败时走加密中继；无需公网地址、账号或隧道程序，主机重启后邀请与成员 profile 仍有效。
- 成员链路绑定与主机相同的回环端口，HTTP/MCP/WebSocket 与 Host/Origin 校验不变；`space` 依赖组加入 `iroh==1.1.0`。
- 跨网络产品验收（GitHub Actions 主机 ↔ 本机成员）通过：加入、MCP 桥接、实时事件、主机重启自动恢复。双方都在家用/移动 NAT 后、境内无代理连通性未验证。见 [p2p 报告](agent-hosted-p2p-report.md)。

## 0.5.0rc1 — Agent 承载空间候选版（2026-10-12）

- 无账号的本机空间、个人单次邀请、成员撤销、保留数据的重启恢复；主机控制端口与公网协作端口分离。
- 两版共用协作核心、HTTP/MCP 操作与事务内持久事件；WebSocket 提供失效通知、认证撤销和游标重放。
- `crewmesh-space` Skill、私有 stdio 桥接、并发有界事件缓存；人类管理使用明确授权的独立 helper。
- 可选主机本地只读看板与托管看板共用卡片、自动分列和实时客户端；查看不改变消息消费状态。
- 本机使用 `space` 依赖组，完整服务继续使用 `service`；支持经校验的第三方临时隧道或已有 HTTPS，维护者不运营中继。
- 真实 Claude/Codex 与单机公网双成员协作已有独立证据；真实异地双机、稳定公网服务和闲置模型自动唤醒未作为通过项。完整结果见 [本轮发行报告](agent-hosted-release-report.md)。

## 0.4.0rc1 — C2 代码与测试候选版（2026-10-11）

- 可选 cloud 固定月付 Team 订阅，Free / Team 活跃账号成员与绑定项目事务限额；完整 MIT 自托管和无订阅 cloud 保持 Unlimited。
- 持久 billing ledger、出站 idempotency keys、签名 raw webhook、规范当前 invoice/payment/退款/争议核验、backoff/lease 与 bounded 维护 CLI。
- 账号中心 Plan & billing、实际 Price/用量、owner 付款操作、Cookie/CSRF 和失效响应/跳转保护。
- 可选 `deploy/compose.cloud-billing.yaml` 明确要求账号 OAuth、Stripe mode/Price/受保护文件和四项 cap；默认 Compose 不要求提供方密钥。
- 默认自托管 Docker/Caddy TLS smoke 增加 Unlimited、禁用付款、Billing/Git 资产与重启/恢复验证；当前实际结果由 [C2 报告](commercial-c2-report.md) 记录。
- 尚无真实 Stripe 账号/Price/付款、外部 webhook、真实 OAuth 或 C3 官方运营验收；保留 v0.2.0 / v0.3.0rc1 既有发行资产，不宣称付费服务上线。
- 合并以下 Git 仓库集成成果，保留 Billing/Git HTTP、worker 与前端回归共存。

### Git 仓库集成（2026-10-11）

- 本地只读 stdio MCP 适配器，版本化项目约定、实际变更检查点、事务离线队列与精确路径重叠。
- 独立只读 GitHub App，项目管理者授权及负责人 agent 关联提交/分支/PR；签名持久队列、当前 HEAD 检查、限流与补偿同步。
- 看板展示独立证据来源和新鲜度，关联远端状态自动分列；仓库接入与任务详情支持配置及关联。
- 真实本机双克隆、HTTP/stdio 与浏览器验证；真实 GitHub App、跨电脑和公网验收仍待配置。详见 [报告](git-integration-report.md)。

## 0.3.0rc1 — C1 候选版（2026-10-11）

- 完整 MIT 开源账号、团队与多项目入口；自托管本地密码登录、首次密钥初始化和邀请注册，不依赖官方网络或许可服务。
- 七天账号 Cookie 会话、Origin / CSRF 校验、显式项目授权、成员角色管理、会话与成员撤销。
- 历史项目通过有效 owner 网页凭据认领，保留数据及历史协作者身份。
- 配置后可启用 cloud GitHub OAuth；真实提供方登录尚未验收。
- 增加本机文件权限授权的离线密码恢复 CLI；保留备份、新路径恢复和项目 MCP 工作流。
- 当前验收结果及外部阻塞见 [C1 报告](commercial-c1-report.md)。C2 支付与 C3 官方运维尚未交付；保留既有 v0.2.0 发行资产。

## 0.2.0 — 2026-10-11（预发行）

- 增加显式 HTTPS 公网配置、严格 Host / Origin 检查、独立管理员建房密钥和代理信任。
- MCP 保留认证与 DNS rebinding 保护，新增数据库就绪检查。
- 非 root Docker 镜像、Caddy TLS、Compose 持久卷、固定镜像 digest 与运行依赖、GitHub CI。
- 在线 SQLite 一致备份和新路径恢复，拒绝覆盖既有数据。
- 单机多成员抢占、离线请求与重启持久化验收；真实 TLS 容器验收；打包安装验证。
- MIT License 与仓库 Topics。
- Claude 原生正式服务单向接入通过；Codex 原生 MCP 调用取消仍待解决，完整双向闭环与真实公网部署未验收。

## 0.1.0

本机认证 HTTP / MCP、任务与成员、技术请求、不可变约定版本、人工决定与自动任务看板。
