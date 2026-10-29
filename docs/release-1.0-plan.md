# 1.0 稳定版就绪计划

产品和 0.8/0.9/1.0 阶段设计见[Coopagents 1.0 产品设计](product-1.0-design.md)。本文维护发布门槛和各环境的验收执行状态。

更新：2026-10-29。当前候选基线为 0.7.4。1.0 的目标是让新用户能在两台真实设备上独立安装、邀请、互相问答、恢复连接，并清楚知道哪些能力已验证、哪些仍依赖网络或工具本身。

## 1.0 范围

1. Coopagents 继续作为由用户设备承载的协作空间；不把托管 SaaS、Stripe 订阅或 OAuth 纳入 1.0 的必要条件。
2. Claude Code、Codex、Cursor、OpenCode、Pi、Kimi Code 和 ZCode 通过共同 MCP 协作协议使用各自身份加入；按 capability matrix 如实区分 MCP 基础能力与各 harness 原生 hook/唤醒能力。
3. P2P 优先；连接失败时明确显示直连/中继/离线状态。主机停止、重启后，成员不需要重复加入。
4. Claude 空闲唤醒和 Codex 待命是可选能力，分别通过真实原生 hook 流程验收，权限与中断方式清楚。
5. Windows、macOS、Linux 的安装与核心协作路径有可重复的 CI 或人工证据；不以单机模拟代替双机证据。

## 发布门槛

| 门槛 | 当前证据 | 1.0 前要求 |
| --- | --- | --- |
| 单机真实 agent 闭环 | 2026-10-29 真实 Claude/Codex 四步验收 17 项通过 | 保持 CI 与真实验收回归 |
| 不同网络间 P2P | GitHub Actions runner 到家用设备的既有报告 | 至少两位用户、两台设备；分别记录 direct/relay 与无代理结果 |
| 双方都在 NAT 后 | 尚无证据 | 家庭 Wi-Fi/移动热点至少一组；验证邀请、双向问答、重启恢复 |
| 跨电脑唤醒 | 单机 Claude 闲置唤醒通过 | 远端 Claude 与 Codex 各自完成一次；区分通知到达和模型实际回复 |
| Multi-harness | Claude Code/Codex 单机完整闭环；Cursor/OpenCode/Pi/Kimi Code/ZCode 官方 MCP/hook/ACP 能力已拆分 | 七个 harness 的 MCP 基础加入和任务闭环；各自 native hook 只在官方提供且真实验收通过时声明 |
| Windows/macOS/Linux | Windows Git Bash、PowerShell、cmd hook 测试通过 | 三个平台按 harness capability matrix 完成 CLI/MCP 安装和闭环；native hook 逐组合单测，不跨平台外推 |
| 发行包与容器 | Python/网页 CI 已覆盖；本机 Docker Engine 当前不可用 | 新 v0.7.4 GitHub CI 全绿；干净 wheel 安装；容器 smoke 由 CI 提供新证据 |
| 真实 GitHub App | 0.8 实现已完成；没有配置真实 App，尚无线上验收证据。该项明确延期到 1.0，不阻塞进入 0.9 | 使用专用测试仓库验证真实 App 安装与只读权限、用户授权 callback/finish、branch/PR/checks/Release 读取、签名 webhook 投递及补偿同步、移除安装后的撤权，以及重新授权后的恢复；记录每步的服务端状态和 GitHub 侧事件 |
| 运维与安全 | 邀请/成员撤销、备份恢复有单元和单机证据 | 两设备运行手册、恢复/撤销演练、威胁模型和已知网络限制同步 |

## 阶段

1. 发布 0.7.4：包含紧凑 v2 邀请、Windows hook 启动修复和已通过的单机真实验收。
2. 双机试点：按[双机验收清单](two-machine-acceptance.md)招募两位参与者；原始结果留在本机，维护文档只记录脱敏的事实与失败。
3. 缺陷收敛：每个双机失败都先保留日志，再写回归测试；不以扩大权限、禁用安全边界或重复重试至成功代替根因修复。
4. 1.0 候选：冻结功能，完成 Python 3.11/3.13、网页、打包、容器 smoke、干净安装和两平台原生验收；所有未通过门槛必须在发布说明中明确，关键闭环不得留空。
5. 真实 GitHub App 验收：在 1.0 候选期使用专用测试仓库执行上表完整流程；保存脱敏的 GitHub 事件与服务端状态证据。离线 provider、HTTP mock 和单元测试只证明本地实现，不计为线上 App 验收。
6. 1.0 正式版：候选验收通过后再改版本号、更新发行说明、打签名 tag、发布 GitHub 资产并由可信发布工作流上传 PyPI。若真实 App 验收仍未完成，必须在发布说明中标为未验证，不能宣称 GitHub App 端到端已通过。

## 不计为通过的证据

- 同一台电脑的两个 profile 不等于两位用户的两台设备。
- SDK/单元测试不等于 Claude Code 或 Codex 原生 CLI 的真实交互。
- WebSocket 事件到达不等于闲置模型已读取、理解或回复。
- Docker CLI 可启动不等于 Docker Engine 可用；历史 smoke 结果不能替代 1.0 候选构建。
- agent 的自然语言“已完成”不等于服务器状态、MCP 注册、hook 或用户收到回复的证据。
