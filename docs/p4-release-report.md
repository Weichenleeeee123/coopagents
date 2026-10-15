# P4 可部署发行版验收

日期：2026-10-10。交付版本：`0.2.0`，按**预发行版**发布。用户确认先完成发行包，实际部署目标稍后提供。部署与备份步骤见 [部署说明](deployment.md)。

## 已取得的证据

| 项目 | 实际结果 |
| --- | --- |
| MIT 与 GitHub Topics | MIT 已识别，12 个 Topics 已设置并读回 |
| 正式服务回归 | Python 3.13 本机 80 项测试通过；覆盖身份、并发认领、消息、版本、HTTP / MCP、公网配置、备份、网页和重启 |
| 历史接入实验 | 21 项回归通过；这些测试不能计为原生 P4 闭环成功 |
| 网页 | JavaScript 语法检查、延迟响应会话隔离、建房密钥仅通过 header 传递的回归通过 |
| 发行包 | `crewmesh-0.2.0-py3-none-any.whl` 构建、资产与 MIT 检查、独立目录安装后导入和服务初始化通过 |
| Docker | 实际构建 `crewmesh:0.2.0`，非 root UID 10001；基础镜像及 Caddy 固定 digest，运行依赖固定版本 |
| TLS / 代理 | 实际运行 Caddy 和独立应用容器，客户端校验测试 CA 及服务器 hostname；12 项部署 smoke 检查通过 |
| Compose 密钥 | 实际启动 Compose 应用，挂载密钥建房成功、health 为 healthy；容器随后停止且卷与证据保留 |
| GitHub CI | 2026-10-11 对 `fd789cc` 的 Python 3.11、3.13 与 container 三个 job 全部成功；容器 job 包含真实 TLS smoke |
| SQLite | 在线备份、完整性检查、新路径恢复、拒绝覆盖；WAL 未 checkpoint 数据也进入备份；容器重启后任务和凭据保留 |
| 原生 Claude Code | 用户修复认证后，实际完成 whoami、认领、会话、进度与发送请求；正式数据库及网页快照相符 |
| 原生 Codex CLI | 两次首次 whoami 调用返回 `user cancelled MCP tool call`；未读取、确认或回复，闭环未通过 |

服务阶段和发行配置分别通过独立需求核对与代码审查。GitHub CI 对 Python 3.11 / 3.13、打包、Docker 与 TLS smoke 进行复验；远端执行结果以 GitHub Actions 对应提交为准，不把工作流文件存在视为运行通过。

远端复验：[成功的 GitHub Actions 运行](https://github.com/Weichenleeeee123/coopagents/actions/runs/38107580009)。发行入口：[v0.2.0 预发行版](https://github.com/Weichenleeeee123/coopagents/releases/tag/v0.2.0)，提供完整 Git 源码 ZIP、Python wheel 和 SHA256 校验清单；仅含受版本管理的源码与文档。

## 容器验收内容

保留的成功运行标识：`coopagents-p4-9638cf7b8ea1`，证据在 `.local/deployment-smoke/<标识>/`。验证了 TLS 证书及 hostname、数据库就绪、UID、后端无映射端口、错误 Host、跨站 Origin、匿名建房拒绝、带密钥建房、网页凭据建任务、个人 agent 凭据 MCP initialize、网页凭据不能用于 MCP、在线备份恢复及容器重启。

首次测试发现代理对未匹配 Host 返回空白 200；增加 Caddy `strict_sni_host on` 后错误 Host 被拒绝。失败运行 `coopagents-p4-875230cdd730` 仍保留，没有删除或篡改结果。测试使用仅此运行信任的私有 CA，未更改系统信任库；正式 Caddyfile 使用公网 ACME 证书流程，尚未实测真实 DNS / ACME。

可复现：

```bash
docker build -t crewmesh:0.2.0 .
python scripts/deployment_smoke.py --image crewmesh:0.2.0
```

脚本会新建测试网络、卷和容器，完成后只停止自己创建的容器。所有文件与卷保留；失败时返回非零并写入结果。不触碰已有正式服务。

## 原生与公网剩余验收

详细原生结果、首次认证失败和重跑证据见 [原生报告](p4-native-report.md)。目前原生请求仍为未读取、未处理、未解决；没有补写回执使结果看起来通过。Codex 取消的具体原因未确定，不能推断为用户主动取消，也不能把 CLI 退出码 0 视为通过。

因此 P4 的部署工程与可复现验收工具已交付，但 **P4 原生双向闭环尚未完成**。预发行标记用于准确表达这一限制。闲置会话自动唤醒、物理双机、公网网络故障及真实域名证书签发没有通过证据。

取得部署目标后执行：DNS / TLS 检查、两位成员各自电脑接入、任务竞争、技术问答及回执、离线恢复、备份恢复演练，再决定是否取消预发行标记。机器配置、令牌、数据库及原始模型会话均不进入 Git 或发行资产。
