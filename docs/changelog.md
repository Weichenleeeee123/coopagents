# 版本记录

## 0.2.0 — 2026-10-10（预发行）

- 增加显式 HTTPS 公网配置、严格 Host / Origin 检查、独立管理员建房密钥和代理信任。
- MCP 保留认证与 DNS rebinding 保护，新增数据库就绪检查。
- 非 root Docker 镜像、Caddy TLS、Compose 持久卷、固定镜像 digest 与运行依赖、GitHub CI。
- 在线 SQLite 一致备份和新路径恢复，拒绝覆盖既有数据。
- 单机多成员抢占、离线请求与重启持久化验收；真实 TLS 容器验收；打包安装验证。
- MIT License 与仓库 Topics。
- Claude 原生正式服务单向接入通过；Codex 原生 MCP 调用取消仍待解决，完整双向闭环与真实公网部署未验收。

## 0.1.0

本机认证 HTTP / MCP、任务与成员、技术请求、不可变约定版本、人工决定与自动任务看板。
