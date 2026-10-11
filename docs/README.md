# Crewmesh 文档索引

持续维护的文档统一放在本目录，并与对应实现一起提交 Git。仓库根目录 README 负责导航，实验代码目录保留源码和依赖声明。

| 文档 | 内容 |
| --- | --- |
| [Git 集成验收](git-integration-report.md) | G1/G2/G3 实现、真实克隆及 HTTP/stdio 验证、外部验收边界 |
| [本地 Git 接入](git-local-setup.md) | 原有 agent 工具的 stdio 配置、检查点、项目约定与离线队列 |
| [GitHub App 接入](git-github-setup.md) | 独立仓库授权、只读权限、签名事件、重试与部署配置 |
| [Git 集成设计](git-integration-proposal.md) | 已批准的本地 Git + GitHub 协作范围 |
| [Git 实施计划](git-integration-plan.md) | G1 → G2 → G3 阶段与验证清单 |
| [C2 设计](commercial-c2-design.md) | 已批准的 Stripe 团队月订阅、额度与私有部署边界 |
| [C2 计划](commercial-c2-plan.md) | 订阅领域、支付适配器、账单界面与分阶段验收 |
| [Stripe 实施参考](c2-stripe-reference.md) | 固定 API 版本、账期字段、事件和风险核验依据 |
| [C1 验收](commercial-c1-report.md) | 账号、多项目、迁移与恢复的验证边界 |
| [C1 设计](commercial-c1-design.md) | 已批准的完整开源身份与工作区设计 |
| [C1 计划](commercial-c1-plan.md) | 分阶段源码、测试、部署与验收 |
| [商业化提案](commercialization-proposal.md) | 完整开源及官方托管订阅；C2 实施中，C3 暂缓 |
| [版本记录](changelog.md) | 候选版与历史发行变化 |
| [部署与运维](deployment.md) | Docker / Caddy HTTPS、密钥、持久卷、备份恢复与升级 |
| [P4 发行计划](p4-release-plan.md) | 可部署发行版的阶段与验收边界 |
| [P4 发行验收](p4-release-report.md) | 实测容器 / TLS / 安装结果及未通过项 |
| [P4 原生验收](p4-native-report.md) | Claude 实际接入与 Codex 取消证据 |
| [看板升级](kanban-plan.md) | 自动分列、筛选、任务详情与浏览器验收 |
| [品牌资产](brand-assets.md) | 生成图标、提示词、文件校验与演示截图 |
| [仓库结构](repository-layout.md) | 目录职责、迁移记录与服务恢复验证 |
| [P2/P3 实施计划](p2-p3-plan.md) | 状态、消息、约定、认证服务和网页的实施与验收 |
| [P2/P3 验证报告](p2-p3-report.md) | 正式共享服务与网页的实际完成情况 |
| [Agent 接入](agent-connection.md) | 个人令牌、Codex / Claude Code 配置与协作检查点 |
| [本机运行](app-running.md) | 正式服务启动、数据位置、停止与备份 |
| [后续路线](roadmap.md) | P2 共享服务、P3 网页、P4 双机的任务和验收状态 |
| [共享服务计划](shared-service-plan.md) | 当前身份基础与任务认领的具体实施步骤 |
| [共享服务报告](shared-service-report.md) | P2 已实现能力和验证结果 |
| [产品设计](agent-team-room-design.md) | 使用场景、协作机制、网页范围与权限边界 |
| [接入实施计划](crewmesh-implementation-plan.md) | 分阶段任务及验收标准 |
| [接入验证报告](crewmesh-integration-report.md) | 已取得的证据、版本、限制和 Git 提交 |
| [实验运行说明](integration-lab.md) | 环境准备、配置生成、服务运行和原生入口验证 |
| [原生 CLI 实验](native-cli-validation.md) | 真实启动、hook 事件、组织策略和配置兼容性阻塞 |

`experiments/agent-integration/archive/` 中的源代码包是历史交付快照。最新事实和运行方式以本目录及仓库源码为准。接入原始证据保留在 `.local/agent-integration/evidence/`，共享服务测试数据库保留在 `.local/test-evidence/`；文档只纳入经过检查的结论，避免把机器路径配置、凭据或用户真实对话加入 Git。
