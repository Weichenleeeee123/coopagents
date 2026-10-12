# Crewmesh 文档索引

持续维护的文档统一放在本目录，并与对应实现一起提交 Git。仓库根目录 README 负责导航，实验代码目录保留源码和依赖声明。

| 文档 | 内容 |
| --- | --- |
| [Agent 承载空间设计](agent-hosted-spaces-design.md) | 无账号、无需部署网页的轻量协作方向；异地连接、实时事件及 L0–L4 阶段 |
| [共同核心实施计划](agent-hosted-core-plan.md) | 两版共用协作与协议，完整入口组合账号，L-1 回归与阶段提交 |
| [共同核心阶段记录](agent-hosted-core-report.md) | L-1 提取完成、428 项回归及后续联网阶段边界 |
| [当前黑白工业前端](frontend-monochrome-validation.md) | 01 配色 × 05 布局的源码交付、真实指标、回归与浏览器验收 |
| [黑白工业实施计划](frontend-monochrome-plan.md) | 用户确认方向的实施清单 |
| [十套视觉方向](frontend-visual-directions.md) | 配色与布局探索、用户选定的组合 |
| [整体前端设计](frontend-design-proposal.md) | 已确认的视觉统一、页面布局、移动适配与分阶段验收范围 |
| [前端实施计划](frontend-implementation-plan.md) | 账号视图、看板详情、样式整合与浏览器验收步骤 |
| [前端验收记录](frontend-validation.md) | 整体设计交付、回归检查、真实浏览器与移动端证据 |
| [任务依赖与路由](dependencies.md) | 查负责人、依赖答复、明确阅读确认与责任变化语义 |
| [协作闭环验证](collaboration-flow-report.md) | F1–F3 实现、真实协议/网页与原生消费边界 |
| [任务交接与恢复](task-lifecycle.md) | 释放、转交、取消恢复、执行会话隔离和审计协议 |
| [协作闭环计划](collaboration-flow-plan.md) | F1 接入检查点、F2 生命周期与 F3 依赖阶段 |
| [Git 集成验收](git-integration-report.md) | G1/G2/G3 实现、真实克隆及 HTTP/stdio 验证、外部验收边界 |
| [本地 Git 接入](git-local-setup.md) | 原有 agent 工具的 stdio 配置、检查点、项目约定与离线队列 |
| [GitHub App 接入](git-github-setup.md) | 独立仓库授权、只读权限、签名事件、重试与部署配置 |
| [Git 集成设计](git-integration-proposal.md) | 已批准的本地 Git + GitHub 协作范围 |
| [Git 实施计划](git-integration-plan.md) | G1 → G2 → G3 阶段与验证清单 |
| [C2 设计](commercial-c2-design.md) | 已批准的 Stripe 团队月订阅、额度与私有部署边界 |
| [C2 计划](commercial-c2-plan.md) | 订阅领域、支付适配器、账单界面与分阶段验收 |
| [C2 领域接口](c2-domain.md) | 事务额度、计费绑定、结账租约和同步版本接口 |
| [C2 Stripe 接口](c2-stripe.md) | 支付配置、签名、提供方核验与恢复限制 |
| [C2 HTTP 与恢复](c2-http.md) | 账号账单路由、原始签名、独立 worker 与本地维护命令 |
| [C2 账单界面](c2-ui.md) | 英文套餐与用量、所有者操作、异步切换保护及浏览器验收 |
| [C2 配置与运维](c2-operations.md) | 可选托管订阅部署、受保护密钥、事件恢复和真实提供方验收边界 |
| [C2 验收记录](commercial-c2-report.md) | 分阶段测试、独立审查与外部验证边界 |
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
| [Agent 接入](agent-connection.md) | 推荐 Skill 指令、个人凭据与高级手动配置 |
| [轻量接入设计](skill-onboarding-design.md) | 邀请链接与一次复制的 Skill 接入体验 |
| [轻量接入验收](skill-onboarding-report.md) | 账号加入、凭据隔离、发行包与浏览器证据 |
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
